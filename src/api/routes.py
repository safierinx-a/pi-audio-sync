"""
API routes for Pi Audio Sync
"""

import os
import subprocess
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
from fastapi import APIRouter, HTTPException, Depends
from loguru import logger

from ..models import DeviceState, SystemState, VolumeUpdate
from ..audio import AudioManager

router = APIRouter(prefix="/api/v1")
_manager: AudioManager = None
_agent = None


class BluetoothAgent(dbus.service.Object):
    """Bluetooth agent for handling pairing requests"""

    AGENT_PATH = "/org/bluez/agent"
    CAPABILITY = "KeyboardDisplay"

    def __init__(self, bus):
        super().__init__(bus, self.AGENT_PATH)
        self.mainloop = GLib.MainLoop()

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        logger.info(f"Authorizing service {uuid} for device {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        logger.info(f"Authorizing device {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        logger.info("Request canceled")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        logger.info(f"Display pin code {pincode} for device {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def DisplayPasskey(self, device, passkey):
        logger.info(f"Display passkey {passkey} for device {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
    def RequestConfirmation(self, device, passkey, entered):
        logger.info(f"Confirming passkey {passkey} for device {device}")
        return

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        logger.info(f"Request pin code for device {device}")
        return "0000"

    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        logger.info(f"Request passkey for device {device}")
        return 0


async def get_audio_manager() -> AudioManager:
    """Get or create AudioManager instance"""
    global _manager
    if _manager is None:
        _manager = AudioManager()
    return _manager


def register_agent():
    """Register the Bluetooth agent"""
    global _agent
    if _agent is None:
        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()
            _agent = BluetoothAgent(bus)

            obj = bus.get_object("org.bluez", "/org/bluez")
            manager = dbus.Interface(obj, "org.bluez.AgentManager1")
            manager.RegisterAgent(_agent.AGENT_PATH, _agent.CAPABILITY)
            manager.RequestDefaultAgent(_agent.AGENT_PATH)

            logger.info("Bluetooth agent registered successfully")
        except Exception as e:
            logger.error(f"Failed to register Bluetooth agent: {e}")
            raise


@router.get("/status")
async def get_status(manager: AudioManager = Depends(get_audio_manager)) -> SystemState:
    """Get system status"""
    try:
        return manager.get_system_state()
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{device_id}")
async def get_device(
    device_id: int, manager: AudioManager = Depends(get_audio_manager)
) -> DeviceState:
    """Get device status"""
    try:
        devices = manager.get_devices()
        device = next((d for d in devices if d.id == device_id), None)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        return device
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/devices/{device_id}/volume")
async def set_volume(
    device_id: int,
    update: VolumeUpdate,
    manager: AudioManager = Depends(get_audio_manager),
):
    """Set device volume"""
    try:
        if not manager.set_volume(device_id, update.volume):
            raise HTTPException(status_code=400, detail="Failed to set volume")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error setting volume: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices/{device_id}/mute")
async def mute_device(
    device_id: int, manager: AudioManager = Depends(get_audio_manager)
):
    """Mute device"""
    try:
        if not manager.set_mute(device_id, True):
            raise HTTPException(status_code=400, detail="Failed to mute device")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error muting device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices/{device_id}/unmute")
async def unmute_device(
    device_id: int, manager: AudioManager = Depends(get_audio_manager)
):
    """Unmute device"""
    try:
        if not manager.set_mute(device_id, False):
            raise HTTPException(status_code=400, detail="Failed to unmute device")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error unmuting device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hass/states")
async def get_hass_states(manager: AudioManager = Depends(get_audio_manager)):
    """Get states for Home Assistant"""
    try:
        state = manager.get_system_state()
        return {
            "state": "on",
            "attributes": {
                "devices": [
                    {
                        "name": device.name,
                        "volume": device.volume,
                        "muted": device.muted,
                        "active": device.active,
                    }
                    for device in state.devices
                ]
            },
        }
    except Exception as e:
        logger.error(f"Error getting Home Assistant states: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bluetooth/pairing")
async def enable_pairing_mode(duration: int = 60):
    """Enable Bluetooth pairing mode for specified duration (seconds)"""
    try:
        # Register agent if not already registered
        register_agent()

        # Make Bluetooth discoverable
        subprocess.run(["sudo", "bluetoothctl", "discoverable", "on"], check=True)
        subprocess.run(["sudo", "bluetoothctl", "pairable", "on"], check=True)

        # Set friendly name
        subprocess.run(
            ["sudo", "bluetoothctl", "system-alias", "Pi Audio Sync"], check=True
        )

        # Set timeout (if supported)
        subprocess.run(
            ["sudo", "bluetoothctl", "discoverable-timeout", str(duration)], check=True
        )

        logger.info(f"Bluetooth pairing mode enabled for {duration} seconds")
        return {"status": "enabled", "duration": duration}
    except Exception as e:
        logger.error(f"Failed to enable pairing mode: {e}")
        raise HTTPException(status_code=500, detail="Failed to enable pairing mode")


@router.get("/bluetooth/status")
async def get_bluetooth_status():
    """Get Bluetooth status"""
    try:
        # Get discoverable status
        result = subprocess.run(
            ["bluetoothctl", "show"], capture_output=True, text=True, check=True
        )

        # Parse output
        lines = result.stdout.split("\n")
        status = {
            "discoverable": any("Discoverable: yes" in line for line in lines),
            "powered": any("Powered: yes" in line for line in lines),
            "name": next(
                (line.split(": ")[1] for line in lines if "Alias: " in line),
                "Pi Audio Sync",
            ),
        }

        return status
    except Exception as e:
        logger.error(f"Failed to get Bluetooth status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get Bluetooth status")
