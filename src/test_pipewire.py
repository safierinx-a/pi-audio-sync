#!/usr/bin/env python3

import os
import sys
import subprocess
from loguru import logger

# Configure logging
logger.remove()  # Remove default handler
logger.add(sys.stderr, level="DEBUG")


def check_environment():
    logger.info("Checking environment variables:")
    for var in ["XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "PYTHONPATH"]:
        logger.info(f"{var}: {os.environ.get(var)}")

    # Check user and process info
    logger.info(f"Current user: {os.getuid()}")
    logger.info(f"Current working directory: {os.getcwd()}")


def check_pipewire():
    logger.info("Checking PipeWire status:")

    # Check if pw-cli exists
    try:
        which_result = subprocess.run(
            ["which", "pw-cli"], capture_output=True, text=True
        )
        logger.info(f"pw-cli location: {which_result.stdout.strip()}")
    except Exception as e:
        logger.error(f"Failed to locate pw-cli: {e}")

    # Try running pw-cli
    try:
        result = subprocess.run(
            ["pw-cli", "info", "all"], capture_output=True, text=True
        )
        logger.info(f"PipeWire info output:\n{result.stdout}")
        if result.stderr:
            logger.error(f"PipeWire errors:\n{result.stderr}")
    except Exception as e:
        logger.error(f"Failed to run pw-cli: {e}")

    # Check PipeWire socket
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        pipewire_socket = os.path.join(runtime_dir, "pipewire-0")
        logger.info(f"Checking for PipeWire socket at: {pipewire_socket}")
        if os.path.exists(pipewire_socket):
            logger.info("PipeWire socket exists")
        else:
            logger.error("PipeWire socket not found")


def main():
    logger.info("Starting PipeWire test")
    check_environment()
    check_pipewire()


if __name__ == "__main__":
    main()
