#!/bin/bash
set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root"
    exit 1
fi

# Get the user who invoked sudo
SUDO_USER="${SUDO_USER:-$USER}"
if [ "$SUDO_USER" = "root" ]; then
    echo "Please run with sudo instead of as root directly"
    exit 1
fi

# Get user's ID for systemd commands
USER_ID=$(id -u $SUDO_USER)

# System diagnostics
echo "=== System Audio Diagnostics ==="
echo "Checking audio devices..."
aplay -l || echo "No ALSA devices found"
echo

echo "Checking PipeWire installation..."
which pipewire || echo "PipeWire not found"
pipewire --version || echo "Cannot get PipeWire version"
echo

echo "Checking PipeWire status..."
ps aux | grep pipewire || echo "No PipeWire processes found"
echo

echo "Checking audio groups..."
getent group audio
echo

echo "Checking PipeWire configuration directories..."
ls -la /etc/pipewire/ || echo "No system PipeWire config found"
ls -la /home/${SUDO_USER}/.config/pipewire/ || echo "No user PipeWire config found"
echo

echo "Checking Bluetooth status..."
systemctl status bluetooth || echo "Bluetooth service not running"
echo

read -p "Continue with installation? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    exit 1
fi

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y \
    python3-pip \
    python3-dbus \
    python3-gi \
    python3-aiohttp \
    python3-numpy \
    pipewire \
    pipewire-bin \
    pipewire-audio-client-libraries \
    libpipewire-0.3-dev \
    libspa-0.2-dev \
    wireplumber \
    bluez \
    bluez-tools \
    alsa-utils \
    libasound2-dev \
    portaudio19-dev \
    python3-dev \
    libdbus-1-dev \
    libdbus-glib-1-dev \
    libgirepository1.0-dev \
    gir1.2-gtk-3.0

# Install Python packages that aren't available in Debian
echo "Installing Python packages..."
pip3 install --break-system-packages \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    python-dotenv==1.0.0 \
    pydantic==2.5.2 \
    loguru==0.7.2 \
    sounddevice==0.4.6 \
    python-multipart==0.0.6 \
    python-jose==3.3.0 \
    websockets==12.0

# Create installation directory
INSTALL_DIR="/opt/pi-audio-sync"
echo "Creating installation directory at ${INSTALL_DIR}..."
mkdir -p ${INSTALL_DIR}

# Copy files
echo "Copying files..."
cp -r . ${INSTALL_DIR}/

# Create .env file if it doesn't exist
if [ ! -f ${INSTALL_DIR}/.env ]; then
    echo "Creating .env file..."
    cat > ${INSTALL_DIR}/.env << EOF
# Environment configuration
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
EOF
fi

# Set ownership
echo "Setting permissions..."
chown -R ${SUDO_USER}:${SUDO_USER} ${INSTALL_DIR}

# Configure PipeWire
echo "Configuring PipeWire..."
# Create PipeWire config directory
mkdir -p /etc/pipewire/pipewire.conf.d
mkdir -p /home/${SUDO_USER}/.config/pipewire/pipewire.conf.d

# Copy default config if it doesn't exist
if [ ! -f /etc/pipewire/pipewire.conf ]; then
    cp /usr/share/pipewire/pipewire.conf /etc/pipewire/
fi

# Set proper ownership for user PipeWire config
chown -R ${SUDO_USER}:${SUDO_USER} /home/${SUDO_USER}/.config/pipewire

# Enable and start PipeWire services for the user
echo "Enabling and starting PipeWire services..."
DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus"
sudo -E -u ${SUDO_USER} \
    XDG_RUNTIME_DIR="/run/user/$USER_ID" \
    DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
    systemctl --user enable --now pipewire.socket pipewire.service wireplumber.service

# Configure Bluetooth
echo "Configuring Bluetooth..."
# Enable and start Bluetooth service
systemctl enable --now bluetooth

# Configure Bluetooth audio
mkdir -p /etc/bluetooth
cat > /etc/bluetooth/main.conf << EOF
[General]
Name = Pi Audio Sync
Class = 0x6c0404
DiscoverableTimeout = 0
PairableTimeout = 0
FastConnectable = true
Privacy = off
JustWorksRepairing = always
MultiProfile = multiple
Experimental = true

[Policy]
AutoEnable=true
ReconnectAttempts=7
ReconnectIntervals=1,2,4,8,16,32,64

[GATT]
Cache = always
EOF

# Add user to necessary groups
usermod -a -G audio,bluetooth ${SUDO_USER}

# Install service file
echo "Installing systemd service..."
cp scripts/audio-sync.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable audio-sync

echo "Installation complete!"
echo "Please log out and log back in for group changes to take effect."
echo "After logging back in, run: sudo systemctl start audio-sync" 