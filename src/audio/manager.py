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

    def _set_driver_volume(self, node_id: str):
        """Set driver/hardware volume to 0 dB for best signal quality"""
        try:
            # First get the current channel map to know how many channels to set
            info = subprocess.run(
                ["pw-cli", "info", node_id],
                capture_output=True,
                text=True,
            )

            if info.returncode == 0:
                # Look for audio.channels in the output
                channels = 2  # Default to stereo
                for line in info.stdout.splitlines():
                    if "audio.channels" in line and ":" in line:
                        try:
                            channels = int(line.split(":", 1)[1].strip())
                            break
                        except (ValueError, IndexError):
                            pass

                # Set each channel's volume to 0 dB (1.0 in linear scale)
                volumes = ",".join(["1.0"] * channels)
                subprocess.run(
                    [
                        "pw-cli",
                        "s",
                        node_id,
                        "Props",
                        f'{{"channelVolumes": [{volumes}]}}',
                    ],
                    capture_output=True,
                    text=True,
                )
                logger.info(f"Set driver volume to 0 dB for device {node_id}")
        except Exception as e:
            logger.error(f"Error setting driver volume: {e}")

    def _ensure_audio_routing(self):
        """Ensure audio sources are routed to all sinks"""
        try:
            # Get all audio sources (like Bluetooth input)
            result = subprocess.run(
                ["pw-cli", "ls", "Node"], capture_output=True, text=True
            )
            if result.returncode == 0:
                lines = result.stdout.splitlines()
                current_node_id = None
                for i, line in enumerate(lines):
                    line = line.strip()

                    # Look for node ID
                    if line.startswith("id"):
                        try:
                            current_node_id = line.split()[1].rstrip(",")
                        except Exception:
                            current_node_id = None
                            continue

                    # Look for audio sources
                    elif current_node_id and "media.class = " in line:
                        media_class = line.split("=")[1].strip().strip('"')
                        if (
                            "Audio/Source" in media_class
                            or "Stream/Output/Audio" in media_class
                        ):
                            logger.info(f"Found audio source: {current_node_id}")
                            # Link this source to all sinks
                            for sink in self.sinks:
                                try:
                                    # Create link from source to sink
                                    subprocess.run(
                                        ["pw-link", current_node_id, sink["id"]],
                                        capture_output=True,
                                        text=True,
                                    )
                                    logger.info(
                                        f"Linked source {current_node_id} to sink {sink['id']}"
                                    )
                                except Exception as e:
                                    logger.error(f"Error linking source to sink: {e}")
        except Exception as e:
            logger.error(f"Error ensuring audio routing: {e}")

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

                        # Only process Audio/Sink nodes (output devices)
                        if "Audio/Sink" in media_class:
                            try:
                                logger.debug(f"Processing audio sink {current_node_id}")

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
                                        f"Found sink device: {node_desc} ({node_name})"
                                    )

                                    # Set driver volume to 0 dB
                                    self._set_driver_volume(current_node_id)

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

                            except Exception as e:
                                logger.error(f"Error processing node: {e}")
                                continue

            logger.info(f"Found {len(self.sinks)} audio sinks")
            for sink in self.sinks:
                logger.info(
                    f"  - {sink['props']['node.description']} ({sink['props']['node.name']})"
                )

            # Ensure audio routing is set up
            self._ensure_audio_routing()

        except Exception as e:
            logger.error(f"Error initializing audio: {e}")

    def refresh_devices(self):
        """Refresh the list of audio devices while maintaining states"""
        try:
            # Store current states
            current_states = self.device_states.copy()
            current_sinks = {sink["props"]["node.name"]: sink for sink in self.sinks}

            # Reinitialize devices
            self._init_audio()

            # Restore states for existing devices
            for sink in self.sinks:
                node_name = sink["props"]["node.name"]
                if node_name in current_states:
                    # Set driver volume to 0 dB first
                    self._set_driver_volume(sink["id"])

                    # Restore volume
                    try:
                        volume = current_states[node_name]["volume"]
                        subprocess.run(
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
                        sink["props"]["node.volume"] = volume / 100
                    except Exception as e:
                        logger.error(f"Error restoring volume for {node_name}: {e}")

                    # Restore mute state
                    try:
                        muted = current_states[node_name]["muted"]
                        subprocess.run(
                            [
                                "pw-cli",
                                "s",
                                sink["id"],
                                "Props",
                                f'{{"mute": {str(muted).lower()}}}',
                            ],
                            capture_output=True,
                            text=True,
                        )
                        sink["props"]["node.mute"] = muted
                    except Exception as e:
                        logger.error(f"Error restoring mute state for {node_name}: {e}")
                else:
                    # New device - set driver volume to 0 dB first
                    self._set_driver_volume(sink["id"])

                    # Then set safe initial volume
                    try:
                        subprocess.run(
                            ["pw-cli", "s", sink["id"], "Props", '{"volume": 0.05}'],
                            capture_output=True,
                            text=True,
                        )
                        sink["props"]["node.volume"] = 0.05
                        self.device_states[node_name] = {"volume": 5, "muted": False}
                    except Exception as e:
                        logger.error(
                            f"Error setting initial volume for {node_name}: {e}"
                        )

                    # Ensure device is linked (active)
                    try:
                        subprocess.run(
                            ["pw-cli", "l", sink["id"]],
                            capture_output=True,
                            text=True,
                        )
                    except Exception as e:
                        logger.error(f"Error linking device {node_name}: {e}")

        except Exception as e:
            logger.error(f"Error refreshing devices: {e}")
            # Restore original states on error
            self.sinks = [sink for sink in current_sinks.values()]
            self.device_states = current_states

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

            devices = []
            for i, sink in enumerate(self.sinks):
                # Get current volume from PipeWire for accurate reporting
                try:
                    info = subprocess.run(
                        ["pw-cli", "info", sink["id"]],
                        capture_output=True,
                        text=True,
                    )
                    if info.returncode == 0:
                        for line in info.stdout.splitlines():
                            if "volume" in line and ":" in line:
                                try:
                                    volume = float(line.split(":", 1)[1].strip())
                                    sink["props"]["node.volume"] = volume
                                except (ValueError, IndexError):
                                    pass
                except Exception as e:
                    logger.error(f"Error getting device volume: {e}")

                devices.append(
                    DeviceState(
                        id=i,
                        name=sink["props"].get(
                            "node.description",
                            sink["props"].get("node.name", "Unknown"),
                        ),
                        type=self._determine_device_type(sink["props"]),
                        volume=int(float(sink["props"].get("node.volume", 1.0)) * 100),
                        muted=bool(sink["props"].get("node.mute", False)),
                        active=True,  # All devices are always active
                    )
                )

            logger.debug(f"Returning {len(devices)} devices: {devices}")
            return devices
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return []

    def _determine_device_type(self, props: dict) -> str:
        """Determine device type from properties"""
        try:
            # Check for USB devices
            if "alsa" in props.get("device.api", "").lower():
                if (
                    "usb" in props.get("node.description", "").lower()
                    or "usb" in props.get("factory.name", "").lower()
                ):
                    return DeviceType.USB

            # Check for Bluetooth devices
            if (
                "bluetooth" in props.get("device.api", "").lower()
                or "bluez" in props.get("factory.name", "").lower()
            ):
                return DeviceType.BLUETOOTH

            # Default to built-in
            return DeviceType.BUILTIN
        except Exception as e:
            logger.error(f"Error determining device type: {e}")
            return DeviceType.BUILTIN

    def set_volume(self, device_id: int, volume: int) -> bool:
        """Set volume for a device"""
        try:
            volume = max(0, min(100, volume))  # Clamp volume between 0 and 100
            if 0 <= device_id < len(self.sinks):
                sink = self.sinks[device_id]

                # Set volume for the sink
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

                # Set mute state for the sink
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
