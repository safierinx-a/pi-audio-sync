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
    USER_ID=$(id -u $REAL_USER)
    
    # Set up D-Bus environment
    export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus"
    export XDG_RUNTIME_DIR="/run/user/$USER_ID"
    
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

[Policy]
AutoEnable=true
ReconnectAttempts=7
ReconnectIntervals=1,2,4,8,16,32,64
EOF

    # Configure PipeWire environment
    mkdir -p /home/$REAL_USER/.config/pipewire/media-session.d
    cat > /home/$REAL_USER/.config/pipewire/media-session.d/bluez-monitor.conf << EOF
{
 "bluez5.enable-sbc-xq": true,
 "bluez5.enable-msbc": true,
 "bluez5.enable-hw-volume": true,
 "bluez5.headset-roles": ["hsp_hs", "hsp_ag", "hfp_hf", "hfp_ag"],
 "bluez5.codecs": ["sbc_xq", "sbc", "aac"]
}
EOF
    chown -R $REAL_USER:$REAL_USER /home/$REAL_USER/.config/pipewire

    # Add user to required groups
    usermod -a -G bluetooth $REAL_USER
    usermod -a -G audio $REAL_USER
    
    # Stop all services and sockets
    systemctl stop bluetooth
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user stop pipewire.socket pipewire-pulse.socket pipewire.service pipewire-pulse.service
    sleep 2
    
    # Start services in correct order
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user start pipewire.socket
    sleep 1
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user start pipewire-pulse.socket
    sleep 1
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user start pipewire.service
    sleep 1
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user start pipewire-pulse.service
    sleep 2
    
    # Start Bluetooth after PipeWire is ready
    systemctl start bluetooth
    sleep 2
    
    # Set Bluetooth class manually
    hciconfig hci0 down
    sleep 1
    hciconfig hci0 class 0x6c0404
    hciconfig hci0 up
    sleep 1
    
    # Verify PipeWire is running
    if ! sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" pactl info >/dev/null 2>&1; then
        echo "Warning: PipeWire is not responding. Trying to restart..."
        sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user restart pipewire pipewire-pulse
        sleep 2
    fi
    
    echo "Audio system configured"
}

# Function to enable pairing mode
enable_pairing() {
    local duration=$1
    
    echo "Initializing audio system..."
    ensure_audio
    
    echo "Initializing Bluetooth..."
    
    # Reset Bluetooth controller
    bluetoothctl power off
    sleep 2
    bluetoothctl power on
    sleep 2
    
    # Configure Bluetooth
    bluetoothctl << EOF
agent on
default-agent
discoverable on
pairable on
EOF
    
    # Verify settings
    if ! bluetoothctl show | grep -q "Powered: yes"; then
        echo "Error: Bluetooth is not powered on. Retrying..."
        bluetoothctl power on
        sleep 2
    fi
    
    if ! bluetoothctl show | grep -q "Discoverable: yes"; then
        echo "Error: Bluetooth is not discoverable. Retrying..."
        bluetoothctl discoverable on
        sleep 2
    fi
    
    echo "Bluetooth is ready for pairing"
    echo "The device will remain discoverable indefinitely"
    echo "Waiting for connections..."
}

# Function to get status
get_status() {
    # Get the actual username and ID
    REAL_USER=$(who | awk '{print $1}' | head -n1)
    USER_ID=$(id -u $REAL_USER)
    export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus"
    export XDG_RUNTIME_DIR="/run/user/$USER_ID"
    
    echo "=== System Services Status ==="
    systemctl status bluetooth --no-pager
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user status pipewire.socket pipewire-pulse.socket pipewire.service pipewire-pulse.service --no-pager
    
    echo -e "\n=== Bluetooth Controller ==="
    bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias|UUID|Class"
    
    echo -e "\n=== Connected Devices ==="
    bluetoothctl devices Connected
    bluetoothctl info BC:D0:74:A3:4D:09
    
    echo -e "\n=== Audio Devices ==="
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" pw-cli list-objects | grep -A 2 "bluetooth"
    
    echo -e "\n=== PipeWire Audio Sinks ==="
    sudo -u $REAL_USER DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" pactl list sinks short
    
    echo -e "\n=== Bluetooth Audio Status ==="
    hcitool dev
    echo "Audio Class: $(hciconfig hci0 class | grep 'Class' | awk '{print $2}')"
    
    echo -e "\n=== Debug Information ==="
    echo "XDG_RUNTIME_DIR: $XDG_RUNTIME_DIR"
    echo "DBUS_SESSION_BUS_ADDRESS: $DBUS_SESSION_BUS_ADDRESS"
    echo "User ID: $USER_ID"
    echo "Real User: $REAL_USER"
    ls -la $XDG_RUNTIME_DIR/pulse || true
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