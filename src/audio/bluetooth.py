import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from typing import Dict, Optional, List, Callable
from loguru import logger
import json
import os
from pathlib import Path
from .agent import BluetoothAgent
import threading


class BluetoothManager:
    """Manages Bluetooth connections and profiles"""

    def __init__(self):
        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.mainloop = GLib.MainLoop()
        self.mainloop_thread = None

        # Initialize Bluetooth objects
        self.manager = dbus.Interface(
            self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
        )

        # Get adapter
        self.adapter = self._get_adapter()
        if not self.adapter:
            raise Exception("No Bluetooth adapter found")

        # Initialize agent manager
        self.agent_manager = dbus.Interface(
            self.bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1"
        )
        self.agent = None

        # Register A2DP sink profile
        self._register_profiles()

        # Device tracking
        self.devices: Dict[str, dict] = {}
        self.trusted_devices: Dict[str, dict] = self._load_trusted_devices()
        self.discovering = False

        # Set up signal handlers
        self._setup_signal_handlers()

        # Start agent
        self._start_agent()

        logger.info("Bluetooth manager initialized")

    def _get_adapter(self) -> Optional[dbus.Interface]:
        """Get the first available Bluetooth adapter"""
        objects = self.manager.GetManagedObjects()
        for path, interfaces in objects.items():
            if "org.bluez.Adapter1" in interfaces:
                adapter = dbus.Interface(
                    self.bus.get_object("org.bluez", path), "org.bluez.Adapter1"
                )
                # Configure adapter
                props = dbus.Interface(
                    self.bus.get_object("org.bluez", path),
                    "org.freedesktop.DBus.Properties",
                )
                props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
                props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
                props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
                props.Set(
                    "org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0)
                )  # Always discoverable
                props.Set(
                    "org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(0)
                )  # Always pairable

                # Set friendly name
                props.Set("org.bluez.Adapter1", "Alias", "Pi Audio Receiver")

                logger.info(f"Configured Bluetooth adapter: {path}")
                return adapter
        return None

    def _load_trusted_devices(self) -> Dict[str, dict]:
        """Load trusted devices from storage"""
        config_dir = Path(os.path.expanduser("~/.config/pi-audio-sync"))
        config_dir.mkdir(parents=True, exist_ok=True)

        devices_file = config_dir / "trusted_devices.json"
        if devices_file.exists():
            try:
                return json.loads(devices_file.read_text())
            except Exception as e:
                logger.error(f"Failed to load trusted devices: {e}")
        return {}

    def _save_trusted_devices(self):
        """Save trusted devices to storage"""
        config_dir = Path(os.path.expanduser("~/.config/pi-audio-sync"))
        devices_file = config_dir / "trusted_devices.json"
        try:
            devices_file.write_text(json.dumps(self.trusted_devices))
        except Exception as e:
            logger.error(f"Failed to save trusted devices: {e}")

    def _start_agent(self):
        """Register and start the Bluetooth agent"""
        try:
            # Try to register our agent path first
            try:
                self.agent_manager.RegisterAgent(
                    BluetoothAgent.AGENT_PATH, BluetoothAgent.CAPABILITY
                )
                # If we get here, no agent exists, so create one
                self.agent = BluetoothAgent(self.bus)
                self.agent_manager.RequestDefaultAgent(BluetoothAgent.AGENT_PATH)
                logger.info("Bluetooth agent registered successfully")
            except dbus.exceptions.DBusException as e:
                if "AlreadyExists" in str(e):
                    # Agent already registered, we can use it
                    logger.info("Using existing Bluetooth agent")
                    return
                # Some other error occurred
                raise
        except Exception as e:
            logger.error(f"Failed to register Bluetooth agent: {e}")
            raise

    def _setup_signal_handlers(self):
        """Set up D-Bus signal handlers for device events"""
        self.bus.add_signal_receiver(
            self._properties_changed,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged",
            path_keyword="path",
        )

        self.bus.add_signal_receiver(
            self._interfaces_added,
            dbus_interface="org.freedesktop.DBus.ObjectManager",
            signal_name="InterfacesAdded",
        )

        self.bus.add_signal_receiver(
            self._interfaces_removed,
            dbus_interface="org.freedesktop.DBus.ObjectManager",
            signal_name="InterfacesRemoved",
        )

    def _properties_changed(self, interface, changed, invalidated, path):
        """Handle property changes on devices"""
        if interface != "org.bluez.Device1":
            return

        device_path = path
        if "Connected" in changed:
            connected = changed["Connected"]
            if connected:
                logger.info(f"Device {device_path} connected")
                self._setup_profiles(device_path)
            else:
                logger.info(f"Device {device_path} disconnected")
                self._handle_disconnect(device_path)

    def _interfaces_added(self, path, interfaces):
        """Handle new device discovery"""
        if "org.bluez.Device1" not in interfaces:
            return

        try:
            props = interfaces["org.bluez.Device1"]
            addr = str(props.get("Address", ""))
            name = str(props.get("Name", addr))
            paired = bool(props.get("Paired", False))
            trusted = bool(props.get("Trusted", False))

            # Check if device interface exists before adding
            device = self.bus.get_object("org.bluez", path)
            if not device:
                logger.error(f"Device object not found at path: {path}")
                return

            # Verify Device1 interface exists
            try:
                dbus.Interface(device, "org.bluez.Device1")
            except dbus.exceptions.DBusException as e:
                logger.error(f"Device1 interface not available: {e}")
                return

            self.devices[path] = {
                "address": addr,
                "name": name,
                "trusted": trusted,
                "paired": paired,
            }

            logger.info(f"Found device: {name} ({addr})")

            # Check if this is a trusted device
            if addr in self.trusted_devices:
                logger.info(f"Found trusted device: {name} ({addr})")
                self._trust_device(path)
                if not props.get("Connected", False):
                    self._try_connect(path)

        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus error handling device: {e}")
        except Exception as e:
            logger.error(f"Error handling new device at {path}: {e}")

    def _interfaces_removed(self, path, interfaces):
        """Handle device removal"""
        if path in self.devices:
            del self.devices[path]

    def _setup_profiles(self, device_path):
        """Set up audio profiles for a device."""
        try:
            # First check if device exists
            device = self.bus.get_object("org.bluez", device_path)
            if not device:
                logger.error(f"Device not found at path: {device_path}")
                return

            # Verify Device1 interface exists
            try:
                device_interface = dbus.Interface(device, "org.bluez.Device1")
            except dbus.exceptions.DBusException as e:
                logger.error(f"Device1 interface not available: {e}")
                return

            props = dbus.Interface(device, "org.freedesktop.DBus.Properties")

            # Get UUIDs with error handling
            try:
                uuids = props.Get("org.bluez.Device1", "UUIDs")
                logger.info(f"Device UUIDs: {uuids}")
            except dbus.exceptions.DBusException as e:
                logger.error(f"Failed to get device UUIDs: {e}")
                return

            # Set device as trusted
            try:
                props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
            except dbus.exceptions.DBusException as e:
                logger.error(f"Failed to set device as trusted: {e}")
                # Continue anyway as this is not critical

            # Set A2DP sink profile
            try:
                device_interface.ConnectProfile("0000110b-0000-1000-8000-00805f9b34fb")
                logger.info(f"Set A2DP sink profile for {device_path}")
            except dbus.exceptions.DBusException as e:
                if "Already Connected" in str(e):
                    logger.info(
                        f"A2DP sink profile already connected for {device_path}"
                    )
                else:
                    logger.error(f"Error setting A2DP sink profile: {e}")

        except dbus.exceptions.DBusException as e:
            logger.error(f"DBus error setting up profiles: {e}")
        except Exception as e:
            logger.error(f"Error setting up profiles: {e}")

    def _set_profile(self, device_path: str, profile: str):
        """Set specific audio profile"""
        # This method is no longer used as we handle profile selection through the A2DPSinkProfile class
        pass

    def _handle_disconnect(self, device_path: str):
        """Handle device disconnection"""
        try:
            device = self.bus.get_object("org.bluez", device_path)
            props = dbus.Interface(device, "org.freedesktop.DBus.Properties")
            addr = str(props.Get("org.bluez.Device1", "Address"))

            if addr in self.trusted_devices:
                logger.info(f"Trusted device disconnected: {addr}")
                # Schedule reconnection attempt
                GLib.timeout_add_seconds(5, lambda: self._try_connect(device_path))
        except Exception as e:
            logger.error(f"Error handling disconnect for {device_path}: {e}")

    def _try_connect(self, device_path: str) -> bool:
        """Attempt to connect to a device"""
        try:
            device = dbus.Interface(
                self.bus.get_object("org.bluez", device_path), "org.bluez.Device1"
            )
            device.Connect()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {device_path}: {e}")
            return False

    def _trust_device(self, device_path: str):
        """Trust a device"""
        try:
            device = dbus.Interface(
                self.bus.get_object("org.bluez", device_path), "org.bluez.Device1"
            )
            device.Trusted = True
            logger.info(f"Device trusted: {device_path}")
        except Exception as e:
            logger.error(f"Failed to trust device {device_path}: {e}")

    def start_discovery(self, duration: int = 30):
        """Start device discovery"""
        try:
            if self.discovering:
                logger.info("Discovery already in progress")
                return

            # Power on adapter if needed
            adapter_props = dbus.Interface(
                self.bus.get_object("org.bluez", self.adapter.object_path),
                "org.freedesktop.DBus.Properties",
            )
            if not adapter_props.Get("org.bluez.Adapter1", "Powered"):
                adapter_props.Set("org.bluez.Adapter1", "Powered", True)

            # Start discovery
            self.adapter.StartDiscovery()
            self.discovering = True
            logger.info("Started Bluetooth discovery")

            # Schedule discovery stop
            GLib.timeout_add_seconds(duration, self._stop_discovery)

        except Exception as e:
            logger.error(f"Failed to start discovery: {e}")

    def _stop_discovery(self) -> bool:
        """Stop device discovery"""
        try:
            if not self.discovering:
                return False
            self.adapter.StopDiscovery()
            self.discovering = False
            logger.info("Stopped Bluetooth discovery")
        except Exception as e:
            logger.error(f"Failed to stop discovery: {e}")
        return False  # Don't repeat the timeout

    def start(self):
        """Start the Bluetooth manager in a separate thread"""
        if self.mainloop_thread and self.mainloop_thread.is_alive():
            logger.warning("Bluetooth manager already running")
            return

        def run_mainloop():
            try:
                logger.info("Starting Bluetooth mainloop")
                self.mainloop.run()
                logger.info("Bluetooth mainloop ended")
            except Exception as e:
                logger.error(f"Error in Bluetooth mainloop: {e}")

        self.mainloop_thread = threading.Thread(target=run_mainloop, daemon=True)
        self.mainloop_thread.start()
        logger.info("Started Bluetooth manager thread")

    def stop(self):
        """Stop the Bluetooth manager"""
        try:
            if self.discovering:
                self._stop_discovery()

            # Clean up agent
            if self.agent:
                try:
                    self.agent_manager.UnregisterAgent(self.agent.AGENT_PATH)
                    self.agent.remove_from_connection()
                    logger.info("Unregistered Bluetooth agent")
                except Exception as e:
                    logger.error(f"Error cleaning up Bluetooth agent: {e}")

            # Stop mainloop
            if self.mainloop.is_running():
                self.mainloop.quit()
            if self.mainloop_thread and self.mainloop_thread.is_alive():
                self.mainloop_thread.join(timeout=5)
            logger.info("Stopped Bluetooth manager")
        except Exception as e:
            logger.error(f"Error stopping Bluetooth manager: {e}")

    def get_connected_devices(self) -> List[dict]:
        """Get list of connected devices"""
        connected = []
        for path, device in self.devices.items():
            try:
                dev_interface = dbus.Interface(
                    self.bus.get_object("org.bluez", path),
                    "org.freedesktop.DBus.Properties",
                )
                props = dev_interface.GetAll("org.bluez.Device1")
                if props.get("Connected", False):
                    connected.append(
                        {
                            "name": device["name"],
                            "address": device["address"],
                            "trusted": device["trusted"],
                            "paired": device["paired"],
                        }
                    )
            except Exception as e:
                logger.error(f"Error getting device status: {e}")
        return connected

    def get_discoverable_devices(self) -> List[dict]:
        """Get list of discoverable devices"""
        devices = []
        for path, device in self.devices.items():
            if not device.get("paired", False):  # Only return unpaired devices
                devices.append(
                    {"name": device["name"], "address": device["address"], "path": path}
                )
        return devices

    def pair_device(self, device_path: str) -> bool:
        """Initiate pairing with a device"""
        try:
            device = dbus.Interface(
                self.bus.get_object("org.bluez", device_path), "org.bluez.Device1"
            )
            device.Pair()
            logger.info(f"Initiated pairing with device: {device_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to pair device {device_path}: {e}")
            return False

    def set_discoverable(self, discoverable: bool = True, timeout: int = 180):
        """Make the Bluetooth adapter discoverable and start/stop discovery"""
        try:
            adapter_props = dbus.Interface(
                self.bus.get_object("org.bluez", self.adapter.object_path),
                "org.freedesktop.DBus.Properties",
            )
            # Make sure adapter is powered on
            if not adapter_props.Get("org.bluez.Adapter1", "Powered"):
                adapter_props.Set("org.bluez.Adapter1", "Powered", True)

            # Set discoverable and pairable
            adapter_props.Set("org.bluez.Adapter1", "Discoverable", discoverable)
            adapter_props.Set("org.bluez.Adapter1", "Pairable", discoverable)

            if discoverable:
                # Start discovery when making discoverable
                if not self.discovering:
                    self.adapter.StartDiscovery()
                    self.discovering = True
                    # Schedule discovery stop
                    GLib.timeout_add_seconds(timeout, self._stop_discovery)
            else:
                # Stop discovery when making not discoverable
                if self.discovering:
                    self._stop_discovery()

            logger.info(f"Adapter discoverable: {discoverable}, timeout: {timeout}s")
        except Exception as e:
            logger.error(f"Failed to set discoverable mode: {e}")

    def connect_device(self, device_path: str) -> bool:
        """Connect to a device"""
        try:
            device = dbus.Interface(
                self.bus.get_object("org.bluez", device_path), "org.bluez.Device1"
            )
            device.Connect()
            # Wait for connection and set up profiles
            self._setup_profiles(device_path)
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {device_path}: {e}")
            return False

    def _register_profiles(self):
        """Register Bluetooth profiles"""
        try:
            # Get profile manager
            profile_manager = dbus.Interface(
                self.bus.get_object("org.bluez", "/org/bluez"),
                "org.bluez.ProfileManager1",
            )

            # Create and register A2DP sink profile
            self.sink_profile = A2DPSinkProfile(self.bus)
            profile_path = self.sink_profile.path
            uuid = "0000110b-0000-1000-8000-00805f9b34fb"  # A2DP sink UUID

            # Make adapter discoverable and pairable
            adapter_props = dbus.Interface(
                self.bus.get_object("org.bluez", self.adapter.object_path),
                "org.freedesktop.DBus.Properties",
            )
            adapter_props.Set("org.bluez.Adapter1", "Discoverable", True)
            adapter_props.Set("org.bluez.Adapter1", "Pairable", True)
            adapter_props.Set(
                "org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0)
            )
            adapter_props.Set("org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(0))

            # Register profile
            opts = {
                "Name": "A2DP Audio Sink",
                "Role": "sink",
                "RequireAuthentication": False,
                "RequireAuthorization": False,
                "AutoConnect": True,
                "ServiceRecord": """
                    <?xml version="1.0" encoding="UTF-8" ?>
                    <record>
                        <attribute id="0x0001">
                            <sequence>
                                <uuid value="0x110b"/>
                            </sequence>
                        </attribute>
                        <attribute id="0x0004">
                            <sequence>
                                <sequence>
                                    <uuid value="0x0100"/>
                                </sequence>
                                <sequence>
                                    <uuid value="0x0003"/>
                                    <uint8 value="0x08"/>
                                </sequence>
                            </sequence>
                        </attribute>
                        <attribute id="0x0100">
                            <text value="A2DP Audio Sink"/>
                        </attribute>
                        <attribute id="0x0009">
                            <sequence>
                                <sequence>
                                    <uuid value="0x110b"/>
                                    <uint16 value="0x0100"/>
                                </sequence>
                            </sequence>
                        </attribute>
                    </record>
                """,
            }

            try:
                profile_manager.RegisterProfile(profile_path, uuid, opts)
                logger.info("Registered A2DP sink profile")
            except dbus.exceptions.DBusException as e:
                if "AlreadyExists" in str(e):
                    logger.info("A2DP sink profile already registered")
                else:
                    raise

        except Exception as e:
            logger.error(f"Failed to register profiles: {e}")

    def get_devices(self):
        """Get a list of all known Bluetooth devices."""
        try:
            devices = []
            objects = self.bus.get_object("org.bluez", "/")
            manager = dbus.Interface(objects, "org.freedesktop.DBus.ObjectManager")
            objects = manager.GetManagedObjects()

            for path, interfaces in objects.items():
                if "org.bluez.Device1" not in interfaces:
                    continue

                props = interfaces["org.bluez.Device1"]
                devices.append(
                    {
                        "path": path,
                        "name": props.get("Name", props.get("Address", "Unknown")),
                        "address": props.get("Address", ""),
                        "connected": props.get("Connected", False),
                        "paired": props.get("Paired", False),
                        "trusted": props.get("Trusted", False),
                    }
                )
            return devices
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return []


class A2DPSinkProfile:
    """Handler for A2DP sink profile"""

    def __init__(self, bus):
        self.bus = bus
        self.path = "/org/bluez/profile/a2dp_sink"

    def Release(self):
        logger.info("A2DP sink profile released")

    def NewConnection(self, device_path, fd, properties):
        logger.info(f"New A2DP sink connection from {device_path}")
        # Here we would handle the audio stream fd
        # For now, we just keep it open

    def RequestDisconnection(self, device_path):
        logger.info(f"A2DP sink disconnection request for {device_path}")
