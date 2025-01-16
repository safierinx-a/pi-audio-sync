# Pi Audio Sync

A Raspberry Pi-based audio synchronization system that manages multiple audio outputs (like built-in audio, USB DACs, HDMI) with perfect sync and individual volume control. Integrates with Home Assistant for easy control.

## Features

- Synchronized multi-output audio with sub-millisecond latency
- Individual volume control per output
- Home Assistant integration
- Automatic device recovery
- Support for high-quality audio (up to 24-bit/192kHz with compatible DACs)

## Requirements

### Hardware

- Raspberry Pi (3B+ or newer recommended)
- One or more audio outputs:
  - Built-in audio
  - USB Sound Cards/DACs
  - HDMI audio
  - Any PipeWire-compatible output

### Software

- Raspberry Pi OS (64-bit recommended)
- Python 3.9+
- PipeWire
- ALSA utils

## Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/safierinx/pi-audio-sync.git
   cd pi-audio-sync
   ```

2. Run the installation script:

   ```bash
   sudo ./scripts/install.sh
   ```

3. Configure your environment:

   ```bash
   sudo nano /opt/pi-audio-sync/.env
   # Edit settings as needed
   ```

4. Start the service:
   ```bash
   sudo systemctl start audio-sync
   ```

## Audio Setup

### Audio Outputs

1. Connect your audio devices (USB DAC, HDMI, etc.)
2. Verify detection:

   ```bash
   aplay -l
   # Should show all connected audio devices
   ```

3. The system will automatically:
   - Detect all available outputs
   - Create a combined sink for synchronization
   - Enable synchronized playback across all outputs

### Audio Quality Settings

PipeWire is configured for optimal quality:

- Sample Rate: 48kHz
- Format: 32-bit float
- Resampling: SOX-HQ
- Buffer Size: Optimized for Raspberry Pi 3B

You can adjust these in `config/pipewire/pipewire.conf`.

## Home Assistant Integration

The service exposes a REST API that integrates with Home Assistant for:

- Individual volume control per output
- Device status monitoring
- Health checks and recovery
- Combined sink management

Configuration instructions can be found in [docs/home-assistant.md](docs/home-assistant.md).

## API Documentation

### System Status

```bash
# Get system status
curl http://localhost:8000/api/v1/status
```

### Audio Devices

```bash
# Get all devices
curl http://localhost:8000/api/v1/devices

# Get specific device
curl http://localhost:8000/api/v1/devices/{device_id}

# Get device capabilities
curl http://localhost:8000/api/v1/devices/{device_id}/capabilities

# Set volume (0-100)
curl -X POST -H "Content-Type: application/json" \
     -d '{"volume": 50}' \
     http://localhost:8000/api/v1/devices/{device_id}/volume

# Mute device
curl -X POST http://localhost:8000/api/v1/devices/{device_id}/mute

# Unmute device
curl -X POST http://localhost:8000/api/v1/devices/{device_id}/unmute
```

### Bluetooth Management

```bash
# Get discoverable devices
curl http://localhost:8000/api/v1/bluetooth/devices

# Start discovery
curl -X POST http://localhost:8000/api/v1/bluetooth/discovery/start

# Stop discovery
curl -X POST http://localhost:8000/api/v1/bluetooth/discovery/stop

# Connect to device
curl -X POST http://localhost:8000/api/v1/bluetooth/devices/{device_path}/connect

# Make Pi discoverable
curl -X POST http://localhost:8000/api/v1/bluetooth/discoverable
```

### Home Assistant Integration

```bash
# Get discovery info
curl http://localhost:8000/api/v1/ha/discovery
```

Note: Replace `localhost` with your Pi's IP address when accessing from another device.

## Development

### Setup Development Environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running Tests

```bash
pytest tests/
```

### Service Management

```bash
# Start the service
sudo systemctl start audio-sync
```

## Architecture

The system consists of three main components:

### 1. Audio Manager

- Manages PipeWire nodes and sinks
- Handles device hotplugging
- Creates and maintains synchronized audio outputs
- Provides error recovery

### 2. FastAPI Server

- REST API for device control
- Health monitoring endpoints
- Home Assistant state management
- Volume and mute control

### 3. Home Assistant Integration

- Device discovery and control
- Status monitoring
- Automation support
- Volume synchronization

## Troubleshooting

### Common Issues

1. **No Audio Output**

   - Check physical connections
   - Verify device detection: `aplay -l`
   - Check service status: `systemctl status audio-sync`

2. **Audio Sync Issues**

   - Verify PipeWire config
   - Check audio node status
   - Adjust buffer settings if needed

3. **Home Assistant Connection**
   - Verify network connectivity
   - Check API endpoint accessibility
   - Verify service is running

### Logs

- Service logs: `journalctl -u audio-sync -f`
- PipeWire logs: `journalctl --user -u pipewire -f`
- API logs: `/var/log/pi-audio-sync/api.log`

## License

MIT License - See [LICENSE](LICENSE) for details
