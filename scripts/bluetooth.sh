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
Name = Pi Audio Sync
Class = 0x240404
DiscoverableTimeout = 0
PairableTimeout = 0
FastConnectable = true
Privacy = off

[Policy]
AutoEnable=true
ReconnectAttempts=7
ReconnectIntervals=1,2,4,8,16,32,64
EOF

    # Configure Bluetooth audio profiles
    mkdir -p /etc/bluetooth/audio
    cat > /etc/bluetooth/audio/config << EOF
[General]
Enable=Source,Sink,Media,Socket
Disable=Gateway,Control,Headset

[A2DP]
SBCSources=1
SBCSinks=1
AACPSources=1
AACPSinks=1
EOF

    # Add user to required groups
    usermod -a -G bluetooth $REAL_USER
    usermod -a -G audio $REAL_USER
    
    # Restart bluetooth to apply changes
    systemctl stop bluetooth
    sleep 2
    systemctl start bluetooth
    sleep 2
    
    # Ensure PipeWire is running for the user
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) systemctl --user restart pipewire pipewire-pulse
    sleep 2
    
    # Load Bluetooth modules
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) pactl load-module module-bluetooth-policy
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) pactl load-module module-bluetooth-discover
    
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
power off
sleep 2
power on
sleep 2
discoverable on
pairable on
agent on
default-agent
EOF
    
    # Set audio profile
    echo "Setting up audio profiles..."
    bluetoothctl << EOF
discoverable on
pairable on
EOF
    
    # Verify power state
    if ! bluetoothctl show | grep -q "Powered: yes"; then
        echo "Error: Bluetooth is not powered on. Retrying..."
        bluetoothctl power on
        sleep 2
    fi
    
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
    bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias|UUID|Class"
    
    echo -e "\n=== Connected Devices ==="
    bluetoothctl devices Connected
    
    echo -e "\n=== Audio Devices ==="
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) pw-cli list-objects | grep -A 2 "bluetooth"
    
    echo -e "\n=== PipeWire Audio Sinks ==="
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER) pactl list sinks short
    
    echo -e "\n=== Bluetooth Audio Status ==="
    hcitool dev
    echo "Audio Class: $(hciconfig hci0 class | grep 'Class' | awk '{print $2}')"
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