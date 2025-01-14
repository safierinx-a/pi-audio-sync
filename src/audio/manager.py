"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from typing import List, Optional
from loguru import logger

from ..models import AudioSource, DeviceState, SystemState, DeviceType


class AudioManager:
    def __init__(self):
        try:
            # Initialize D-Bus
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SessionBus()

            # Get PipeWire interface
            self.pw_obj = self.bus.get_object(
                "org.pipewire.pipewire", "/org/pipewire/pipewire"
            )
            self.pw = dbus.Interface(self.pw_obj, "org.pipewire.pipewire.core1")

            # Initialize device tracking
            self.devices = {}
            self._init_audio()
            logger.info("Audio manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PipeWire: {e}")
            raise

    def _init_audio(self):
        """Initialize audio devices"""
        try:
            # Get all nodes
            objects = self.pw.ListObjects()
            logger.info(f"Found {len(objects)} audio objects")

            # Find audio sinks (outputs)
            self.sinks = []
            for path, interfaces in objects:
                if "org.pipewire.node" in interfaces:
                    props = self.pw.GetProperties(path)
                    if props.get("media.class") == "Audio/Sink":
                        self.sinks.append({"path": path, "props": props})

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
                    volume=int(sink["props"].get("node.volume", 1.0) * 100),
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
                self.pw.SetProperty(
                    sink["path"], "node.volume", dbus.Double(volume / 100)
                )
                logger.info(
                    f"Set volume to {volume}% for node {sink['props'].get('node.name')}"
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
                self.pw.SetProperty(sink["path"], "node.mute", dbus.Boolean(muted))
                logger.info(
                    f"{'Muted' if muted else 'Unmuted'} node {sink['props'].get('node.name')}"
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Error setting mute: {e}")
            return False

    def get_system_state(self) -> SystemState:
        """Get current system state"""
        return SystemState(devices=self.get_devices())
