"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import subprocess
from typing import List, Optional, Dict, Set
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
            self.sources = {}  # Track audio sources
            self.routing = {}  # Track source -> sink mappings
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
                is_pro_audio = False
                device_name = ""

                for line in info.stdout.splitlines():
                    if "audio.channels" in line and ":" in line:
                        try:
                            channels = int(line.split(":", 1)[1].strip())
                        except (ValueError, IndexError):
                            pass
                    # Check if it's a professional audio device
                    elif "node.name" in line:
                        device_name = line.split(":", 1)[1].strip().lower()
                        if any(
                            x in device_name
                            for x in ["thump", "mackie", "pro", "yamaha", "alsa"]
                        ):
                            is_pro_audio = True
                    elif "api.alsa" in line or "device.api" in line:
                        is_pro_audio = True

                # Set each channel's volume to 0 dB (1.0 in linear scale)
                volumes = ",".join(["1.0"] * channels)

                # Configure buffers based on device type
                if is_pro_audio:
                    buffer_config = {
                        "audio.rate": 48000,
                        "audio.allowed-rates": [48000],
                        "node.latency": "1024/48000",  # Increased latency for stability
                        "audio.position": ["FL", "FR"],
                        "node.pause-on-idle": False,
                        "api.alsa.period-size": 2048,  # Larger period size
                        "api.alsa.headroom": 16384,  # More headroom
                        "api.alsa.disable-mmap": True,  # Disable mmap for compatibility
                        "session.suspend-timeout-seconds": 0,  # Prevent suspend
                    }
                else:
                    buffer_config = {
                        "audio.rate": 48000,
                        "audio.allowed-rates": [48000],
                        "node.latency": "256/48000",
                        "audio.position": ["FL", "FR"],
                        "node.pause-on-idle": False,
                        "api.alsa.period-size": 256,
                        "api.alsa.headroom": 4096,
                    }

                # Apply buffer configuration
                result = subprocess.run(
                    [
                        "pw-cli",
                        "s",
                        node_id,
                        "Props",
                        json.dumps(buffer_config),
                    ],
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    logger.warning(
                        f"Failed to set buffer config for device {node_id}: {result.stderr}"
                    )
                    # Try with minimal config if full config fails
                    minimal_config = {
                        "audio.rate": 48000,
                        "node.latency": "1024/48000" if is_pro_audio else "256/48000",
                    }
                    subprocess.run(
                        [
                            "pw-cli",
                            "s",
                            node_id,
                            "Props",
                            json.dumps(minimal_config),
                        ],
                        capture_output=True,
                        text=True,
                    )

                # Set volume after buffer config
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
                logger.info(
                    f"Set driver volume to 0 dB and configured {'pro-audio' if is_pro_audio else 'standard'} buffers for device {node_id}"
                )
        except Exception as e:
            logger.error(f"Error setting driver volume: {e}")

    def _find_sources(self) -> List[Dict]:
        """Find all audio sources"""
        sources = []
        try:
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
                            # Get detailed info about the source
                            info = subprocess.run(
                                ["pw-cli", "info", current_node_id],
                                capture_output=True,
                                text=True,
                            )
                            if info.returncode == 0:
                                props = {}
                                for prop_line in info.stdout.splitlines():
                                    if prop_line.startswith("*") and ":" in prop_line:
                                        key = (
                                            prop_line.split(":", 1)[0]
                                            .strip()
                                            .strip("*")
                                        )
                                        value = prop_line.split(":", 1)[1].strip()
                                        props[key] = value

                                # Use node.name as unique identifier
                                node_name = props.get(
                                    "node.name", f"source_{current_node_id}"
                                )
                                node_desc = props.get("node.description", node_name)

                                source_info = {
                                    "id": current_node_id,
                                    "name": node_name,
                                    "description": node_desc,
                                    "media_class": media_class,
                                }
                                sources.append(source_info)
                                logger.info(
                                    f"Found audio source: {node_desc} ({node_name})"
                                )

        except Exception as e:
            logger.error(f"Error finding sources: {e}")

        return sources

    def _ensure_audio_routing(self):
        """Ensure audio sources are routed according to saved mappings"""
        try:
            # Find current sources
            current_sources = self._find_sources()
            self.sources = {s["name"]: s for s in current_sources}

            # Initialize routing if empty
            if not self.routing:
                # Default to routing all sources to all sinks
                for source in current_sources:
                    source_name = source["name"]
                    if source_name not in self.routing:
                        self.routing[source_name] = set()
                    self.routing[source_name].update(
                        {sink["props"]["node.name"] for sink in self.sinks}
                    )

            # Apply routing
            for source in current_sources:
                source_name = source["name"]
                if source_name in self.routing:
                    # Get target sinks for this source
                    target_sinks = self.routing[source_name]

                    # Link to each target sink
                    for sink in self.sinks:
                        sink_name = sink["props"]["node.name"]
                        try:
                            if sink_name in target_sinks:
                                # Create link
                                subprocess.run(
                                    ["pw-link", source["id"], sink["id"]],
                                    capture_output=True,
                                    text=True,
                                )
                                logger.info(
                                    f"Linked source {source['description']} to sink {sink['props']['node.description']}"
                                )
                            else:
                                # Remove link if it exists
                                subprocess.run(
                                    ["pw-link", "-d", source["id"], sink["id"]],
                                    capture_output=True,
                                    text=True,
                                )
                                logger.info(
                                    f"Unlinked source {source['description']} from sink {sink['props']['node.description']}"
                                )
                        except Exception as e:
                            logger.error(f"Error managing link: {e}")

        except Exception as e:
            logger.error(f"Error ensuring audio routing: {e}")

    def _create_combined_sink(self):
        """Create a combined sink for synchronized playback"""
        try:
            # First, unload any existing combined module
            subprocess.run(
                [
                    "pw-cli",
                    "destroy",
                    "all",
                    "PipeWire:Interface:Module",
                    "libpipewire-module-combine-stream",
                ],
                capture_output=True,
                text=True,
            )

            # Get the sink IDs
            sink_ids = [sink["id"] for sink in self.sinks]
            if len(sink_ids) < 2:
                return

            # Create a combined sink
            sink_list = ",".join(sink_ids)
            subprocess.run(
                [
                    "pw-cli",
                    "create-module",
                    "libpipewire-module-combine-stream",
                    f'{{"combine.mode": "sink", "combine.props": {{"audio.position": ["FL", "FR"]}}, "stream.props": {{"audio.rate": 48000, "node.latency": "1024/48000", "node.pause-on-idle": false}}, "stream.rules": [{{"matches": [{{"node.name": "~.*"}}], "actions": {{"create-stream": {{"audio.rate": 48000, "node.latency": "1024/48000", "node.pause-on-idle": false}}}}}}], "capture.props": {{"audio.rate": 48000, "node.latency": "1024/48000", "node.pause-on-idle": false}}, "sink.ids": [{sink_list}]}}',
                ],
                capture_output=True,
                text=True,
            )
            logger.info("Created combined sink for synchronized playback")
        except Exception as e:
            logger.error(f"Error creating combined sink: {e}")

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

            # Create combined sink for synchronized playback
            self._create_combined_sink()

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
            self._init_audio()  # This will also recreate the combined sink

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
            if not 0 <= volume <= 100:
                raise ValueError("Volume must be between 0 and 100")

            if 0 <= device_id < len(self.sinks):
                sink = self.sinks[device_id]

                # Set volume for the target device
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
                    logger.info(f"Set volume to {volume}% for device {node_name}")

                    # Ensure audio routing is correct for sync
                    self._ensure_audio_routing()
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

    def get_sources(self) -> List[Dict]:
        """Get list of available audio sources"""
        sources = self._find_sources()
        return [
            {
                "id": i,
                "name": source["name"],
                "description": source["description"],
                "outputs": list(self.routing.get(source["name"], set())),
            }
            for i, source in enumerate(sources)
        ]

    def set_source_routing(self, source_id: int, sink_names: List[str]) -> bool:
        """Set which sinks a source should output to"""
        try:
            sources = self._find_sources()
            if 0 <= source_id < len(sources):
                source = sources[source_id]
                # Update routing
                self.routing[source["name"]] = set(sink_names)
                # Apply new routing
                self._ensure_audio_routing()
                return True
            return False
        except Exception as e:
            logger.error(f"Error setting source routing: {e}")
            return False
