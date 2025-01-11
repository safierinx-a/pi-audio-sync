import os
import asyncio
import json
from typing import Dict, List, Optional
import pulsectl
import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from loguru import logger

from .device import AudioDevice, DeviceType
from ..api.models import AudioSource


class AudioManager:
    """Manages PulseAudio devices and Bluetooth sources"""

    def __init__(self):
        # Initialize PulseAudio
        self.pulse = pulsectl.Pulse("pi-audio-sync")
        self.devices: Dict[str, AudioDevice] = {}
        self.combined_sink: Optional[int] = None

        # Initialize DBus for Bluetooth
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.mainloop = GLib.MainLoop()

        # Bluetooth objects
        self.adapter = None
        self.sources: Dict[str, AudioSource] = {}
        self.current_source: Optional[AudioSource] = None
        self._init_bluetooth()

        # Load device names from environment
        self.builtin_name = os.getenv("BUILTIN_DEVICE_NAME", "Built-in Audio")
        self.usb_name = os.getenv("USB_DEVICE_NAME", "USB Audio")

        # Initialize devices
        self._setup_devices()

        # Load trusted sources
        self._load_trusted_sources()

    def _init_bluetooth(self):
        """Initialize Bluetooth adapter"""
        try:
            adapter_obj = self.bus.get_object("org.bluez", "/org/bluez/hci0")
            self.adapter = dbus.Interface(adapter_obj, "org.bluez.Adapter1")
            self.adapter_props = dbus.Interface(
                adapter_obj, "org.freedesktop.DBus.Properties"
            )

            # Set discoverable and pairable
            self.adapter_props.Set("org.bluez.Adapter1", "Discoverable", True)
            self.adapter_props.Set("org.bluez.Adapter1", "Pairable", True)
            self.adapter_props.Set(
                "org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0)
            )  # Always discoverable

            # Set friendly name
            self.adapter_props.Set("org.bluez.Adapter1", "Alias", "Pi Audio Sync")

            # Register agent for pairing
            self._register_agent()

            logger.info("Bluetooth adapter initialized and discoverable")
        except Exception as e:
            logger.error(f"Failed to initialize Bluetooth: {e}")
            raise

    def _register_agent(self):
        """Register authentication agent for pairing requests"""
        try:
            # Get agent manager
            agent_manager = dbus.Interface(
                self.bus.get_object("org.bluez", "/org/bluez"),
                "org.bluez.AgentManager1",
            )

            # Register our custom agent
            agent_path = "/org/bluez/agent"
            agent_manager.RegisterAgent(agent_path, "NoInputNoOutput")
            agent_manager.RequestDefaultAgent(agent_path)

            logger.info("Bluetooth agent registered")
        except Exception as e:
            logger.error(f"Failed to register Bluetooth agent: {e}")

    async def handle_incoming_connection(self, device_path: str):
        """Handle incoming Bluetooth connection"""
        try:
            device = self.bus.get_object("org.bluez", device_path)
            props = dbus.Interface(device, "org.freedesktop.DBus.Properties")

            # Get device info
            mac_address = str(props.Get("org.bluez.Device1", "Address"))
            name = str(props.Get("org.bluez.Device1", "Name"))

            # Create or update source
            if mac_address not in self.sources:
                self.sources[mac_address] = AudioSource(
                    name=name, mac_address=mac_address, connected=True
                )
            else:
                self.sources[mac_address].connected = True

            self.current_source = self.sources[mac_address]
            logger.info(f"Accepted connection from {name} ({mac_address})")

            # Route audio to combined sink
            if self.combined_sink is not None:
                # TODO: Set up audio routing for the new connection
                pass

        except Exception as e:
            logger.error(f"Failed to handle incoming connection: {e}")

    def make_discoverable(self, timeout: int = 0):
        """Make the Pi discoverable to other devices"""
        try:
            self.adapter_props.Set("org.bluez.Adapter1", "Discoverable", True)
            self.adapter_props.Set(
                "org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(timeout)
            )
            logger.info(
                f"Made discoverable{' indefinitely' if timeout == 0 else f' for {timeout} seconds'}"
            )
        except Exception as e:
            logger.error(f"Failed to make discoverable: {e}")

    def stop_discoverable(self):
        """Stop being discoverable"""
        try:
            self.adapter_props.Set("org.bluez.Adapter1", "Discoverable", False)
            logger.info("Stopped being discoverable")
        except Exception as e:
            logger.error(f"Failed to stop being discoverable: {e}")

    def _load_trusted_sources(self):
        """Load trusted sources from storage"""
        try:
            if os.path.exists("/opt/pi-audio-sync/data/trusted_sources.json"):
                with open("/opt/pi-audio-sync/data/trusted_sources.json", "r") as f:
                    trusted = json.load(f)
                    for source in trusted:
                        self.sources[source["mac_address"]] = AudioSource(**source)
                logger.info(f"Loaded {len(trusted)} trusted sources")
        except Exception as e:
            logger.error(f"Failed to load trusted sources: {e}")

    def _save_trusted_sources(self):
        """Save trusted sources to storage"""
        try:
            trusted = [s.dict() for s in self.sources.values() if s.trusted]
            os.makedirs("/opt/pi-audio-sync/data", exist_ok=True)
            with open("/opt/pi-audio-sync/data/trusted_sources.json", "w") as f:
                json.dump(trusted, f)
            logger.info(f"Saved {len(trusted)} trusted sources")
        except Exception as e:
            logger.error(f"Failed to save trusted sources: {e}")

    async def start_source_scan(self):
        """Start scanning for Bluetooth audio sources"""
        try:
            # Start discovery
            self.adapter.StartDiscovery()

            # Scan for 30 seconds
            await asyncio.sleep(30)

            # Stop discovery
            self.adapter.StopDiscovery()

            logger.info("Completed Bluetooth scan")
        except Exception as e:
            logger.error(f"Failed to scan for sources: {e}")
            try:
                self.adapter.StopDiscovery()
            except:
                pass

    async def get_sources(self) -> List[AudioSource]:
        """Get list of available audio sources"""
        try:
            # Get all Bluetooth devices
            objects = self.bus.get_object("org.bluez", "/").GetManagedObjects()

            for path, interfaces in objects.items():
                if "org.bluez.Device1" not in interfaces:
                    continue

                props = interfaces["org.bluez.Device1"]

                # Only include audio devices
                if "Audio" not in props.get(
                    "Class", 0
                ) and "AudioSource" not in props.get("UUIDs", []):
                    continue

                mac = props["Address"]
                name = props.get("Name", "Unknown Device")
                connected = props.get("Connected", False)

                if mac not in self.sources:
                    self.sources[mac] = AudioSource(
                        name=name, mac_address=mac, connected=connected
                    )
                else:
                    self.sources[mac].connected = connected

            return list(self.sources.values())
        except Exception as e:
            logger.error(f"Failed to get sources: {e}")
            return list(self.sources.values())

    async def connect_source(self, mac_address: str, trust: bool = False) -> bool:
        """Connect to an audio source"""
        try:
            # Get device object
            path = f"/org/bluez/hci0/dev_{mac_address.replace(':', '_')}"
            device = self.bus.get_object("org.bluez", path)
            dev_iface = dbus.Interface(device, "org.bluez.Device1")

            # Trust if requested
            if trust:
                await self.trust_source(mac_address)

            # Connect
            dev_iface.Connect()

            # Update source state
            if mac_address in self.sources:
                self.sources[mac_address].connected = True
                self.current_source = self.sources[mac_address]

            logger.info(f"Connected to source: {mac_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to source: {e}")
            return False

    async def disconnect_source(self, mac_address: str) -> bool:
        """Disconnect from an audio source"""
        try:
            # Get device object
            path = f"/org/bluez/hci0/dev_{mac_address.replace(':', '_')}"
            device = self.bus.get_object("org.bluez", path)
            dev_iface = dbus.Interface(device, "org.bluez.Device1")

            # Disconnect
            dev_iface.Disconnect()

            # Update source state
            if mac_address in self.sources:
                self.sources[mac_address].connected = False
                if (
                    self.current_source
                    and self.current_source.mac_address == mac_address
                ):
                    self.current_source = None

            logger.info(f"Disconnected from source: {mac_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect from source: {e}")
            return False

    async def trust_source(self, mac_address: str) -> bool:
        """Trust an audio source"""
        try:
            # Get device object
            path = f"/org/bluez/hci0/dev_{mac_address.replace(':', '_')}"
            device = self.bus.get_object("org.bluez", path)
            props = dbus.Interface(device, "org.freedesktop.DBus.Properties")

            # Set trusted
            props.Set("org.bluez.Device1", "Trusted", True)

            # Update source state
            if mac_address in self.sources:
                self.sources[mac_address].trusted = True
                self._save_trusted_sources()

            logger.info(f"Trusted source: {mac_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to trust source: {e}")
            return False

    async def get_current_source(self) -> Optional[AudioSource]:
        """Get currently connected source"""
        return self.current_source

    def _setup_devices(self):
        """Initialize audio devices and create combined sink"""
        try:
            # Create our device objects
            self.devices = {
                "builtin": AudioDevice(
                    name=self.builtin_name,
                    device_type=DeviceType.BUILTIN,
                    pulse_name="alsa_output.platform-bcm2835_audio.analog-stereo",
                ),
                "usb": AudioDevice(
                    name=self.usb_name,
                    device_type=DeviceType.USB,
                    pulse_name="alsa_output.usb-*",  # Wildcard for USB device
                ),
            }

            # Find and update device indices
            self._update_device_indices()

            # Create combined sink if it doesn't exist
            if not self.combined_sink:
                self._create_combined_sink()

            logger.info("Audio devices initialized successfully")
        except Exception as e:
            logger.error(f"Failed to setup audio devices: {e}")
            raise

    def _update_device_indices(self):
        """Update device indices from PulseAudio"""
        try:
            sinks = self.pulse.sink_list()

            # Update built-in device
            builtin = next((s for s in sinks if "bcm2835" in s.name), None)
            if builtin:
                self.devices["builtin"].index = builtin.index
                self.devices["builtin"].volume = int(builtin.volume.value_flat * 100)
                self.devices["builtin"].muted = builtin.mute

            # Update USB device
            usb = next((s for s in sinks if "usb" in s.name.lower()), None)
            if usb:
                self.devices["usb"].index = usb.index
                self.devices["usb"].volume = int(usb.volume.value_flat * 100)
                self.devices["usb"].muted = usb.mute

            logger.debug("Device indices updated")
        except Exception as e:
            logger.error(f"Failed to update device indices: {e}")

    def _create_combined_sink(self):
        """Create a combined sink for synchronized output"""
        try:
            # Get active sink indices
            sink_indices = [
                str(d.index) for d in self.devices.values() if d.index is not None
            ]

            if len(sink_indices) < 2:
                logger.warning("Not enough sinks available for combined output")
                return

            # Create combined sink
            module = self.pulse.module_load(
                "module-combine-sink",
                args={
                    "slaves": ",".join(sink_indices),
                    "adjust_time": 1,
                    "resample_method": "soxr-vhq",
                },
            )

            # Find the new combined sink
            sinks = self.pulse.sink_list()
            combined = next((s for s in sinks if "combined" in s.name.lower()), None)

            if combined:
                self.combined_sink = combined.index
                logger.info("Created combined sink successfully")
            else:
                logger.error("Combined sink not found after creation")

        except Exception as e:
            logger.error(f"Failed to create combined sink: {e}")

    def set_volume(self, device_id: str, volume: int) -> bool:
        """Set volume for a specific device"""
        device = self.devices.get(device_id)
        if not device or device.index is None:
            logger.error(f"Device not found: {device_id}")
            return False

        try:
            # Ensure volume is within bounds
            volume = max(0, min(100, volume))

            # Set volume using PulseAudio
            sink = self.pulse.sink_info(device.index)
            self.pulse.volume_set_all_chans(sink, volume / 100)

            # Update our device object
            device.volume = volume
            logger.info(f"Set volume for {device.name} to {volume}")
            return True
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")
            return False

    def set_mute(self, device_id: str, muted: bool) -> bool:
        """Mute/unmute a specific device"""
        device = self.devices.get(device_id)
        if not device or device.index is None:
            logger.error(f"Device not found: {device_id}")
            return False

        try:
            # Set mute state using PulseAudio
            sink = self.pulse.sink_info(device.index)
            self.pulse.mute(sink, muted)

            # Update our device object
            device.muted = muted
            logger.info(f"{'Muted' if muted else 'Unmuted'} {device.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set mute state: {e}")
            return False

    def get_devices(self) -> List[dict]:
        """Get all devices and their current state"""
        self._update_device_indices()  # Refresh state
        return [device.to_dict() for device in self.devices.values()]

    def get_device(self, device_id: str) -> Optional[dict]:
        """Get a specific device's state"""
        device = self.devices.get(device_id)
        return device.to_dict() if device else None

    def cleanup(self):
        """Cleanup PulseAudio resources"""
        try:
            if self.combined_sink is not None:
                # Find and unload the combine-sink module
                for module in self.pulse.module_list():
                    if "module-combine-sink" in module.name:
                        self.pulse.module_unload(module.index)

            self.pulse.close()
            logger.info("Audio manager cleanup complete")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
