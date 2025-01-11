from pydantic import BaseModel, Field
from typing import List, Optional


class VolumeUpdate(BaseModel):
    volume: int = Field(..., ge=0, le=100, description="Volume level (0-100)")


class DeviceState(BaseModel):
    name: str
    type: str
    volume: int
    muted: bool
    active: bool
    index: int | None


class AudioSource(BaseModel):
    name: str
    mac_address: Optional[str] = None
    connected: bool = False
    trusted: bool = False
    type: str = "bluetooth"  # bluetooth, airplay, etc.


class SystemState(BaseModel):
    builtin: DeviceState
    usb: DeviceState
    combined_sink_active: bool
    current_source: Optional[AudioSource] = None
    available_sources: List[AudioSource] = []


class SourceConnect(BaseModel):
    mac_address: str = Field(..., description="MAC address of the source device")
    trust: bool = Field(
        False, description="Whether to trust this device for auto-connection"
    )
