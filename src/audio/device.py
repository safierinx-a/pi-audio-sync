from dataclasses import dataclass
from typing import Optional
from enum import Enum


class DeviceType(Enum):
    BUILTIN = "builtin"
    USB = "usb"


@dataclass
class AudioDevice:
    """Represents a physical audio output device"""

    name: str
    device_type: DeviceType
    pulse_name: str  # PulseAudio sink name
    index: Optional[int] = None
    volume: int = 70
    muted: bool = False

    @property
    def is_active(self) -> bool:
        """Check if device is active and available"""
        return self.index is not None and not self.muted

    def to_dict(self) -> dict:
        """Convert device to dictionary for API responses"""
        return {
            "name": self.name,
            "type": self.device_type.value,
            "volume": self.volume,
            "muted": self.muted,
            "active": self.is_active,
            "index": self.index,
        }
