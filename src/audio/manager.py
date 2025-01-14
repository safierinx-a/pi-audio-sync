"""
Audio Manager for Pi Audio Sync
"""

import os
import json
from typing import List, Optional
from loguru import logger
import gi

gi.require_version("Gst", "1.0")
gi.require_version("Pipewire", "0.3")
from gi.repository import GLib, Gst, Pipewire

from ..models import AudioSource, DeviceState, SystemState, DeviceType


class AudioManager:
    def __init__(self):
        try:
            # Initialize GLib and PipeWire
            Gst.init(None)
            Pipewire.init()
            self.loop = GLib.MainLoop()

            # Get PipeWire context
            self.context = Pipewire.Context.new(self.loop.get_context())
            self.context.connect()

            # Get core and registry
            self.core = self.context.get_core()
            self.registry = self.core.get_registry()

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

            def registry_global(registry, object_id, type, version, props):
                if type == "PipeWire:Interface:Node":
                    if props.get("media.class") == "Audio/Sink":
                        self.sinks.append({"id": object_id, "props": dict(props)})

            self.registry.connect("global", registry_global)
            self.registry.sync()

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
                node = self.core.lookup_proxy(sink["id"])
                if node:
                    props = node.get_properties()
                    props["node.volume"] = volume / 100
                    node.set_properties(props)
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
                node = self.core.lookup_proxy(sink["id"])
                if node:
                    props = node.get_properties()
                    props["node.mute"] = muted
                    node.set_properties(props)
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
