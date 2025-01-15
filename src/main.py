"""
Main entry point for Pi Audio Sync
"""

import os
import sys
import uvicorn
from fastapi import FastAPI
from loguru import logger
import threading

from .audio import AudioManager, BluetoothManager
from .api import router


def setup_logging():
    """Setup logging configuration"""
    log_dir = os.path.expanduser("~/.local/log/pi-audio-sync")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "pi-audio-sync.log")
    logger.add(log_file, rotation="10 MB", retention="7 days")
    logger.add(sys.stderr, level="INFO")


def main():
    """Main entry point"""
    setup_logging()
    logger.info("Starting Pi Audio Sync")

    # Initialize managers immediately
    audio_manager = AudioManager()
    bluetooth_manager = BluetoothManager()

    # Store managers in router module
    router._audio_manager = audio_manager
    router._bluetooth_manager = bluetooth_manager

    app = FastAPI()
    app.include_router(router)

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
