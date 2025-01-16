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
    
    echo "$message..."
    timeout "$timeout" bash -c "$cmd" || {
        echo "Command timed out after ${timeout}s: $cmd"
        return 1
    }
}

function run_as_user() {
    local cmd="$1"
    su - "$SUDO_USER" -c "$cmd"
}

function is_package_installed() {
    dpkg -l "$1" &> /dev/null
}

function run_systemd_user() {
    local cmd="$1"
    echo "Debug: Setting up systemd user environment..."
    echo "Debug: SUDO_USER=$SUDO_USER"
    echo "Debug: User ID=$(id -u $SUDO_USER)"
    
    # Enable lingering for the user
    echo "Debug: Enabling lingering..."
    loginctl enable-linger "$SUDO_USER"
    
    # Set up runtime directory
    echo "Debug: Setting up runtime directory..."
    export XDG_RUNTIME_DIR="/run/user/$(id -u $SUDO_USER)"
    mkdir -p "$XDG_RUNTIME_DIR"
    chown "$SUDO_USER:$SUDO_USER" "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
    
    # Export DBUS session address
    echo "Debug: Setting up DBUS session..."
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u $SUDO_USER)/bus"
    export DBUS_SESSION_BUS_ADDRESS
    
    # Run the command with full environment
    echo "Debug: Running command: $cmd"
    su - "$SUDO_USER" -c "export XDG_RUNTIME_DIR='$XDG_RUNTIME_DIR'; export DBUS_SESSION_BUS_ADDRESS='$DBUS_SESSION_BUS_ADDRESS'; systemctl --user $cmd"
    
    local result=$?
    if [ $result -ne 0 ]; then
        echo "Debug: Command failed with exit code $result"
        echo "Debug: Systemd status:"
        systemctl --user status || true
        echo "Debug: Journal output:"
        journalctl -n 50 --no-pager || true
    fi
    return $result
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
    pipewire-bin
    pipewire-tests
    pipewire-alsa
    pipewire-module-bluetooth
    libpipewire-0.3-*
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
    apt-get install --reinstall pipewire pipewire-bin libpipewire-0.3-* || {
        echo "Failed to install PipeWire modules. Please check your system's package repositories."
        exit 1
    }
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