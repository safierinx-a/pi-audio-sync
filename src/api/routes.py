"""
API routes for Pi Audio Sync
"""

from fastapi import APIRouter, HTTPException, Depends, Request, Body
from loguru import logger
import subprocess
import os
from typing import List, Optional
from pydantic import BaseModel

from ..models import DeviceState, SystemState, VolumeUpdate
from ..audio import AudioManager, BluetoothManager

router = APIRouter(prefix="/api/v1")
_audio_manager: AudioManager = None
_bluetooth_manager: BluetoothManager = None


async def get_audio_manager() -> AudioManager:
    """Get or create AudioManager instance"""
    global _audio_manager
    if _audio_manager is None:
        _audio_manager = AudioManager()
    return _audio_manager


async def get_bluetooth_manager() -> BluetoothManager:
    """Get or create BluetoothManager instance"""
    global _bluetooth_manager
    if _bluetooth_manager is None:
        _bluetooth_manager = BluetoothManager()
    return _bluetooth_manager


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


@router.post("/devices/{device_id}/volume")
async def set_volume_post(
    device_id: int,
    volume: int = Body(..., embed=True),
    manager: AudioManager = Depends(get_audio_manager),
):
    """Set device volume (POST method)"""
    try:
        logger.debug(f"Setting volume for device {device_id} to {volume}")
        if not manager.set_volume(device_id, volume):
            raise HTTPException(status_code=400, detail="Failed to set volume")
        return {"status": "ok"}
    except ValueError as e:
        logger.error(f"Invalid volume value: {e}")
        raise HTTPException(status_code=400, detail=str(e))
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


@router.get("/bluetooth/devices")
async def get_bluetooth_devices(
    manager: BluetoothManager = Depends(get_bluetooth_manager),
):
    """Get list of Bluetooth devices"""
    try:
        return manager.get_devices()
    except Exception as e:
        logger.error(f"Error getting Bluetooth devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bluetooth/discovery/start")
async def start_discovery(manager: BluetoothManager = Depends(get_bluetooth_manager)):
    """Start Bluetooth discovery"""
    try:
        manager.start_discovery()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error starting discovery: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bluetooth/discovery/stop")
async def stop_discovery(manager: BluetoothManager = Depends(get_bluetooth_manager)):
    """Stop Bluetooth discovery"""
    try:
        manager.stop_discovery()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error stopping discovery: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bluetooth/devices/{address}/pair")
async def pair_device(
    address: str, manager: BluetoothManager = Depends(get_bluetooth_manager)
):
    """Pair with a Bluetooth device"""
    try:
        if not manager.pair_device(address):
            raise HTTPException(status_code=400, detail="Failed to pair device")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error pairing device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bluetooth/devices/{address}/connect")
async def connect_device(
    address: str, manager: BluetoothManager = Depends(get_bluetooth_manager)
):
    """Connect to a Bluetooth device"""
    try:
        if not manager.connect_device(address):
            raise HTTPException(status_code=400, detail="Failed to connect device")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error connecting device: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bluetooth/devices/{address}/disconnect")
async def disconnect_device(
    address: str, manager: BluetoothManager = Depends(get_bluetooth_manager)
):
    """Disconnect from a Bluetooth device"""
    try:
        if not manager.disconnect_device(address):
            raise HTTPException(status_code=400, detail="Failed to disconnect device")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error disconnecting device: {e}")
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


@router.post("/devices/{device_id}/default")
async def set_default_device(device_id: int):
    """Set the default audio output device"""
    if not get_audio_manager().set_default_device(device_id):
        raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "ok"}


@router.get("/sources")
async def get_sources(manager: AudioManager = Depends(get_audio_manager)):
    """Get list of available audio sources"""
    return manager.get_sources()


@router.post("/sources/{source_id}/route")
async def set_source_routing(
    source_id: int,
    sink_names: List[str],
    manager: AudioManager = Depends(get_audio_manager),
):
    """Set which outputs a source should play through"""
    if manager.set_source_routing(source_id, sink_names):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Source not found")
