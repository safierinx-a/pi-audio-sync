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

echo "Checking PulseAudio installation..."
which pulseaudio || echo "PulseAudio not found"
pulseaudio --version || echo "Cannot get PulseAudio version"
echo

echo "Checking PulseAudio status..."
ps aux | grep pulseaudio || echo "No PulseAudio processes found"
echo

echo "Checking audio groups..."
getent group audio
getent group pulse
getent group pulse-access
echo

echo "Checking PulseAudio configuration directories..."
ls -la /etc/pulse/ || echo "No system PulseAudio config found"
ls -la /home/${SUDO_USER}/.config/pulse/ || echo "No user PulseAudio config found"
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
# System-wide configuration
cp ${INSTALL_DIR}/config/pulse/default.pa /etc/pulse/default.pa
cp ${INSTALL_DIR}/config/pulse/daemon.conf /etc/pulse/daemon.conf

# User-specific configuration
USER_PULSE_DIR="/home/${SUDO_USER}/.config/pulse"
echo "Setting up user PulseAudio directory at ${USER_PULSE_DIR}..."
mkdir -p ${USER_PULSE_DIR}
cp ${INSTALL_DIR}/config/pulse/default.pa ${USER_PULSE_DIR}/
cp ${INSTALL_DIR}/config/pulse/daemon.conf ${USER_PULSE_DIR}/
chown -R ${SUDO_USER}:${SUDO_USER} ${USER_PULSE_DIR}

# Make sure PulseAudio can start for the user
usermod -a -G audio ${SUDO_USER}
usermod -a -G pulse ${SUDO_USER}
usermod -a -G pulse-access ${SUDO_USER}

# Restart PulseAudio for the user
echo "Restarting PulseAudio..."
su - ${SUDO_USER} -c "pulseaudio -k || true"  # Kill existing PulseAudio
sleep 2  # Give it time to fully stop
su - ${SUDO_USER} -c "pulseaudio --start -D"  # Start PulseAudio as daemon

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