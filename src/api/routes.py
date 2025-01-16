"""
API routes for Pi Audio Sync
"""

from fastapi import APIRouter, HTTPException, Depends, Request, Body, WebSocket
from loguru import logger
import subprocess
import os
from typing import List, Optional, Dict
from pydantic import BaseModel
import json

from ..models import DeviceState, SystemState, VolumeUpdate, DeviceCapabilities
from ..audio import AudioManager, BluetoothManager

router = APIRouter(prefix="/api/v1")
_audio_manager: Optional[AudioManager] = None
_bluetooth_manager: Optional[BluetoothManager] = None
_websocket_clients: List[WebSocket] = []


def initialize_managers():
    """Initialize the global manager instances"""
    global _audio_manager, _bluetooth_manager

    if _audio_manager is None:
        _audio_manager = AudioManager()

    if _bluetooth_manager is None:
        _bluetooth_manager = BluetoothManager()
        _bluetooth_manager.start()  # Start the Bluetooth mainloop


async def get_audio_manager() -> AudioManager:
    """Get the AudioManager instance"""
    if _audio_manager is None:
        initialize_managers()
    return _audio_manager


async def get_bluetooth_manager() -> BluetoothManager:
    """Get the BluetoothManager instance"""
    if _bluetooth_manager is None:
        initialize_managers()
    return _bluetooth_manager


async def broadcast_state_change(state: dict):
    """Broadcast state change to all connected clients"""
    for client in _websocket_clients:
        try:
            await client.send_json(state)
        except Exception as e:
            logger.error(f"Error broadcasting to client: {e}")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    _websocket_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle any incoming messages if needed
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        _websocket_clients.remove(websocket)


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


@router.get("/devices/{device_id}/capabilities")
async def get_device_capabilities(
    device_id: int, manager: AudioManager = Depends(get_audio_manager)
) -> DeviceCapabilities:
    """Get device capabilities"""
    try:
        devices = manager.get_devices()
        device = next((d for d in devices if d.id == device_id), None)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        return DeviceCapabilities(
            can_mute=True,
            has_volume=True,
            volume_steps=100,
            is_bluetooth=device.type == "bluetooth",
            supported_features=["volume", "mute", "bluetooth"]
            if device.type == "bluetooth"
            else ["volume", "mute"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting device capabilities: {e}")
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


# Home Assistant integration endpoints
@router.get("/ha/discovery")
async def get_ha_discovery() -> Dict:
    """Get Home Assistant discovery information"""
    try:
        manager = await get_audio_manager()
        devices = manager.get_devices()

        discovery_info = {
            "name": "Pi Audio Sync",
            "model": "Multi-Room Audio",
            "manufacturer": "Custom",
            "version": "1.0",
            "devices": [
                {
                    "identifiers": [f"pi_audio_sync_{d.id}"],
                    "name": d.name,
                    "model": "Audio Output",
                    "type": d.type,
                    "capabilities": {
                        "volume": True,
                        "mute": True,
                        "bluetooth": d.type == "bluetooth",
                    },
                }
                for d in devices
            ],
        }
        return discovery_info
    except Exception as e:
        logger.error(f"Error getting discovery info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Bluetooth endpoints
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


@router.on_event("startup")
async def startup_event():
    """Initialize managers on startup"""
    initialize_managers()


@router.on_event("shutdown")
async def shutdown_event():
    """Clean up managers on shutdown"""
    if _bluetooth_manager:
        _bluetooth_manager.stop()


# Bluetooth endpoints
@router.post("/bluetooth/discoverable")
async def set_discoverable(manager: BluetoothManager = Depends(get_bluetooth_manager)):
    """Make the Pi discoverable and start scanning for devices"""
    try:
        manager.set_discoverable(True, 180)
        return {
            "status": "success",
            "message": "Device is now discoverable and scanning",
        }
    except Exception as e:
        logger.error(f"Error setting discoverable mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bluetooth/discoverable/stop")
async def stop_discoverable(manager: BluetoothManager = Depends(get_bluetooth_manager)):
    """Stop being discoverable and stop scanning"""
    try:
        manager.set_discoverable(False)
        return {"status": "success", "message": "Device is no longer discoverable"}
    except Exception as e:
        logger.error(f"Error stopping discoverable mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))
