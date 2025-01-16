"""
Audio Manager for Pi Audio Sync
"""

import os
import json
import subprocess
import time
from math import log10
from typing import List, Optional, Dict, Set
from loguru import logger

from ..models import DeviceState, SystemState, DeviceType


class AudioManager:
    def __init__(self):
        self.max_init_retries = 5
        self.init_retry_delay = 2
        self._ensure_pipewire_running()

    def _ensure_pipewire_running(self):
        """Ensure PipeWire is running and properly initialized"""
        for attempt in range(self.max_init_retries):
            try:
                logger.info(
                    f"PipeWire initialization attempt {attempt + 1}/{self.max_init_retries}"
                )

                # Check PipeWire socket
                runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
                socket_path = f"{runtime_dir}/pipewire-0"

                if not os.path.exists(socket_path):
                    logger.warning(f"PipeWire socket not found at {socket_path}")
                    raise Exception("PipeWire socket not found")

                # Verify PipeWire is responding
                result = subprocess.run(
                    ["pw-cli", "info", "0"], capture_output=True, text=True, timeout=5
                )
                if result.returncode != 0:
                    raise Exception(f"PipeWire not responding: {result.stderr}")

                # Check for audio nodes
                nodes = json.loads(
                    subprocess.run(
                        ["pw-dump"], capture_output=True, text=True, timeout=5
                    ).stdout
                )

                audio_nodes = [
                    n
                    for n in nodes
                    if n.get("info", {})
                    .get("props", {})
                    .get("media.class", "")
                    .startswith("Audio/")
                ]

                if not audio_nodes:
                    logger.warning("No audio nodes found")
                    raise Exception("No audio nodes found")

                logger.info(f"Found {len(audio_nodes)} audio nodes")
                return True

            except subprocess.TimeoutExpired:
                logger.warning("PipeWire command timed out")
            except json.JSONDecodeError:
                logger.warning("Failed to parse PipeWire output")
            except Exception as e:
                logger.error(f"PipeWire initialization error: {e}")

            if attempt < self.max_init_retries - 1:
                logger.info(f"Retrying in {self.init_retry_delay} seconds...")
                time.sleep(self.init_retry_delay)

        raise Exception("Failed to initialize PipeWire after multiple attempts")

    def _monitor_pipewire_health(self):
        """Monitor PipeWire health and attempt recovery if needed"""
        try:
            result = subprocess.run(
                ["pw-cli", "info", "0"], capture_output=True, text=True, timeout=2
            )
            if result.returncode != 0:
                logger.warning("PipeWire health check failed, attempting recovery...")
                self._ensure_pipewire_running()
        except Exception as e:
            logger.error(f"PipeWire health check error: {e}")
            self._ensure_pipewire_running()

    def _set_node_params(self, node_id: str, params: Dict):
        """Set parameters for a PipeWire node with error handling"""
        try:
            subprocess.run(
                ["pw-cli", "s", node_id, "Props", json.dumps(params)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            logger.debug(f"Set parameters for node {node_id}: {params}")
        except Exception as e:
            logger.error(f"Failed to set parameters for node {node_id}: {e}")

    def _configure_audio_node(self, node_id: str):
        """Configure an audio node with optimal settings"""
        # Get settings from environment
        sample_rate = int(os.environ.get("SAMPLE_RATE", "48000"))
        buffer_size = int(os.environ.get("BUFFER_SIZE", "1024"))

        # Base configuration for reliable audio
        base_config = {
            "audio.rate": sample_rate,
            "audio.allowed-rates": [sample_rate],
            "node.latency": f"{buffer_size}/{sample_rate}",
            "audio.position": ["FL", "FR"],
            "node.pause-on-idle": False,
            "api.alsa.period-size": buffer_size,
            "api.alsa.headroom": buffer_size * 8,
            "session.suspend-timeout-seconds": 0,
        }

        self._set_node_params(node_id, base_config)

    def refresh_devices(self):
        """Refresh and configure audio devices"""
        try:
            # Get current nodes
            nodes = json.loads(
                subprocess.run(
                    ["pw-dump"], capture_output=True, text=True, timeout=5
                ).stdout
            )

            # Process each audio node
            for node in nodes:
                props = node.get("info", {}).get("props", {})
                if props.get("media.class", "").startswith("Audio/"):
                    node_id = str(node.get("id", ""))
                    self._configure_audio_node(node_id)

            logger.info("Audio devices refreshed and configured")
            return True
        except Exception as e:
            logger.error(f"Error refreshing devices: {e}")
            return False
