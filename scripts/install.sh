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

# System Dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-dbus \
    python3-gi \
    python3-aiohttp \
    pipewire \
    pipewire-audio-client-libraries \
    pipewire-pulse \
    wireplumber \
    bluetooth \
    bluez \
    bluez-tools

# Install Python packages
echo "Installing Python packages..."
pip3 install --break-system-packages \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    python-dotenv==1.0.0 \
    pydantic==2.5.2 \
    loguru==0.7.2 \
    websockets==12.0

# Enable required services
echo "Enabling system services..."
systemctl --system enable bluetooth
systemctl --system start bluetooth

# Create configuration directories
echo "Setting up PipeWire configuration..."
mkdir -p /etc/pipewire
mkdir -p /home/$SUDO_USER/.config/systemd/user

# Copy configurations
echo "Copying configuration files..."
cp -r config/pipewire/* /etc/pipewire/
cp -r config/bluetooth/* /etc/bluetooth/

# Install application
echo "Installing application..."
mkdir -p /opt/pi-audio-sync
cp -r src /opt/pi-audio-sync/
cp -r config /opt/pi-audio-sync/
chown -R $SUDO_USER:$SUDO_USER /opt/pi-audio-sync

# Install service
echo "Installing service..."
cp config/systemd/audio-sync.service /home/$SUDO_USER/.config/systemd/user/
chown -R $SUDO_USER:$SUDO_USER /home/$SUDO_USER/.config

# Create log directory
echo "Setting up logging..."
mkdir -p /var/log/pi-audio-sync
chown -R $SUDO_USER:$SUDO_USER /var/log/pi-audio-sync

# Enable user services
echo "Enabling user services..."
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user daemon-reload
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user enable pipewire pipewire-pulse wireplumber
sudo -u $SUDO_USER XDG_RUNTIME_DIR=/run/user/$(id -u $SUDO_USER) systemctl --user enable audio-sync

echo "Installation complete!"
echo "Please reboot your system to start the services." 