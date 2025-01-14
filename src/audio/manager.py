"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import subprocess
from typing import List, Optional, Dict
from loguru import logger

from ..models import DeviceState, SystemState, DeviceType


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
            self.device_states = {}  # Track volume/mute states per device
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
                logger.debug("Raw pw-cli output:")
                logger.debug(result.stdout)

                lines = result.stdout.splitlines()
                current_node_id = None
                for i, line in enumerate(lines):
                    line = line.strip()

                    # Look for node ID at the start of an object
                    if line.startswith("id"):
                        try:
                            current_node_id = line.split()[1].rstrip(",")
                            logger.debug(f"Found potential node ID: {current_node_id}")
                        except Exception:
                            current_node_id = None
                            continue

                    # Look for media class in subsequent lines
                    elif current_node_id and "media.class = " in line:
                        media_class = line.split("=")[1].strip().strip('"')
                        logger.debug(
                            f"Found media class: {media_class} for node {current_node_id}"
                        )

                        if any(
                            cls in media_class
                            for cls in [
                                "Audio/Sink",
                                "Stream/Output/Audio",
                                "Audio/Source",
                            ]
                        ):
                            try:
                                logger.debug(f"Processing audio node {current_node_id}")

                                # Get detailed info about the node
                                info = subprocess.run(
                                    ["pw-cli", "info", current_node_id],
                                    capture_output=True,
                                    text=True,
                                )

                                logger.debug(f"Node {current_node_id} info output:")
                                logger.debug(info.stdout)

                                if info.returncode == 0:
                                    props = {}
                                    current_key = None
                                    for prop_line in info.stdout.splitlines():
                                        if prop_line.startswith("*"):
                                            # Handle multi-line properties
                                            if ":" in prop_line:
                                                current_key = (
                                                    prop_line.split(":", 1)[0]
                                                    .strip()
                                                    .strip("*")
                                                )
                                                value = prop_line.split(":", 1)[
                                                    1
                                                ].strip()
                                                props[current_key] = value
                                            elif current_key:
                                                # Append to previous value
                                                props[current_key] += (
                                                    " " + prop_line.strip()
                                                )

                                    logger.debug(
                                        f"Parsed properties for node {current_node_id}:"
                                    )
                                    logger.debug(props)

                                    # Use node.name as unique identifier
                                    node_name = props.get(
                                        "node.name", f"device_{current_node_id}"
                                    )
                                    node_desc = props.get("node.description", node_name)
                                    logger.info(
                                        f"Found device: {node_desc} ({node_name})"
                                    )

                                    # Restore previous state or use safe defaults
                                    if node_name in self.device_states:
                                        saved_state = self.device_states[node_name]
                                        volume = saved_state.get("volume", 5)
                                        muted = saved_state.get("muted", False)
                                    else:
                                        volume = 5
                                        muted = False

                                    sink_info = {
                                        "id": current_node_id,
                                        "props": {
                                            "node.name": node_name,
                                            "node.description": node_desc,
                                            "media.class": media_class,
                                            "node.volume": volume / 100,
                                            "node.mute": muted,
                                            "device.api": props.get("device.api", ""),
                                            "factory.name": props.get(
                                                "factory.name", ""
                                            ),
                                            "object.path": props.get("object.path", ""),
                                        },
                                    }

                                    self.sinks.append(sink_info)
                                    logger.info(f"Added sink: {sink_info}")

                                    # Save state for future reference
                                    self.device_states[node_name] = {
                                        "volume": volume,
                                        "muted": muted,
                                    }

                                    # Set initial volume for new devices
                                    if node_name not in self.device_states:
                                        subprocess.run(
                                            [
                                                "pw-cli",
                                                "s",
                                                current_node_id,
                                                "Props",
                                                f'{{"volume": {volume / 100}}}',
                                            ],
                                            capture_output=True,
                                            text=True,
                                        )

                                    # Ensure the device is linked (active)
                                    subprocess.run(
                                        ["pw-cli", "l", current_node_id],
                                        capture_output=True,
                                        text=True,
                                    )
                            except Exception as e:
                                logger.error(f"Error processing node: {e}")
                                continue

            logger.info(f"Found {len(self.sinks)} audio sinks")
            for sink in self.sinks:
                logger.info(
                    f"  - {sink['props']['node.description']} ({sink['props']['node.name']})"
                )

        except Exception as e:
            logger.error(f"Error initializing audio: {e}")

    def refresh_devices(self):
        """Refresh the list of audio devices while maintaining states"""
        current_states = self.device_states.copy()
        self._init_audio()
        # Restore any previously saved states
        for sink in self.sinks:
            node_name = sink["props"]["node.name"]
            if node_name in current_states:
                self.set_volume(
                    self._get_device_id_by_name(node_name),
                    current_states[node_name]["volume"],
                )
                if current_states[node_name]["muted"]:
                    self.set_mute(self._get_device_id_by_name(node_name), True)

    def _get_device_id_by_name(self, node_name: str) -> Optional[int]:
        """Get device ID by node name"""
        for i, sink in enumerate(self.sinks):
            if sink["props"]["node.name"] == node_name:
                return i
        return None

    def get_devices(self) -> List[DeviceState]:
        """Get list of audio devices"""
        try:
            # Refresh devices to catch any changes
            self.refresh_devices()

            devices = [
                DeviceState(
                    id=i,
                    name=sink["props"].get(
                        "node.description", sink["props"].get("node.name", "Unknown")
                    ),
                    type=self._determine_device_type(sink["props"]),
                    volume=int(float(sink["props"].get("node.volume", 1.0)) * 100),
                    muted=bool(sink["props"].get("node.mute", False)),
                    active=True,  # All devices are always active
                )
                for i, sink in enumerate(self.sinks)
            ]
            logger.debug(f"Returning {len(devices)} devices: {devices}")
            return devices
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return []

    def _determine_device_type(self, props: dict) -> DeviceType:
        """Determine the type of audio device based on its properties"""
        if props.get("device.api") == "bluez5" or "bluez" in props.get(
            "factory.name", ""
        ):
            return DeviceType.BLUETOOTH
        elif "usb" in props.get("object.path", "").lower():
            return DeviceType.USB
        elif "alsa" in props.get("factory.name", "").lower():
            return DeviceType.BUILTIN
        else:
            return DeviceType.BUILTIN

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
                    # Save state
                    node_name = sink["props"]["node.name"]
                    if node_name in self.device_states:
                        self.device_states[node_name]["volume"] = volume
                    else:
                        self.device_states[node_name] = {
                            "volume": volume,
                            "muted": False,
                        }
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
                    # Save state
                    node_name = sink["props"]["node.name"]
                    if node_name in self.device_states:
                        self.device_states[node_name]["muted"] = muted
                    else:
                        self.device_states[node_name] = {"volume": 100, "muted": muted}
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
