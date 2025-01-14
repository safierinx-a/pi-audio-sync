"""
Shared models for Pi Audio Sync
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class DeviceType(str, Enum):
    BUILTIN = "builtin"
    USB = "usb"
    BLUETOOTH = "bluetooth"


class DeviceState(BaseModel):
    id: int
    name: str
    type: DeviceType
    volume: int
    muted: bool
    active: bool


class SystemState(BaseModel):
    devices: List[DeviceState]
    current_source: Optional[str] = None
    available_sources: Optional[List[str]] = None


class VolumeUpdate(BaseModel):
    volume: int
