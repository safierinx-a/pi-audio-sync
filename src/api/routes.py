from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from loguru import logger
from typing import List

from .models import VolumeUpdate, DeviceState, SystemState, AudioSource, SourceConnect
from ..audio import AudioManager

router = APIRouter(prefix="/api/v1")


async def get_audio_manager() -> AudioManager:
    """Dependency to get the AudioManager instance"""
    # In a real app, we'd get this from a dependency injection system
    # For now, we'll assume it's set globally
    from ..main import audio_manager

    return audio_manager


@router.get("/status", response_model=SystemState)
async def get_status(manager: AudioManager = Depends(get_audio_manager)):
    """Get the status of all audio devices"""
    try:
        devices = manager.get_devices()
        sources = await manager.get_sources()
        current = await manager.get_current_source()

        return SystemState(
            builtin=DeviceState(**next(d for d in devices if d["type"] == "builtin")),
            usb=DeviceState(**next(d for d in devices if d["type"] == "usb")),
            combined_sink_active=manager.combined_sink is not None,
            current_source=current,
            available_sources=sources,
        )
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system status")


@router.get("/devices/{device_id}", response_model=DeviceState)
async def get_device(
    device_id: str, manager: AudioManager = Depends(get_audio_manager)
):
    """Get the status of a specific device"""
    device = manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return DeviceState(**device)


@router.put("/devices/{device_id}/volume")
async def set_volume(
    device_id: str,
    update: VolumeUpdate,
    manager: AudioManager = Depends(get_audio_manager),
):
    """Set the volume for a specific device"""
    success = await manager.set_volume(device_id, update.volume)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to set volume")
    return {"status": "ok"}


@router.post("/devices/{device_id}/mute")
async def set_mute(device_id: str, manager: AudioManager = Depends(get_audio_manager)):
    """Mute a specific device"""
    success = await manager.set_mute(device_id, True)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to mute device")
    return {"status": "ok"}


@router.post("/devices/{device_id}/unmute")
async def set_unmute(
    device_id: str, manager: AudioManager = Depends(get_audio_manager)
):
    """Unmute a specific device"""
    success = await manager.set_mute(device_id, False)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to unmute device")
    return {"status": "ok"}


@router.post("/sources/scan", response_model=List[AudioSource])
async def scan_sources(
    background_tasks: BackgroundTasks,
    manager: AudioManager = Depends(get_audio_manager),
):
    """Start scanning for audio sources"""
    try:
        # Start scanning in background
        background_tasks.add_task(manager.start_source_scan)
        return await manager.get_sources()
    except Exception as e:
        logger.error(f"Failed to scan for sources: {e}")
        raise HTTPException(status_code=500, detail="Failed to scan for sources")


@router.post("/sources/{mac_address}/connect")
async def connect_source(
    mac_address: str,
    params: SourceConnect,
    manager: AudioManager = Depends(get_audio_manager),
):
    """Connect to an audio source"""
    try:
        success = await manager.connect_source(mac_address, trust=params.trust)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to connect to source")
        return {"status": "connected"}
    except Exception as e:
        logger.error(f"Failed to connect to source: {e}")
        raise HTTPException(status_code=500, detail="Failed to connect to source")


@router.post("/sources/{mac_address}/disconnect")
async def disconnect_source(
    mac_address: str, manager: AudioManager = Depends(get_audio_manager)
):
    """Disconnect from an audio source"""
    try:
        success = await manager.disconnect_source(mac_address)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to disconnect source")
        return {"status": "disconnected"}
    except Exception as e:
        logger.error(f"Failed to disconnect source: {e}")
        raise HTTPException(status_code=500, detail="Failed to disconnect source")


@router.post("/sources/{mac_address}/trust")
async def trust_source(
    mac_address: str, manager: AudioManager = Depends(get_audio_manager)
):
    """Trust an audio source for auto-connection"""
    try:
        success = await manager.trust_source(mac_address)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to trust source")
        return {"status": "trusted"}
    except Exception as e:
        logger.error(f"Failed to trust source: {e}")
        raise HTTPException(status_code=500, detail="Failed to trust source")


# Update Home Assistant endpoint to include source information
@router.get("/hass/states")
async def get_hass_states(manager: AudioManager = Depends(get_audio_manager)):
    """Get states in Home Assistant format"""
    try:
        devices = manager.get_devices()
        sources = await manager.get_sources()
        current_source = await manager.get_current_source()
        states = []

        # Add output devices
        for device in devices:
            states.append(
                {
                    "state": "on" if not device["muted"] else "off",
                    "attributes": {
                        "friendly_name": device["name"],
                        "volume_level": device["volume"] / 100,
                        "is_volume_muted": device["muted"],
                        "source": "combined" if manager.combined_sink else "direct",
                        "supported_features": 4
                        | 8,  # SUPPORT_VOLUME_SET | SUPPORT_VOLUME_MUTE
                    },
                }
            )

        # Add source device state
        states.append(
            {
                "state": "playing" if current_source else "idle",
                "attributes": {
                    "friendly_name": "Audio Source",
                    "source": current_source.name if current_source else "none",
                    "source_list": [s.name for s in sources if s.trusted],
                    "supported_features": 512,  # SUPPORT_SELECT_SOURCE
                },
            }
        )

        return states
    except Exception as e:
        logger.error(f"Failed to get Home Assistant states: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get Home Assistant states"
        )
