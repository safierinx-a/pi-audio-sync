"""
Main entry point for Pi Audio Sync
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI
from loguru import logger

from .audio import AudioManager
from .api import router

# Load environment variables
load_dotenv()

# Configure logging
logger.add(
    "logs/pi-audio-sync.log",
    rotation="1 day",
    retention="7 days",
    level=os.getenv("LOG_LEVEL", "INFO"),
)

# Create FastAPI app
app = FastAPI(
    title="Pi Audio Sync",
    description="Multi-output audio synchronization system",
    version="1.0.0",
)

# Create audio manager instance
audio_manager = AudioManager()

# Add API routes
app.include_router(router)

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=os.getenv("APP_ENV") == "development",
    )
