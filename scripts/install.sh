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
    python3-venv \
    python3-dbus \
    python3-gi \
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
    gir1.2-gtk-3.0 \
    wireplumber \
    pipewire-media-session \
    bluetooth-tools \
    pulseaudio-module-bluetooth

# Create installation directory
INSTALL_DIR="/opt/pi-audio-sync"
echo "Creating installation directory at ${INSTALL_DIR}..."
mkdir -p ${INSTALL_DIR}

# Copy files
echo "Copying files..."
cp -r . ${INSTALL_DIR}/

# Set ownership
echo "Setting permissions..."
chown -R ${SUDO_USER}:${SUDO_USER} ${INSTALL_DIR}

# Create virtual environment
echo "Creating Python virtual environment..."
su - ${SUDO_USER} -c "cd ${INSTALL_DIR} && python3 -m venv venv"
su - ${SUDO_USER} -c "cd ${INSTALL_DIR} && ./venv/bin/pip install -r requirements.txt"

# Configure PipeWire
echo "Configuring PipeWire..."
# Create PipeWire config directory
mkdir -p /etc/pipewire/pipewire.conf.d
mkdir -p /home/${SUDO_USER}/.config/pipewire/pipewire.conf.d

# Copy default config if it doesn't exist
if [ ! -f /etc/pipewire/pipewire.conf ]; then
    cp /usr/share/pipewire/pipewire.conf /etc/pipewire/
fi

# Enable PipeWire service for the user
systemctl --user enable pipewire.socket
systemctl --user enable pipewire.service
systemctl --user enable wireplumber.service

# Add user to necessary groups
usermod -a -G audio,bluetooth ${SUDO_USER}

echo "Installation complete!"
echo "Please log out and log back in for group changes to take effect." 