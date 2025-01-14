"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import subprocess
from typing import List, Optional
from loguru import logger

from ..models import AudioSource, DeviceState, SystemState, DeviceType


class AudioManager:
    def __init__(self):
        try:
            # Check if PipeWire is running
            result = subprocess.run(
                ["pw-cli", "info", "0"], capture_output=True, text=True
            )
            if result.returncode != 0:
                raise Exception("PipeWire is not running")

            # Initialize device tracking
            self.devices = {}
            self._init_audio()
            logger.info("Audio manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize audio: {e}")
            raise

    def _init_audio(self):
        """Initialize audio devices"""
        try:
            # Get audio sinks from PipeWire
            self.sinks = []
            result = subprocess.run(
                ["pw-cli", "ls", "Node"], capture_output=True, text=True
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "Audio/Sink" in line:
                        # Extract node ID and info
                        node_id = line.split()[1]
                        info = subprocess.run(
                            ["pw-cli", "info", node_id], capture_output=True, text=True
                        )
                        if info.returncode == 0:
                            props = {}
                            for prop_line in info.stdout.splitlines():
                                if ":" in prop_line:
                                    key, value = prop_line.split(":", 1)
                                    props[key.strip()] = value.strip()
                            self.sinks.append(
                                {
                                    "id": node_id,
                                    "props": {
                                        "node.name": props.get("node.name", "Unknown"),
                                        "node.description": props.get(
                                            "node.description", ""
                                        ),
                                        "media.class": "Audio/Sink",
                                        "node.volume": float(
                                            props.get("node.volume", "1.0")
                                        ),
                                        "node.mute": props.get(
                                            "node.mute", "false"
                                        ).lower()
                                        == "true",
                                    },
                                }
                            )

            logger.info(f"Found {len(self.sinks)} audio sinks")

        except Exception as e:
            logger.error(f"Error initializing audio: {e}")

    def get_devices(self) -> List[DeviceState]:
        """Get list of audio devices"""
        try:
            return [
                DeviceState(
                    id=i,
                    name=sink["props"].get(
                        "node.description", sink["props"].get("node.name", "Unknown")
                    ),
                    type=DeviceType.USB
                    if "usb" in sink["props"].get("node.name", "").lower()
                    else DeviceType.BUILTIN,
                    volume=int(float(sink["props"].get("node.volume", 1.0)) * 100),
                    muted=bool(sink["props"].get("node.mute", False)),
                    active=True,
                )
                for i, sink in enumerate(self.sinks)
            ]
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return []

    def set_volume(self, device_id: int, volume: int) -> bool:
        """Set volume for a device"""
        try:
            volume = max(0, min(100, volume))  # Clamp volume between 0 and 100
            if 0 <= device_id < len(self.sinks):
                sink = self.sinks[device_id]
                result = subprocess.run(
                    [
                        "pw-cli",
                        "s",
                        sink["id"],
                        "Props",
                        f'{{"volume": {volume / 100}}}',
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    sink["props"]["node.volume"] = volume / 100
                    logger.info(
                        f"Set volume to {volume}% for device {sink['props'].get('node.name')}"
                    )
                    return True
            return False
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False

    def set_mute(self, device_id: int, muted: bool) -> bool:
        """Set mute state for a device"""
        try:
            if 0 <= device_id < len(self.sinks):
                sink = self.sinks[device_id]
                result = subprocess.run(
                    [
                        "pw-cli",
                        "s",
                        sink["id"],
                        "Props",
                        f'{{"mute": {"true" if muted else "false"}}}',
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    sink["props"]["node.mute"] = muted
                    logger.info(
                        f"{'Muted' if muted else 'Unmuted'} device {sink['props'].get('node.name')}"
                    )
                    return True
            return False
        except Exception as e:
            logger.error(f"Error setting mute: {e}")
            return False

    def get_system_state(self) -> SystemState:
        """Get current system state"""
        return SystemState(devices=self.get_devices())
