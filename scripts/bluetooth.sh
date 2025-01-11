#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Function to ensure audio system is ready
ensure_audio() {
    echo "Setting up audio system..."
    
    # Stop any existing audio services
    systemctl --user stop pulseaudio.service pulseaudio.socket || true
    systemctl --global disable pulseaudio.service pulseaudio.socket || true
    pkill -9 pulseaudio || true
    sleep 2
    
    # Enable PipeWire services
    systemctl --user enable pipewire pipewire-pulse
    systemctl --user start pipewire pipewire-pulse
    sleep 2
    
    # Configure Bluetooth audio
    mkdir -p /etc/bluetooth
    cat > /etc/bluetooth/main.conf << EOF
[General]
Class = 0x41C
DiscoverableTimeout = 0
PairableTimeout = 0
EOF

    # Add user to required groups
    usermod -a -G bluetooth $SUDO_USER
    usermod -a -G audio $SUDO_USER
    
    # Restart bluetooth to apply changes
    systemctl restart bluetooth
    sleep 2
    
    echo "Audio system configured"
}

# Function to enable pairing mode
enable_pairing() {
    local duration=$1
    
    echo "Initializing audio system..."
    ensure_audio
    
    echo "Initializing Bluetooth..."
    
    # Configure Bluetooth
    bluetoothctl << EOF
power on
discoverable on
pairable on
agent on
default-agent
EOF
    
    echo "Bluetooth is ready for pairing"
    echo "The device will remain discoverable indefinitely"
    echo "Waiting for connections..."
}

# Function to get status
get_status() {
    echo "=== System Services Status ==="
    systemctl status bluetooth --no-pager
    systemctl --user status pipewire pipewire-pulse --no-pager
    
    echo -e "\n=== Bluetooth Controller ==="
    bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias"
    
    echo -e "\n=== Connected Devices ==="
    bluetoothctl devices Connected
    
    echo -e "\n=== Audio Devices ==="
    pw-cli list-objects | grep -A 2 "bluetooth"
}

# Handle command line arguments
case "$1" in
    "enable")
        enable_pairing "${2:-60}"
        ;;
    "status")
        get_status
        ;;
    *)
        echo "Usage: $0 {enable [duration]|status}"
        echo "  enable [duration]: Enable pairing mode (default 60 seconds)"
        echo "  status: Show current Bluetooth status and connections"
        exit 1
        ;;
esac 