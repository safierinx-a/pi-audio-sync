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

# Function to run commands with timeout
run_with_timeout() {
    local cmd="$1"
    local timeout="$2"
    local message="$3"
    
    echo "$message..."
    timeout "$timeout" bash -c "$cmd" || {
        echo "Command timed out after ${timeout}s: $cmd"
        return 1
    }
}

# Function to run commands as user
run_as_user() {
    local cmd="$1"
    su - $SUDO_USER -c "$cmd"
}

# Function to check if a package is installed
is_package_installed() {
    dpkg -l "$1" &> /dev/null
}

# Function to run systemd user commands
run_systemd_user() {
    local cmd="$1"
    loginctl enable-linger $SUDO_USER
    export XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER)
    su - $SUDO_USER -c "systemctl --user $cmd"
}

# Clean up old services and state
echo "Cleaning up old services and state..."
run_systemd_user "stop pipewire pipewire-pulse wireplumber audio-sync 2>/dev/null || true"
run_systemd_user "disable audio-sync 2>/dev/null || true"

# Clean up old state
rm -rf /home/$SUDO_USER/.local/state/pipewire
rm -rf /home/$SUDO_USER/.local/state/wireplumber
rm -f /home/$SUDO_USER/.config/systemd/user/audio-sync.service

# Update package lists
echo "Updating package lists..."
apt-get update || {
    echo "Failed to update package lists. Please check your internet connection."
    exit 1
}

# Install required system packages
echo "Installing system packages..."
SYSTEM_PACKAGES=(
    # Audio stack
    pipewire
    pipewire-audio-client-libraries
    pipewire-pulse
    wireplumber
    # Bluetooth stack
    bluetooth
    bluez
    # Python and dependencies
    python3
    python3-pip
    python3-setuptools
    python3-wheel
    # System utilities
    alsa-utils
)

# Check package availability
MISSING_PACKAGES=()
for pkg in "${SYSTEM_PACKAGES[@]}"; do
    if ! apt-cache show "$pkg" &> /dev/null; then
        MISSING_PACKAGES+=("$pkg")
    fi
done

if [ ${#MISSING_PACKAGES[@]} -ne 0 ]; then
    echo "Warning: The following packages are not available in the repositories:"
    printf '%s\n' "${MISSING_PACKAGES[@]}"
    echo "Please ensure you have the correct repositories enabled."
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Install system packages
echo "Installing system packages..."
apt-get install -y "${SYSTEM_PACKAGES[@]}" || {
    echo "Failed to install system packages. Please check the error messages above."
    exit 1
}

# Install Python dependencies
echo "Installing Python dependencies..."
python3 -m pip install --break-system-packages fastapi uvicorn python-dotenv pydantic websockets || {
    echo "Failed to install Python dependencies. Please check the error messages above."
    exit 1
}

# Ensure user is in required groups
echo "Setting up user permissions..."
usermod -a -G audio,bluetooth,pulse,pulse-access $SUDO_USER

# Create necessary directories
echo "Creating configuration directories..."
mkdir -p /etc/pipewire/pipewire.conf.d
mkdir -p /home/$SUDO_USER/.config/systemd/user
mkdir -p /var/log/pi-audio-sync
chown -R $SUDO_USER:$SUDO_USER /var/log/pi-audio-sync

# Install application
echo "Installing application..."
rm -rf /opt/pi-audio-sync
mkdir -p /opt/pi-audio-sync
cp -r src config requirements.txt /opt/pi-audio-sync/

# Set up environment file
echo "Setting up environment file..."
cat > /opt/pi-audio-sync/.env << EOF
# Application Settings
APP_NAME=pi-audio-sync
APP_ENV=development
DEBUG=true
LOG_LEVEL=INFO

# Network Settings
HOST=0.0.0.0
PORT=8000
API_PORT=8001

# Audio Settings
BUILTIN_DEVICE_NAME="Built-in Audio"
USB_DEVICE_NAME="USB Audio"
SAMPLE_RATE=44100
BUFFER_SIZE=2048
DEFAULT_VOLUME=70

# Home Assistant Integration
HASS_URL=http://homeassistant:8123
HASS_TOKEN=
HASS_ENTITY_PREFIX=media_player.pi_audio

# Security
API_KEY=
JWT_SECRET= 
EOF

chown -R $SUDO_USER:$SUDO_USER /opt/pi-audio-sync

# Copy configurations
echo "Copying configuration files..."
cp -r config/pipewire/* /etc/pipewire/
cp -r config/systemd/* /home/$SUDO_USER/.config/systemd/user/
chown -R $SUDO_USER:$SUDO_USER /home/$SUDO_USER/.config

# Configure Bluetooth
echo "Configuring Bluetooth..."
systemctl stop bluetooth
cp config/bluetooth/main.conf /etc/bluetooth/
systemctl start bluetooth

# Ensure runtime directory exists with correct permissions
echo "Setting up runtime directory..."
mkdir -p /run/user/$(id -u $SUDO_USER)
chown $SUDO_USER:$SUDO_USER /run/user/$(id -u $SUDO_USER)
chmod 700 /run/user/$(id -u $SUDO_USER)

# Reload systemd user daemon
echo "Reloading systemd user daemon..."
run_systemd_user "daemon-reload"

# Start PipeWire stack in correct order
echo "Starting audio services..."
run_systemd_user "enable --now pipewire.socket"
sleep 2
run_systemd_user "enable --now pipewire.service"
sleep 2
run_systemd_user "enable --now wireplumber.service"
sleep 2
run_systemd_user "enable --now pipewire-pulse.socket"
sleep 2
run_systemd_user "enable --now pipewire-pulse.service"
sleep 2

# Verify PipeWire is running
echo "Verifying PipeWire setup..."
if ! run_with_timeout "run_as_user 'pw-cli info 0'" 5 "Checking PipeWire core"; then
    echo "Error: PipeWire core not responding"
    echo "PipeWire logs:"
    run_as_user "journalctl --user -u pipewire -n 50"
    exit 1
fi

# Verify audio nodes are present
echo "Checking for audio nodes..."
if ! run_with_timeout "run_as_user 'pw-dump'" 5 "Checking audio nodes" | grep -q "Audio/"; then
    echo "Warning: No audio nodes found. System state:"
    echo "1. ALSA devices:"
    aplay -l
    echo "2. PipeWire nodes:"
    run_as_user "pw-cli list-objects | grep node"
    echo "3. Service status:"
    run_as_user "systemctl --user status pipewire pipewire-pulse wireplumber"
fi

# Start audio-sync service
echo "Starting audio-sync service..."
run_systemd_user "enable --now audio-sync.service"

# Verify service is running
echo "Verifying audio-sync service..."
if ! run_with_timeout "run_as_user 'systemctl --user status audio-sync'" 5 "Checking audio-sync service"; then
    echo "Error: audio-sync service failed to start"
    echo "Service logs:"
    run_as_user "journalctl --user -u audio-sync -n 50"
    exit 1
fi

echo "Installation completed successfully!"
echo "You can check the service status with: systemctl --user status audio-sync"
echo "View logs with: journalctl --user -u audio-sync -f"
echo "View PipeWire status with: pw-cli info 0"
echo "List audio devices with: pw-dump | grep Audio/" 