"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import asyncio
from typing import List, Optional
import libpipewire as pw
from loguru import logger

from ..models import AudioSource, DeviceState, SystemState, DeviceType


class AudioManager:
    def __init__(self):
        try:
            # Initialize PipeWire
            self.loop = pw.Loop()
            self.core = pw.Core(self.loop)
            self.context = pw.Context()
            self.core.connect(self.context)
            self.registry = pw.Registry(self.core)
            self._init_audio()
        except Exception as e:
            logger.error(f"Failed to initialize PipeWire: {e}")
            raise

    def _init_audio(self):
        """Initialize audio devices"""
        try:
            # Get all nodes
            nodes = self.core.get_nodes()
            logger.info(f"Found {len(nodes)} audio nodes")

            if not nodes:
                logger.error("No audio nodes found")
                return

            # Find audio sinks (outputs)
            self.sinks = [
                node for node in nodes if node.props.get("media.class") == "Audio/Sink"
            ]
            logger.info(f"Found {len(self.sinks)} audio sinks")

            # Set default sink
            try:
                default = next(
                    (
                        s
                        for s in self.sinks
                        if "bcm2835" in s.props.get("node.name", "").lower()
                    ),
                    self.sinks[0] if self.sinks else None,
                )
                if default:
                    self.core.set_default_node(default)
                    logger.info(
                        f"Set default sink to: {default.props.get('node.name')}"
                    )
            except Exception as e:
                logger.error(f"Failed to set default sink: {e}")

        except Exception as e:
            logger.error(f"Error initializing audio: {e}")
            # Don't raise here, let the service continue with limited functionality

    def get_devices(self) -> List[DeviceState]:
        """Get list of audio devices"""
        try:
            return [
                DeviceState(
                    id=sink.id,
                    name=sink.props.get(
                        "node.description", sink.props.get("node.name", "Unknown")
                    ),
                    type=DeviceType.USB
                    if "usb" in sink.props.get("node.name", "").lower()
                    else DeviceType.BUILTIN,
                    volume=int(sink.props.get("node.volume", 1.0) * 100),
                    muted=bool(sink.props.get("node.mute", False)),
                    active=True,
                )
                for sink in self.sinks
            ]
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            return []

    def set_volume(self, device_id: int, volume: int) -> bool:
        """Set volume for a device"""
        try:
            volume = max(0, min(100, volume))  # Clamp volume between 0 and 100
            node = next((n for n in self.sinks if n.id == device_id), None)
            if not node:
                logger.error(f"Node {device_id} not found")
                return False

            node.set_param("Props", {"node.volume": volume / 100})
            logger.info(
                f"Set volume to {volume}% for node {node.props.get('node.name')}"
            )
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False

    def set_mute(self, device_id: int, muted: bool) -> bool:
        """Set mute state for a device"""
        try:
            node = next((n for n in self.sinks if n.id == device_id), None)
            if not node:
                logger.error(f"Node {device_id} not found")
                return False

            node.set_param("Props", {"node.mute": muted})
            logger.info(
                f"{'Muted' if muted else 'Unmuted'} node {node.props.get('node.name')}"
            )
            return True
        except Exception as e:
            logger.error(f"Error setting mute: {e}")
            return False

    def get_system_state(self) -> SystemState:
        """Get current system state"""
        return SystemState(devices=self.get_devices())
