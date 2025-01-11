"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import asyncio
from typing import List, Optional
import pulsectl
from loguru import logger

from ..models import AudioSource, DeviceState, SystemState, DeviceType


class AudioManager:
    def __init__(self):
        try:
            self.pulse = pulsectl.Pulse("pi-audio-sync")
            self._init_audio()
        except Exception as e:
            logger.error(f"Failed to initialize PulseAudio: {e}")
            raise

    def _init_audio(self):
        """Initialize audio devices and combined sink"""
        try:
            # Get all sinks
            sinks = self.pulse.sink_list()
            logger.info(f"Found {len(sinks)} audio sinks")

            if not sinks:
                logger.error("No audio sinks found")
                return

            # Try to find or create combined sink
            try:
                combined = next((s for s in sinks if s.name == "combined"), None)
                if not combined and len(sinks) > 1:
                    logger.info("Creating combined sink")
                    sink_names = [s.name for s in sinks]
                    logger.debug(f"Available sinks: {sink_names}")
                    self.pulse.module_load(
                        "module-combine-sink",
                        f"sink_name=combined slaves={','.join(sink_names)}",
                    )
                    logger.info("Combined sink created successfully")
                elif not combined:
                    logger.info("Only one sink available, skipping combined sink")
            except Exception as e:
                logger.error(f"Failed to create combined sink: {e}")
                logger.info("Continuing with individual sinks")

            # Set default sink
            try:
                default = next(
                    (s for s in sinks if "bcm2835" in s.name.lower()), sinks[0]
                )
                self.pulse.default_set(default)
                logger.info(f"Set default sink to: {default.name}")
            except Exception as e:
                logger.error(f"Failed to set default sink: {e}")

        except Exception as e:
            logger.error(f"Error initializing audio: {e}")
            # Don't raise here, let the service continue with limited functionality

    def get_devices(self) -> List[DeviceState]:
        """Get list of audio devices"""
        try:
            sinks = self.pulse.sink_list()
            return [
                DeviceState(
                    id=sink.index,
                    name=sink.description or sink.name,
                    type=DeviceType.USB
                    if "usb" in sink.name.lower()
                    else DeviceType.BUILTIN,
                    volume=int(sink.volume.value_flat * 100),
                    muted=bool(sink.mute),
                    active=True,
                )
                for sink in sinks
            ]
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return []

    def set_volume(self, device_id: int, volume: int) -> bool:
        """Set volume for a device"""
        try:
            volume = max(0, min(100, volume))  # Clamp volume between 0 and 100
            sink = self.pulse.sink_info(device_id)
            self.pulse.volume_set_all_chans(sink, volume / 100)
            logger.info(f"Set volume to {volume}% for sink {sink.name}")
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False

    def set_mute(self, device_id: int, muted: bool) -> bool:
        """Set mute state for a device"""
        try:
            sink = self.pulse.sink_info(device_id)
            self.pulse.mute(sink, muted)
            logger.info(f"{'Muted' if muted else 'Unmuted'} sink {sink.name}")
            return True
        except Exception as e:
            logger.error(f"Error setting mute: {e}")
            return False

    def get_system_state(self) -> SystemState:
        """Get current system state"""
        return SystemState(devices=self.get_devices())
