#!/usr/bin/env python3

import os
import sys
import subprocess
import time
from loguru import logger

# Configure logging
logger.remove()  # Remove default handler
logger.add(sys.stderr, level="DEBUG")


def check_environment():
    logger.info("Checking environment variables:")
    for var in [
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "PYTHONPATH",
        "PULSE_SERVER",
    ]:
        logger.info(f"{var}: {os.environ.get(var)}")

    # Check user and process info
    logger.info(f"Current user: {os.getuid()}")
    logger.info(f"Current working directory: {os.getcwd()}")


def check_pipewire():
    logger.info("Checking PipeWire status:")

    # Check PipeWire socket
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        # Check all possible PipeWire sockets
        for socket in ["pipewire-0", "pipewire-0.lock", "pulse/native"]:
            socket_path = os.path.join(runtime_dir, socket)
            logger.info(f"Checking for socket at: {socket_path}")
            if os.path.exists(socket_path):
                logger.info(f"Socket exists: {socket_path}")
                try:
                    stats = os.stat(socket_path)
                    logger.info(f"Socket permissions: {oct(stats.st_mode)}")
                    logger.info(f"Socket owner: {stats.st_uid}")
                except Exception as e:
                    logger.error(f"Failed to get socket stats: {e}")
            else:
                logger.error(f"Socket not found: {socket_path}")

    # Check PipeWire processes
    try:
        ps_result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        for line in ps_result.stdout.splitlines():
            if "pipewire" in line or "pulseaudio" in line:
                logger.info(f"Process: {line}")
    except Exception as e:
        logger.error(f"Failed to check processes: {e}")

    # Try running pw-cli with debug output
    try:
        env = os.environ.copy()
        env["PIPEWIRE_DEBUG"] = "3"  # Enable debug output
        result = subprocess.run(
            ["pw-cli", "info", "all"], capture_output=True, text=True, env=env
        )
        logger.info(f"PipeWire info output:\n{result.stdout}")
        if result.stderr:
            logger.error(f"PipeWire errors:\n{result.stderr}")
    except Exception as e:
        logger.error(f"Failed to run pw-cli: {e}")


def main():
    logger.info("Starting PipeWire test")
    check_environment()
    check_pipewire()


if __name__ == "__main__":
    main()
