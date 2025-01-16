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

# Function definitions
function run_with_timeout() {
    local cmd="$1"
    local timeout="$2"
    local message="$3"
    
    echo "Debug: Running command: $cmd"
    timeout "$timeout" bash -c "$cmd"
    local exit_code=$?
    
    if [ $exit_code -eq 124 ]; then
        echo "Command timed out after ${timeout}s: $cmd"
        return 1
    elif [ $exit_code -ne 0 ]; then
        echo "Command failed with exit code $exit_code: $cmd"
        return 1
    fi
    return 0
}

function run_as_user() {
    local cmd="$1"
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u $SUDO_USER)/bus" \
    XDG_RUNTIME_DIR="/run/user/$(id -u $SUDO_USER)" \
    sudo -u "$SUDO_USER" bash -c "$cmd"
}

function is_package_installed() {
    dpkg -l "$1" &> /dev/null
}

function run_systemd_user() {
    local cmd="$1"
    sudo -u "$SUDO_USER" \
    DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
    XDG_RUNTIME_DIR="$RUNTIME_DIR" \
    systemctl --user $cmd
}

# Update package lists first
echo "Updating package lists..."
apt-get update || {
    echo "Failed to update package lists. Please check your internet connection."
    exit 1
}

# Install required system packages first
echo "Installing system packages..."
SYSTEM_PACKAGES=(
    # Audio stack
    pipewire
    pipewire-audio-client-libraries
    pipewire-pulse
    pipewire-bin
    pipewire-tests
    pipewire-alsa
    libpipewire-0.3-*
    libpipewire-0.3-modules
    libspa-0.2-*
    libspa-0.2-bluetooth
    libspa-0.2-jack
    wireplumber
    # Bluetooth stack
    bluetooth
    bluez
    bluez-tools
    python3-dbus
    python3-gi
    python3-gi-cairo
    gir1.2-gtk-3.0
    # Python and dependencies
    python3
    python3-pip
    python3-setuptools
    python3-wheel
    # System utilities
    alsa-utils
    dbus
    rtkit  # For realtime priority
)

# Install packages
echo "Installing system packages..."
apt-get install -y "${SYSTEM_PACKAGES[@]}" || {
    echo "Failed to install system packages. Please check the error messages above."
    exit 1
}

# Set up runtime directory and D-Bus session before any systemd commands
echo "Setting up runtime directory and D-Bus session..."
RUNTIME_DIR="/run/user/$(id -u $SUDO_USER)"
mkdir -p "$RUNTIME_DIR"
chown $SUDO_USER:$SUDO_USER "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR"

# Export necessary environment variables
export XDG_RUNTIME_DIR="$RUNTIME_DIR"
DBUS_SESSION_BUS_ADDRESS="unix:path=$RUNTIME_DIR/bus"
export DBUS_SESSION_BUS_ADDRESS

# Start D-Bus session if not running
if ! pgrep -u $SUDO_USER dbus-daemon >/dev/null; then
    echo "Starting D-Bus session daemon..."
    sudo -u $SUDO_USER dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --nofork --nopidfile --syslog-only &
    sleep 2
fi

# Verify D-Bus session is running
echo "Verifying D-Bus session..."
if ! sudo -u $SUDO_USER dbus-send --session --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ListNames >/dev/null 2>&1; then
    echo "Error: D-Bus session not running properly"
    exit 1
fi

# Function to run systemd user commands
function run_systemd_user() {
    local cmd="$1"
    sudo -u "$SUDO_USER" \
    DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
    XDG_RUNTIME_DIR="$RUNTIME_DIR" \
    systemctl --user $cmd
}

# Clean up old services and state
echo "Cleaning up old services and state..."
run_systemd_user "stop pipewire pipewire-pulse wireplumber audio-sync 2>/dev/null || true"
run_systemd_user "disable audio-sync 2>/dev/null || true"

# Clean up old state
rm -rf /home/$SUDO_USER/.local/state/pipewire
rm -rf /home/$SUDO_USER/.local/state/wireplumber
rm -f /home/$SUDO_USER/.config/systemd/user/audio-sync.service

# Install apt-file for package content search
echo "Installing apt-file..."
apt-get install -y apt-file || {
    echo "Failed to install apt-file. Package content search will be limited."
}
apt-file update || true

# Check repository configuration
echo "Verifying repository configuration..."
if ! grep -r "^deb.*main" /etc/apt/sources.list /etc/apt/sources.list.d/; then
    echo "Error: Main repository not found in sources"
    exit 1
fi

# Debug repository and package information
echo "=== Repository Status ==="
apt-cache policy
echo "=== PipeWire Package Information ==="
apt-cache show pipewire libpipewire-0.3-modules || true
echo "=== Available PipeWire Packages ==="
apt-cache search pipewire
echo "=== System Architecture ==="
dpkg --print-architecture
uname -m

# Debug PipeWire module locations
echo "=== Searching for PipeWire Modules ==="
echo "1. Package contents for pipewire-bin:"
dpkg -L pipewire-bin 2>/dev/null | grep -i module || true
echo "2. Package contents for libpipewire-0.3-modules:"
dpkg -L libpipewire-0.3-modules 2>/dev/null | grep -i module || true
echo "3. All PipeWire modules in system:"
find /usr -name "libpipewire-module-*.so" 2>/dev/null || true
echo "4. All SPA modules in system:"
find /usr -name "libspa-*.so" 2>/dev/null || true
echo "5. Package providing bluez5 module:"
apt-file search libpipewire-module-bluez5.so 2>/dev/null || true

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
systemctl enable bluetooth

