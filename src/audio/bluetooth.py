import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from typing import Dict, Optional, List, Callable
from loguru import logger
import json
import os
from pathlib import Path
from .agent import BluetoothAgent


class BluetoothManager:
    """Manages Bluetooth connections and profiles"""

    def __init__(self):
        # Initialize D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.mainloop = GLib.MainLoop()

        # Initialize Bluetooth objects
        self.manager = dbus.Interface(
            self.bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
        )

        # Initialize agent
        self.agent = BluetoothAgent(self.bus)
        self.agent_manager = dbus.Interface(
            self.bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1"
        )

        # Device tracking
        self.devices: Dict[str, dict] = {}
        self.trusted_devices: Dict[str, dict] = self._load_trusted_devices()

        # Set up signal handlers
        self._setup_signal_handlers()

        # Start agent
        self._start_agent()

        logger.info("Bluetooth manager initialized")

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
            self.agent_manager.RegisterAgent(
                self.agent.AGENT_PATH, self.agent.CAPABILITY
            )
            self.agent_manager.RequestDefaultAgent(self.agent.AGENT_PATH)
            logger.info("Bluetooth agent registered successfully")
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

        props = interfaces["org.bluez.Device1"]
        addr = str(props.get("Address", ""))
        name = str(props.get("Name", "Unknown"))

        self.devices[path] = {
            "address": addr,
            "name": name,
            "trusted": False,
            "paired": False,
        }

        # Check if this is a trusted device
        if addr in self.trusted_devices:
            logger.info(f"Found trusted device: {name} ({addr})")
            self._trust_device(path)
            self._try_connect(path)

    def _interfaces_removed(self, path, interfaces):
        """Handle device removal"""
        if path in self.devices:
            del self.devices[path]

    def _setup_profiles(self, device_path):
        """Set up audio profiles for connected device"""
        try:
            device = dbus.Interface(
                self.bus.get_object("org.bluez", device_path), "org.bluez.Device1"
            )

            # Get UUIDs
            props = device.GetProperties()
            uuids = props.get("UUIDs", [])

            # Check for A2DP profile
            if "0000110a-0000-1000-8000-00805f9b34fb" in uuids:  # A2DP Sink
                logger.info(f"Setting up A2DP profile for {device_path}")
                self._set_profile(device_path, "a2dp_sink")

            # Mark as trusted if connection successful
            addr = str(props.get("Address", ""))
            name = str(props.get("Name", "Unknown"))
            self.trusted_devices[addr] = {"name": name, "last_connected": True}
            self._save_trusted_devices()

        except Exception as e:
            logger.error(f"Failed to setup profiles for {device_path}: {e}")

    def _set_profile(self, device_path: str, profile: str):
        """Set specific audio profile"""
        try:
            device = dbus.Interface(
                self.bus.get_object("org.bluez", device_path),
                "org.freedesktop.DBus.Properties",
            )
            device.Set("org.bluez.Device1", "Profile", profile)
            logger.info(f"Set profile {profile} for {device_path}")
        except Exception as e:
            logger.error(f"Failed to set profile {profile}: {e}")

    def _handle_disconnect(self, device_path: str):
        """Handle device disconnection"""
        try:
            device = dbus.Interface(
                self.bus.get_object("org.bluez", device_path), "org.bluez.Device1"
            )
            props = device.GetProperties()
            addr = str(props.get("Address", ""))

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

    def start(self):
        """Start the Bluetooth manager"""
        logger.info("Starting Bluetooth manager")
        self.mainloop.run()

    def stop(self):
        """Stop the Bluetooth manager"""
        logger.info("Stopping Bluetooth manager")
        self.mainloop.quit()

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

    def start_discovery(self, duration: int = 60):
        """Make the device discoverable and start scanning for devices"""
        try:
            adapter = dbus.Interface(
                self.bus.get_object("org.bluez", "/org/bluez/hci0"),
                "org.bluez.Adapter1",
            )

            # Set discoverable
            props = dbus.Interface(
                self.bus.get_object("org.bluez", "/org/bluez/hci0"),
                "org.freedesktop.DBus.Properties",
            )
            props.Set("org.bluez.Adapter1", "Discoverable", True)
            props.Set(
                "org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(duration)
            )
            props.Set("org.bluez.Adapter1", "Pairable", True)

            # Start scanning
            adapter.StartDiscovery()
            logger.info(f"Started Bluetooth discovery for {duration} seconds")
            return True
        except Exception as e:
            logger.error(f"Failed to start discovery: {e}")
            return False

    def stop_discovery(self):
        """Stop device discovery"""
        try:
            adapter = dbus.Interface(
                self.bus.get_object("org.bluez", "/org/bluez/hci0"),
                "org.bluez.Adapter1",
            )
            adapter.StopDiscovery()
            logger.info("Stopped Bluetooth discovery")
            return True
        except Exception as e:
            logger.error(f"Failed to stop discovery: {e}")
            return False

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
