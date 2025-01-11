#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Function to ensure audio system is ready
ensure_audio() {
    echo "Setting up audio system..."
    
    # Get the actual username (not sudo user)
    REAL_USER=$(who | awk '{print $1}' | head -n1)
    
    # Configure Bluetooth audio
    mkdir -p /etc/bluetooth
    cat > /etc/bluetooth/main.conf << EOF
[General]
Class = 0x41C
DiscoverableTimeout = 0
PairableTimeout = 0

[Policy]
AutoEnable=true
EOF

    # Add user to required groups
    usermod -a -G bluetooth $REAL_USER
    usermod -a -G audio $REAL_USER
    
    # Restart bluetooth to apply changes
    systemctl restart bluetooth
    sleep 2
    
    # Ensure PipeWire is running for the user
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) systemctl --user restart pipewire pipewire-pulse
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
trust BC:D0:74:A3:4D:09
EOF
    
    echo "Bluetooth is ready for pairing"
    echo "The device will remain discoverable indefinitely"
    echo "Waiting for connections..."
}

# Function to get status
get_status() {
    # Get the actual username
    REAL_USER=$(who | awk '{print $1}' | head -n1)
    
    echo "=== System Services Status ==="
    systemctl status bluetooth --no-pager
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) systemctl --user status pipewire pipewire-pulse --no-pager
    
    echo -e "\n=== Bluetooth Controller ==="
    bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias"
    
    echo -e "\n=== Connected Devices ==="
    bluetoothctl devices Connected
    
    echo -e "\n=== Audio Devices ==="
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) pw-cli list-objects | grep -A 2 "bluetooth"
    
    echo -e "\n=== PipeWire Audio Sinks ==="
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) pactl list sinks short
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