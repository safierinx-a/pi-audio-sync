"""
Shared models for Pi Audio Sync
"""

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


class DeviceType(Enum):
    BUILTIN = "builtin"
    USB = "usb"


@dataclass
class AudioSource:
    name: str
    mac_address: str
    connected: bool = False
    trusted: bool = False
    type: str = "bluetooth"


@dataclass
class DeviceState:
    id: str
    name: str
    type: DeviceType
    volume: int
    muted: bool
    active: bool


@dataclass
class SystemState:
    devices: List[DeviceState]
    current_source: Optional[AudioSource] = None
    available_sources: List[AudioSource] = None


@dataclass
class VolumeUpdate:
    volume: int
