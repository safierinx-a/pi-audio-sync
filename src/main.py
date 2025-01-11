"""
Main entry point for Pi Audio Sync
"""

import os
import uvicorn
from fastapi import FastAPI
from loguru import logger

from .audio import AudioManager
from .api import router

# Configure logging
logger.add("/var/log/pi-audio-sync.log", rotation="10 MB")

# Create FastAPI app
app = FastAPI(title="Pi Audio Sync")
app.include_router(router)

# Create audio manager
audio_manager = AudioManager()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    # Start the FastAPI server
    uvicorn.run(app, host=host, port=port)
