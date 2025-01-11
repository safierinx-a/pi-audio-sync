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
  - Any PulseAudio-compatible output

### Software

- Raspberry Pi OS (64-bit recommended)
- Python 3.9+
- PulseAudio
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

PulseAudio is configured for optimal quality:

- Sample Rate: 48kHz
- Format: 32-bit float
- Resampling: SOX-HQ
- Buffer Size: Optimized for Raspberry Pi 3B

You can adjust these in `config/pulse/daemon.conf`.

## Home Assistant Integration

The service exposes a REST API that integrates with Home Assistant for:

- Individual volume control per output
- Device status monitoring
- Health checks and recovery
- Combined sink management

Configuration instructions can be found in [docs/home-assistant.md](docs/home-assistant.md).

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

# Stop the service
sudo systemctl stop audio-sync

# View logs
journalctl -u audio-sync -f
```

## Architecture

The system consists of three main components:

### 1. Audio Manager

- Manages PulseAudio devices and sinks
- Handles device hotplugging
- Creates and maintains combined sink
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

   - Verify PulseAudio config
   - Check combined sink status
   - Adjust buffer settings if needed

3. **Home Assistant Connection**
   - Verify network connectivity
   - Check API endpoint accessibility
   - Verify service is running

### Logs

- Service logs: `journalctl -u audio-sync -f`
- PulseAudio logs: `journalctl -u pulseaudio -f`
- API logs: `/var/log/pi-audio-sync/api.log`

## License

MIT License - See [LICENSE](LICENSE) for details
