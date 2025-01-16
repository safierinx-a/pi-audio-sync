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

# Check if running on Raspberry Pi OS
if ! grep -q "Raspberry Pi" /etc/os-release; then
    echo "This script is designed for Raspberry Pi OS"
    echo "Current OS: $(cat /etc/os-release | grep PRETTY_NAME)"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for internet connectivity
echo "Checking internet connectivity..."
if ! ping -c 1 google.com &> /dev/null; then
    echo "No internet connection. Please connect to the internet and try again."
    exit 1
fi

# Create backup directory for existing configs
BACKUP_DIR="/root/pi-audio-sync-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p $BACKUP_DIR
if [ -d "/etc/pipewire" ]; then
    cp -r /etc/pipewire $BACKUP_DIR/
fi
if [ -d "/etc/bluetooth" ]; then
    cp -r /etc/bluetooth $BACKUP_DIR/
fi
echo "Existing configurations backed up to $BACKUP_DIR"

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
aplay -l || echo "No ALSA devices found"
echo "Checking PipeWire installation..."
which pipewire || echo "PipeWire not found"
which pw-cli || echo "pw-cli not found"
which pw-dump || echo "pw-dump not found"

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
apt-get update || {
    echo "Failed to update package list. Check your internet connection and try again."
    exit 1
}

# Function to check if a package is available
check_package() {
    if ! apt-cache show $1 > /dev/null 2>&1; then
        echo "Warning: Package $1 not found in repositories"
        return 1
    fi
    return 0
}

# Check package availability before installing
MISSING_PACKAGES=""
for package in python3-fastapi python3-uvicorn python3-dotenv python3-pydantic python3-websockets; do
    if ! check_package $package; then
        MISSING_PACKAGES="$MISSING_PACKAGES $package"
    fi
done

if [ ! -z "$MISSING_PACKAGES" ]; then
    echo "The following packages are not available in the default repositories:$MISSING_PACKAGES"
    echo "We will need to install these via pip instead"
    USE_PIP=1
else
    USE_PIP=0
fi

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

# Create PipeWire config directories
echo "Setting up PipeWire configuration..."
mkdir -p /etc/pipewire
mkdir -p /etc/pipewire/pipewire.conf.d
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

# Install Python packages from apt
echo "Installing Python packages..."
apt-get install -y \
    python3-fastapi \
    python3-uvicorn \
    python3-dotenv \
    python3-pydantic \
    python3-websockets

# Install PipeWire packages
echo "Installing PipeWire packages..."
apt-get install -y pipewire pipewire-audio-client-libraries \
    pipewire-pulse libspa-0.2-modules libspa-0.2-bluetooth \
    wireplumber

# Configure main PipeWire settings
echo "Configuring main PipeWire settings..."
cat << 'EOF' | tee /etc/pipewire/pipewire.conf
context.properties = {
    link.max-buffers = 16
    core.daemon = true
    core.name = pipewire-0
}

context.spa-libs = {
    audio.convert.* = audioconvert/libspa-audioconvert
    support.* = support/libspa-support
}

context.modules = [
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-metadata }
    { name = libpipewire-module-spa-device-factory }
    { name = libpipewire-module-spa-node-factory }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-client-device }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-rt }
    { name = libpipewire-module-protocol-pulse }
    { name = libpipewire-module-link-factory }
    { name = libpipewire-module-session-manager }
]

context.objects = [
    { factory = spa-node-factory args = { factory.name = support.node.driver node.name = Dummy-Driver } }
]

context.exec = [
    { path = "/usr/bin/wireplumber" args = "" }
]
EOF

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

# Ensure systemd user instance is running
loginctl enable-linger $SUDO_USER

# Stop all existing audio services
echo "Stopping existing audio services..."
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user stop pipewire pipewire-pulse wireplumber audio-sync || true
systemctl --user -M $SUDO_USER@ stop pipewire pipewire-pulse wireplumber audio-sync || true

