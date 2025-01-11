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

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y \
    python3-pip \
    python3-venv \
    pulseaudio \
    alsa-utils \
    libasound2-dev \
    portaudio19-dev \
    python3-dev

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

# Configure PulseAudio
echo "Configuring PulseAudio..."
cp ${INSTALL_DIR}/config/pulse/default.pa /etc/pulse/default.pa
cp ${INSTALL_DIR}/config/pulse/daemon.conf /etc/pulse/daemon.conf

# Restart PulseAudio for the user
echo "Restarting PulseAudio..."
su - ${SUDO_USER} -c "pulseaudio -k || true"  # Kill existing PulseAudio
su - ${SUDO_USER} -c "pulseaudio --start"     # Start PulseAudio

# Copy and enable systemd service
echo "Setting up systemd service..."
cp ${INSTALL_DIR}/scripts/audio-sync.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable audio-sync@${SUDO_USER}.service

# Create environment file if it doesn't exist
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    echo "Creating environment file..."
    cp ${INSTALL_DIR}/.env.example ${INSTALL_DIR}/.env
    chown ${SUDO_USER}:${SUDO_USER} ${INSTALL_DIR}/.env
fi

echo "Installation complete!"
echo "Please edit ${INSTALL_DIR}/.env to configure your settings"
echo "Then start the service with: sudo systemctl start audio-sync@${SUDO_USER}" 