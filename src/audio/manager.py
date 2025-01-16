"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import subprocess
from math import log10
from typing import List, Optional, Dict, Set
from loguru import logger

from ..models import DeviceState, SystemState, DeviceType


class AudioManager:
    def __init__(self):
        try:
            # Check if PipeWire is running
            logger.debug("Checking PipeWire status...")

            # First check if pw-cli exists
            which_result = subprocess.run(
                ["which", "pw-cli"], capture_output=True, text=True
            )
            if which_result.returncode != 0:
                raise Exception("pw-cli not found in PATH")
            logger.debug(f"Found pw-cli at: {which_result.stdout.strip()}")

            # Check PipeWire socket
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
            if not os.path.exists(f"{runtime_dir}/pipewire-0"):
                raise Exception(
                    f"PipeWire socket not found at {runtime_dir}/pipewire-0"
                )
            logger.debug(f"Found PipeWire socket at {runtime_dir}/pipewire-0")

            # Force PipeWire to load ALSA nodes
            logger.debug("Forcing PipeWire to load ALSA nodes...")
            subprocess.run(["systemctl", "--user", "restart", "pipewire-pulse"])
            subprocess.run(["sleep", "2"])

            # Try to get nodes with timeout and retries
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    logger.debug(f"Attempt {retry_count + 1} to get PipeWire nodes")
                    result = subprocess.run(
                        ["pw-dump"], capture_output=True, text=True, timeout=5
                    )
                    logger.debug(f"pw-dump return code: {result.returncode}")

                    if result.returncode == 0:
                        try:
                            nodes = json.loads(result.stdout)
                            audio_nodes = [
                                n
                                for n in nodes
                                if n.get("info", {})
                                .get("props", {})
                                .get("media.class", "")
                                .startswith("Audio/")
                            ]
                            if audio_nodes:
                                logger.info(f"Found {len(audio_nodes)} audio nodes")
                                break
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse pw-dump output")

                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(
                            f"No audio nodes found, retrying in 2 seconds..."
                        )
                        subprocess.run(["sleep", "2"])
                except subprocess.TimeoutExpired:
                    logger.warning("pw-dump command timed out")
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"Retrying in 2 seconds...")
                        subprocess.run(["sleep", "2"])

            if retry_count == max_retries:
                raise Exception(
                    "Failed to find any PipeWire audio nodes after multiple attempts"
                )

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
        """Set driver/hardware volume with compensation for multiple sinks"""
        try:
            # Get device info first
            info = subprocess.run(
                ["pw-cli", "info", node_id],
                capture_output=True,
                text=True,
            )

            if info.returncode != 0:
                logger.error(f"Failed to get info for device {node_id}")
                return

            # Calculate compensation factor based on number of active sinks
            active_sinks = len([s for s in self.sinks if s["props"]["node.volume"] > 0])
            # If this is the first sink, count it
            compensation = (
                1.0 if active_sinks == 0 else (2.0 ** ((active_sinks - 1) / 2))
            )
            # Convert to dB: 2.0 = ~6dB boost, sqrt(2.0) = ~3dB boost per additional sink

            logger.info(
                f"Using compensation factor of {compensation:.2f}x for {active_sinks} active sinks"
            )

            # Set up default configuration
            buffer_config = {
                "audio.rate": 48000,
                "audio.allowed-rates": [48000],
                "node.latency": "1024/48000",
                "audio.position": ["FL", "FR"],
                "node.pause-on-idle": False,
                "api.alsa.period-size": 1024,
                "api.alsa.headroom": 8192,
            }

            # Apply buffer configuration
            subprocess.run(
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

            # Set volume with compensation (base 1.122 * compensation)
            compensated_volume = min(
                1.122 * compensation, 2.0
            )  # Cap at +6dB to prevent distortion
            subprocess.run(
                [
                    "pw-cli",
                    "s",
                    node_id,
                    "Props",
                    f'{{"channelVolumes": [{compensated_volume}, {compensated_volume}]}}',
                ],
                capture_output=True,
                text=True,
            )

            logger.info(
                f"Set compensated driver volume to {20 * log10(compensated_volume):.1f} dB for device {node_id}"
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
                    self.routing[source_name] = {
                        sink["props"]["node.name"] for sink in self.sinks
                    }
            else:
                # Ensure all sources are routed to all sinks
                for source in current_sources:
                    source_name = source["name"]
                    if source_name not in self.routing:
                        self.routing[source_name] = set()
                    # Add all sinks to the routing
                    self.routing[source_name].update(
                        {sink["props"]["node.name"] for sink in self.sinks}
                    )

            # Create links for each source to all sinks
            for source in current_sources:
                source_name = source["name"]
                # Link to all sinks
                for sink in self.sinks:
                    try:
                        # Create link with explicit buffer settings
                        subprocess.run(
                            [
                                "pw-link",
                                source["id"],
                                sink["id"],
                            ],
                            capture_output=True,
                            text=True,
                        )
                        logger.info(
                            f"Created link from {source['description']} to {sink['props']['node.description']}"
                        )
                    except Exception as e:
                        logger.error(f"Error creating link: {e}")

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

            # First check what ALSA sees
            logger.debug("Checking ALSA devices...")
            alsa_result = subprocess.run(
                ["aplay", "-l"], capture_output=True, text=True
            )
            if alsa_result.returncode == 0:
                logger.debug("ALSA devices found:")
                logger.debug(alsa_result.stdout)

            # Now check PipeWire nodes
            logger.debug("Checking PipeWire nodes...")
            result = subprocess.run(
                ["pw-cli", "ls", "Node"], capture_output=True, text=True
            )

            if result.returncode == 0:
                logger.debug("Raw pw-cli output:")
                logger.debug(result.stdout)

                if not result.stdout.strip():
                    logger.warning(
                        "No PipeWire nodes found - waiting for devices to be registered"
                    )
                    # Try running pw-cli info all to see what PipeWire knows about
                    info_result = subprocess.run(
                        ["pw-cli", "info", "all"], capture_output=True, text=True
                    )
                    logger.debug("PipeWire info all output:")
                    logger.debug(info_result.stdout)

                    # Force PipeWire to rescan ALSA devices
                    logger.info("Forcing PipeWire to rescan ALSA devices...")
                    subprocess.run(["systemctl", "--user", "restart", "pipewire-pulse"])
                    subprocess.run(["sleep", "2"])

                    # Try listing nodes again
                    result = subprocess.run(
                        ["pw-cli", "ls", "Node"], capture_output=True, text=True
                    )
                    logger.debug("PipeWire nodes after rescan:")
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

            # Configure global PipeWire settings for better sync
            subprocess.run(
                [
                    "pw-metadata",
                    "-n",
                    "settings",
                    "0",
                    "clock.force-rate",
                    "48000",
                ],
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "pw-metadata",
                    "-n",
                    "settings",
                    "0",
                    "clock.force-quantum",
                    "1024",
                ],
                capture_output=True,
                text=True,
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

            # Clear existing links before refresh
            subprocess.run(["pw-link", "-d", "all"], capture_output=True, text=True)

            # Wait a moment for PipeWire to settle
            subprocess.run(["sleep", "0.5"], capture_output=True)

            # Reinitialize devices
            self._init_audio()

            # Restore states for existing devices
            for sink in self.sinks:
                node_name = sink["props"]["node.name"]
                if node_name in current_states:
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
                        self.device_states[node_name] = {
                            "volume": volume,
                            "muted": False,
                        }
                    except Exception as e:
                        logger.error(f"Error restoring volume for {node_name}: {e}")
                else:
                    # New device - set safe initial volume
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

            # Re-establish audio routing
            self._ensure_audio_routing()

        except Exception as e:
            logger.error(f"Error refreshing devices: {e}")

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

                    # Update driver volumes for all sinks to maintain proper compensation
                    for sink in self.sinks:
                        self._set_driver_volume(sink["id"])

                    # Ensure audio routing is correct
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