# Clear any existing PipeWire state
echo "Clearing PipeWire state..."
rm -rf /run/user/$(id -u $SUDO_USER)/pipewire-* || true
rm -rf /home/$SUDO_USER/.local/state/pipewire/* || true
rm -rf /home/$SUDO_USER/.config/pipewire/media-session.d/* || true

# Ensure runtime directory exists and has correct permissions
echo "Setting up runtime directory..."
mkdir -p /run/user/$(id -u $SUDO_USER)
chown $SUDO_USER:$SUDO_USER /run/user/$(id -u $SUDO_USER)
chmod 700 /run/user/$(id -u $SUDO_USER)

# Debug: Check ALSA devices
echo "Checking ALSA devices..."
aplay -l || echo "No ALSA devices found - this is expected if using only Bluetooth"

# Reload systemd daemon to pick up new service files
echo "Reloading systemd daemon..."
systemctl --user -M $SUDO_USER@ daemon-reload
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user daemon-reload

# Function to start and verify service with better error handling
start_and_verify_service() {
    local service=$1
    echo "Starting $service..."
    
    # Try to start the service
    if ! sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user start $service; then
        echo "Warning: Failed to start $service directly"
        # Try alternative method
        systemctl --user -M $SUDO_USER@ start $service || true
    fi
    
    # Wait for service to settle
    sleep 3
    
    # Check service status
    if ! sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user status $service; then
        echo "Warning: $service failed to start properly"
        echo "Service logs:"
        sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) journalctl --user -u $service -n 50
        return 1
    fi
    return 0
}

# Start services in correct order with proper delays
echo "Starting PipeWire stack..."
start_and_verify_service pipewire
sleep 2
start_and_verify_service wireplumber
sleep 2
start_and_verify_service pipewire-pulse
sleep 2

# Debug: Check PipeWire socket and processes
echo "Debug: Checking PipeWire socket..."
ls -l /run/user/$(id -u $SUDO_USER)/pipewire-0 || echo "PipeWire socket not found"

echo "Debug: Checking PipeWire processes..."
ps aux | grep pipewire

# Wait longer for PipeWire to fully initialize
echo "Waiting for PipeWire to initialize..."
for i in {1..10}; do
    if sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) pw-cli info 0 > /dev/null 2>&1; then
        echo "PipeWire initialized successfully"
        break
    fi
    echo "Attempt $i: Waiting for PipeWire to initialize..."
    sleep 3
    
    # On every other attempt, try restarting pipewire
    if [ $((i % 2)) -eq 0 ]; then
        echo "Attempting to restart PipeWire..."
        sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user restart pipewire
        sleep 2
    fi
done

# Force reload of ALSA and check for devices
echo "Reloading ALSA..."
alsactl kill rescan || true
sleep 2

# Check for audio nodes with detailed output
echo "Checking for audio nodes..."
echo "Debug: Full PipeWire dump:"
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) pw-dump || true

echo "Debug: Looking for audio sinks..."
if ! sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) pw-dump | grep -q "Audio/Sink"; then
    echo "Warning: No audio sinks found. Checking system state:"
    echo "1. ALSA devices:"
    aplay -l
    echo "2. PipeWire modules:"
    sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) pw-cli list-objects | grep module || true
    echo "3. Active PipeWire nodes:"
    sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) pw-cli list-objects | grep node || true
    echo "4. PipeWire service status:"
    sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user status pipewire
fi

# Start bluetooth
echo "Starting Bluetooth service..."
systemctl start bluetooth
sleep 2

# Enable user services
echo "Enabling user services..."
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user enable pipewire pipewire-pulse wireplumber
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user enable audio-sync

# Final status check
echo "Performing final status check..."
FAILED_SERVICES=""

check_service() {
    if ! systemctl --user -M $SUDO_USER@ status $1 > /dev/null 2>&1; then
        FAILED_SERVICES="$FAILED_SERVICES $1"
    fi
}

check_service pipewire
check_service pipewire-pulse
check_service wireplumber
check_service audio-sync

if [ ! -z "$FAILED_SERVICES" ]; then
    echo "Warning: The following services failed to start:$FAILED_SERVICES"
    echo "You may need to investigate these services after reboot"
fi

# Clean up temp directory
echo "Cleaning up temporary files..."
rm -rf $TEMP_DIR

echo "Installation complete!"
echo "A backup of your original configuration has been saved to $BACKUP_DIR"
if [ ! -z "$FAILED_SERVICES" ]; then
    echo "Note: Some services failed to start. Please check the logs after reboot."
fi

echo "Would you like to reboot now? (recommended)"
read -p "Reboot now? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Rebooting in 5 seconds... Press Ctrl+C to cancel"
    sleep 5
    reboot
else
    echo "Please reboot your system manually to ensure all changes take effect."
    echo "After reboot, check service status with: systemctl --user status audio-sync"
    echo "Check PipeWire status with: pw-cli info 0"
    echo "Check audio devices with: pw-dump | grep Audio/Sink"
fi 