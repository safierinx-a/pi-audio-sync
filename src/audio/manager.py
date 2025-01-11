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
        self.pulse = pulsectl.Pulse("pi-audio-sync")
        self._init_audio()

    def _init_audio(self):
        """Initialize audio devices and combined sink"""
        try:
            # Get all sinks
            sinks = self.pulse.sink_list()
            logger.info(f"Found {len(sinks)} audio sinks")

            # Create combined sink if needed
            combined = next((s for s in sinks if s.name == "combined"), None)
            if not combined:
                logger.info("Creating combined sink")
                slaves = ",".join(s.name for s in sinks)
                self.pulse.module_load(
                    "module-combine-sink", f"sink_name=combined slaves={slaves}"
                )

            # Set as default
            self.pulse.default_set(combined or sinks[0])

        except Exception as e:
            logger.error(f"Error initializing audio: {e}")
            raise

    def get_devices(self) -> List[DeviceState]:
        """Get list of audio devices"""
        try:
            sinks = self.pulse.sink_list()
            return [
                DeviceState(
                    id=sink.index,
                    name=sink.description,
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
            sink = self.pulse.sink_info(device_id)
            self.pulse.volume_set_all_chans(sink, volume / 100)
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False

    def set_mute(self, device_id: int, muted: bool) -> bool:
        """Set mute state for a device"""
        try:
            sink = self.pulse.sink_info(device_id)
            self.pulse.mute(sink, muted)
            return True
        except Exception as e:
            logger.error(f"Error setting mute: {e}")
            return False

    def get_system_state(self) -> SystemState:
        """Get current system state"""
        return SystemState(devices=self.get_devices())
