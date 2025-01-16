#!/bin/bash

# Exit on any error
set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Ensure SUDO_USER is set
if [ -z "$SUDO_USER" ]; then
    echo "This script must be run with sudo"
    exit 1
fi

echo "Installing Pi Audio Sync..."

# Create temporary directory
TEMP_DIR=$(mktemp -d)
echo "Created temporary directory: $TEMP_DIR"

# Copy current files to temp directory
echo "Backing up current files..."
cp -r . $TEMP_DIR/

# System diagnostics
echo "Running system diagnostics..."
echo "Checking audio devices..."
aplay -l
echo "Checking PipeWire installation..."
which pipewire
which pw-cli
which pw-dump

# Clean up old installations
echo "Cleaning up old installations..."
systemctl --user -M $SUDO_USER@ stop audio-sync || true
systemctl --user -M $SUDO_USER@ disable audio-sync || true
rm -f /home/$SUDO_USER/.config/systemd/user/audio-sync.service
rm -rf /etc/pipewire/*

# Only remove contents of /opt/pi-audio-sync if it exists and is not the current directory
if [ -d "/opt/pi-audio-sync" ] && [ "$PWD" != "/opt/pi-audio-sync" ]; then
    echo "Cleaning up old installation directory..."
    rm -rf /opt/pi-audio-sync/*
fi

# System Dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-dbus \
    python3-gi \
    python3-aiohttp \
    python3-setuptools \
    python3-fastapi \
    python3-uvicorn \
    python3-dotenv \
    python3-pydantic \
    python3-websockets \
    pipewire \
    pipewire-audio-client-libraries \
    pipewire-pulse \
    wireplumber \
    bluetooth \
    bluez \
    bluez-tools \
    alsa-utils \
    libasound2-plugins \
    libspa-0.2-bluetooth \
    libspa-0.2-modules

# Ensure user is in required groups
echo "Setting up user permissions..."
usermod -a -G audio,bluetooth,pulse,pulse-access $SUDO_USER

# Configure Bluetooth
echo "Configuring Bluetooth..."
# Stop bluetooth to modify settings
systemctl stop bluetooth

# Configure Bluetooth settings
echo "Setting up Bluetooth configuration..."
cat > /etc/bluetooth/main.conf << EOF
[General]
Name = Pi Audio Receiver
Class = 0x240404
DiscoverableTimeout = 0
PairableTimeout = 0
Privacy = 0
Experimental = true
FastConnectable = true
JustWorksRepairing = always
MultiProfile = multiple
AutoEnable = true

[Policy]
AutoEnable = true
ReconnectAttempts = 3
ReconnectIntervals = 1,2,4

[GATT]
KeySize = 0x10
ExchangeMTU = 517
EOF

# Set up Bluetooth adapter
echo "Setting up Bluetooth adapter..."
if ! hciconfig hci0 up; then
    echo "Error enabling Bluetooth adapter"
    exit 1
fi

# Make adapter discoverable and pairable
echo "Making Bluetooth adapter discoverable..."
hciconfig hci0 piscan
hciconfig hci0 sspmode 1
hciconfig hci0 class 0x240404

# Create configuration directories
echo "Setting up PipeWire configuration..."
mkdir -p /etc/pipewire
mkdir -p /home/$SUDO_USER/.config/systemd/user
mkdir -p /home/$SUDO_USER/.config/pipewire

# Copy configurations from temp directory
echo "Copying configuration files..."
cp -r $TEMP_DIR/config/pipewire/* /etc/pipewire/
cp -r $TEMP_DIR/config/bluetooth/* /etc/bluetooth/

# Configure PipeWire for A2DP sink
echo "Configuring PipeWire A2DP sink..."
cat > /etc/pipewire/pipewire-pulse.conf << EOF
context.properties = {
    log.level = 2
}

context.modules = [
    { name = libpipewire-module-rt
        args = {
            nice.level = -11
            rt.prio = 88
            rt.time.soft = 200000
            rt.time.hard = 200000
        }
        flags = [ ifexists nofail ]
    }
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-metadata }
    { name = libpipewire-module-protocol-pulse
        args = {
            server.address = [ "unix:native" "tcp:4713" ]
            pulse.min.req = 256/48000
            pulse.default.req = 960/48000
            pulse.min.frag = 256/48000
            pulse.default.frag = 96000/48000
            pulse.default.tlength = 96000/48000
            pulse.min.quantum = 256/48000
        }
    }
]

stream.properties = {
    node.latency = 1024/48000
    resample.quality = 4
    channelmix.normalize = false
    channelmix.mix-lfe = false
    session.suspend-timeout-seconds = 0
}
EOF

# Configure PipeWire Bluetooth
echo "Configuring PipeWire Bluetooth..."
cat > /etc/pipewire/pipewire.conf.d/99-bluetooth.conf << EOF
context.modules = [
    {
        name = libpipewire-module-bluetooth
        args = {
            bluez5.enable-sbc-xq = true
            bluez5.enable-msbc = true
            bluez5.enable-hw-volume = true
            bluez5.headset-roles = [ a2dp_sink ]
            bluez5.codecs = [ sbc_xq sbc aac ]
            bluez5.hfphsp-backend = native
            bluez5.msbc-support = true
            bluez5.keep-profile = true
        }
    }
]
EOF

# Remove pip package management since we're using system packages
# Clean up old Python packages
echo "Cleaning up Python packages..."
apt-get remove -y python3-fastapi python3-uvicorn python3-dotenv python3-pydantic python3-websockets || true

# Install Python packages from apt
echo "Installing Python packages..."
apt-get install -y \
    python3-fastapi \
    python3-uvicorn \
    python3-dotenv \
    python3-pydantic \
    python3-websockets

# Enable required services
echo "Enabling system services..."
systemctl --system enable bluetooth
systemctl --system start bluetooth

# Verify PipeWire configuration
echo "Verifying PipeWire configuration..."
if [ ! -f /etc/pipewire/pipewire.conf ]; then
    echo "Error: PipeWire configuration not found"
    exit 1
fi

# Install application
echo "Installing application..."
mkdir -p /opt/pi-audio-sync
cp -r $TEMP_DIR/src /opt/pi-audio-sync/
cp -r $TEMP_DIR/config /opt/pi-audio-sync/
chown -R $SUDO_USER:$SUDO_USER /opt/pi-audio-sync

# Install service
echo "Installing service..."
cp $TEMP_DIR/config/systemd/audio-sync.service /home/$SUDO_USER/.config/systemd/user/
chown -R $SUDO_USER:$SUDO_USER /home/$SUDO_USER/.config

# Create log directory
echo "Setting up logging..."
mkdir -p /var/log/pi-audio-sync
chown -R $SUDO_USER:$SUDO_USER /var/log/pi-audio-sync

# Initialize PipeWire
echo "Initializing PipeWire..."
# Stop any existing PipeWire instances
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user stop pipewire pipewire-pulse wireplumber || true

# Clear any existing PipeWire state
rm -rf /run/user/$(id -u $SUDO_USER)/pipewire-* || true

# Start PipeWire stack in the correct order
echo "Starting PipeWire services..."
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user daemon-reload
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user start pipewire
sleep 2
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user start wireplumber
sleep 2
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user start pipewire-pulse

# Verify PipeWire is running
echo "Verifying PipeWire status..."
if ! sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) pw-cli info 0 > /dev/null; then
    echo "Error: PipeWire not running properly"
    exit 1
fi

# Check for audio nodes
echo "Checking for audio nodes..."
if ! sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) pw-dump | grep -q "Audio/Sink"; then
    echo "Warning: No audio sinks found. This might be normal if no devices are connected."
fi

# Start bluetooth
echo "Starting Bluetooth service..."
systemctl start bluetooth
sleep 2

# Enable user services
echo "Enabling user services..."
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user enable pipewire pipewire-pulse wireplumber
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user enable audio-sync

# Clean up temp directory
echo "Cleaning up temporary files..."
rm -rf $TEMP_DIR

echo "Installation complete!"
echo "Please reboot your system to ensure all changes take effect."
echo "After reboot, check service status with: systemctl --user status audio-sync"
echo "Check PipeWire status with: pw-cli info 0"
echo "Check audio devices with: pw-dump | grep Audio/Sink" 