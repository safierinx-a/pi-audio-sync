"""
API routes for Pi Audio Sync
"""

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger
import subprocess
import os

from ..models import DeviceState, SystemState, VolumeUpdate
from ..audio import AudioManager

router = APIRouter(prefix="/api/v1")
_manager: AudioManager = None


async def get_audio_manager() -> AudioManager:
    """Get or create AudioManager instance"""
    global _manager
    if _manager is None:
        _manager = AudioManager()
    return _manager


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
    """Enable Bluetooth pairing mode for the specified duration."""
    try:
        script_path = os.path.join(
            os.environ.get("INSTALL_DIR", "/opt/pi-audio-sync"), "scripts/bluetooth.sh"
        )
        result = subprocess.run(
            [script_path, "enable", str(duration)],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info(f"Enabled Bluetooth pairing: {result.stdout}")
        return {"message": "Pairing mode enabled", "duration": duration}
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to enable pairing mode: {e.stderr}")
        raise HTTPException(status_code=500, detail="Failed to enable pairing mode")


@router.get("/bluetooth/status")
async def get_bluetooth_status():
    """Get current Bluetooth status."""
    try:
        script_path = os.path.join(
            os.environ.get("INSTALL_DIR", "/opt/pi-audio-sync"), "scripts/bluetooth.sh"
        )
        result = subprocess.run(
            [script_path, "status"], capture_output=True, text=True, check=True
        )
        status_lines = result.stdout.strip().split("\n")
        status = {}
        for line in status_lines:
            key, value = line.split(":", 1)
            status[key.strip()] = value.strip()
        return status
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get Bluetooth status: {e.stderr}")
        raise HTTPException(status_code=500, detail="Failed to get Bluetooth status")