# Verify Bluetooth is running
echo "Verifying Bluetooth setup..."
if ! systemctl is-active bluetooth > /dev/null; then
    echo "Error: Bluetooth service not running"
    systemctl status bluetooth
    exit 1
fi

# Ensure Bluetooth adapter is powered on
if ! bluetoothctl show | grep -q "Powered: yes"; then
    echo "Powering on Bluetooth adapter..."
    bluetoothctl power on
fi

# Reload systemd user daemon
echo "Reloading systemd user daemon..."
run_systemd_user "daemon-reload"

# Start PipeWire stack in correct order
echo "Starting audio services..."
run_systemd_user "stop pipewire pipewire-pulse wireplumber"
sleep 2

# Clear any existing state
rm -rf /home/$SUDO_USER/.local/state/pipewire
rm -rf /home/$SUDO_USER/.local/state/wireplumber

run_systemd_user "daemon-reload"
run_systemd_user "start pipewire.socket"
sleep 2
run_systemd_user "start pipewire.service"
sleep 2
run_systemd_user "start wireplumber.service"
sleep 2
run_systemd_user "start pipewire-pulse.socket"
sleep 2
run_systemd_user "start pipewire-pulse.service"
sleep 5

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

# After installing packages, verify PipeWire modules
echo "Verifying PipeWire installation..."
ARCH=$(uname -m)
MODULE_PATHS=(
    "/usr/lib/pipewire-0.3"
    "/usr/lib/$ARCH-linux-gnu/pipewire-0.3"
)

# Check for mandatory modules
MANDATORY_MODULES=(
    "libpipewire-module-protocol-native.so"
    "libpipewire-module-client-node.so"
    "libpipewire-module-adapter.so"
    "libpipewire-module-metadata.so"
)

MISSING_MODULES=()
for module in "${MANDATORY_MODULES[@]}"; do
    FOUND=0
    for path in "${MODULE_PATHS[@]}"; do
        if [ -f "$path/$module" ]; then
            FOUND=1
            echo "Found $module in $path"
            break
        fi
    done
    if [ $FOUND -eq 0 ]; then
        MISSING_MODULES+=("$module")
    fi
done

if [ ${#MISSING_MODULES[@]} -ne 0 ]; then
    echo "Error: Missing PipeWire modules:"
    printf '%s\n' "${MISSING_MODULES[@]}"
    echo "Trying to fix by reinstalling packages..."
    apt-get install --reinstall pipewire pipewire-bin libpipewire-0.3-modules || {
        echo "Failed to install PipeWire modules. Please check your system's package repositories."
        # List available packages for debugging
        echo "Available PipeWire packages:"
        apt-cache search pipewire
        echo "Available modules in standard paths:"
        find /usr/lib -name "libpipewire-module-*.so" 2>/dev/null || true
        exit 1
    }
fi

# Check for optional Bluetooth module
echo "Checking for Bluetooth module..."
BLUETOOTH_MODULE="libpipewire-module-bluez5.so"
FOUND=0
for path in "${MODULE_PATHS[@]}"; do
    if [ -f "$path/$BLUETOOTH_MODULE" ]; then
        FOUND=1
        echo "Found $BLUETOOTH_MODULE in $path"
        break
    fi
done
if [ $FOUND -eq 0 ]; then
    echo "Warning: Bluetooth module not found. Bluetooth functionality will be limited."
    echo "Available PipeWire packages:"
    apt-cache search pipewire
    echo "Available modules in standard paths:"
    find /usr/lib -name "libpipewire-module-*.so" 2>/dev/null || true
fi

# Verify PipeWire is running
echo "Verifying PipeWire setup..."
if ! run_with_timeout "run_as_user 'pw-cli info 0'" 5 "Checking PipeWire core"; then
    echo "Error: PipeWire core not responding"
    echo "PipeWire logs:"
    run_as_user "journalctl --user -u pipewire -n 50"
    exit 1
fi

echo "Installation completed successfully!"
echo "You can check the service status with: systemctl --user status audio-sync"
echo "View logs with: journalctl --user -u audio-sync -f"
echo "View PipeWire status with: pw-cli info 0"
echo "List audio devices with: pw-dump | grep Audio/"

# Verify PipeWire installation and modules
echo "Verifying PipeWire installation..."
if ! command -v pw-cli >/dev/null 2>&1; then
    echo "Error: PipeWire CLI tools not found"
    exit 1
fi

# Create necessary directories with correct permissions
mkdir -p ~/.config/systemd/user
mkdir -p ~/.local/state/wireplumber
mkdir -p ~/.local/state/pipewire
chmod 700 ~/.local/state/wireplumber
chmod 700 ~/.local/state/pipewire

# Stop existing services
systemctl --user stop pipewire pipewire-pulse wireplumber

# Clean up any existing state
rm -f /run/user/$UID/pipewire-0
rm -f /run/user/$UID/pipewire-0-manager
rm -rf ~/.local/state/pipewire/*
rm -rf ~/.local/state/wireplumber/*

# Reload systemd configuration
systemctl --user daemon-reload

# Start core services in order
echo "Starting PipeWire services..."
systemctl --user start pipewire.socket
sleep 2
systemctl --user start pipewire.service
sleep 2

# Verify PipeWire is running
if ! systemctl --user is-active pipewire.service >/dev/null 2>&1; then
    echo "Error: PipeWire failed to start"
    journalctl --user -u pipewire -n 50
    exit 1
fi

# Start additional services
systemctl --user start wireplumber.service
sleep 2

# Verify services are running
echo "Verifying service status..."
systemctl --user status pipewire wireplumber 