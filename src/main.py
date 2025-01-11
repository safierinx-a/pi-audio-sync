"""
Main entry point for Pi Audio Sync
"""

import os
import sys
import uvicorn
from fastapi import FastAPI
from loguru import logger

from .audio import AudioManager
from .api import router


def setup_logging():
    """Configure logging"""
    try:
        # Setup user-specific log directory
        log_dir = os.path.expanduser("~/.local/log")
        os.makedirs(log_dir, exist_ok=True)

        # Remove default logger and add our configured one
        logger.remove()
        logger.add(
            f"{log_dir}/pi-audio-sync.log",
            rotation="10 MB",
            level=os.getenv("LOG_LEVEL", "INFO"),
            backtrace=True,
            diagnose=True,
        )
        logger.add(sys.stderr, level="INFO")

        return True
    except Exception as e:
        print(f"Failed to setup logging: {e}")
        return False


def main():
    """Main entry point"""
    # Setup logging
    if not setup_logging():
        sys.exit(1)

    try:
        # Create FastAPI app
        app = FastAPI(
            title="Pi Audio Sync",
            description="Multi-output audio synchronization system",
            version="1.0.0",
        )
        app.include_router(router)

        # Create audio manager
        audio_manager = AudioManager()
        logger.info("Audio manager initialized successfully")

        # Start the FastAPI server
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "8000"))
        logger.info(f"Starting server on {host}:{port}")

        uvicorn.run(app, host=host, port=port)

    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
