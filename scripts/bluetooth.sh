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

    # Configure PipeWire environment
    mkdir -p /home/$REAL_USER/.config/pipewire/media-session.d
    cat > /home/$REAL_USER/.config/pipewire/media-session.d/bluez-monitor.conf << EOF
{
 "bluez5.enable-sbc-xq": true,
 "bluez5.enable-msbc": true,
 "bluez5.enable-hw-volume": true,
 "bluez5.headset-roles": ["hsp_hs", "hsp_ag", "hfp_hf", "hfp_ag"],
 "bluez5.codecs": ["sbc_xq", "sbc", "aac"],
 "bluez5.hfphsp-backend": "native",
 "bluez5.msbc-support": true,
 "bluez5.msbc-force-mtu": 0,
 "bluez5.keep-profile": true,
 "bluez5.a2dp.ldac.quality": "auto",
 "bluez5.a2dp.aac.bitratemode": "0",
 "bluez5.a2dp.aac.quality": "1"
}
EOF
    chown -R $REAL_USER:$REAL_USER /home/$REAL_USER/.config/pipewire

    # Add user to required groups
    usermod -a -G bluetooth,audio $REAL_USER
    
    # Stop all services first
    systemctl stop bluetooth
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user stop pipewire.socket pipewire.service
    sleep 2
    
    # Kill any existing processes
    pkill -f bluetoothd || true
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" pkill -f pipewire || true
    sleep 2
    
    # Initialize Bluetooth first
    systemctl start bluetooth
    sleep 2
    
    # Set Bluetooth class and reset controller
    for i in {1..3}; do
        echo "Attempt $i: Configuring Bluetooth controller..."
        hciconfig hci0 down
        sleep 2
        hciconfig hci0 reset
        sleep 2
        hciconfig hci0 up
        sleep 2
        if hciconfig hci0 class 0x6c0404; then
            echo "Controller configured successfully"
            break
        fi
        echo "Retrying controller configuration..."
        sleep 2
    done
    
    # Verify Bluetooth is working
    if ! hciconfig hci0 | grep -q "UP RUNNING"; then
        echo "Error: Failed to initialize Bluetooth controller"
        return 1
    fi
    
    # Now start PipeWire services
    echo "Starting PipeWire services..."
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user start pipewire.socket
    sleep 2
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user start pipewire.service
    sleep 2
    
    # Verify PipeWire is running
    for i in {1..3}; do
        if sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" pw-cli info >/dev/null 2>&1; then
            echo "PipeWire is running"
            break
        fi
        echo "Attempt $i: PipeWire not responding. Restarting..."
        sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user restart pipewire
        sleep 3
    done
    
    echo "Audio system configured"
}

# Function to enable pairing mode
enable_pairing() {
    local duration=$1
    
    echo "Initializing audio system..."
    ensure_audio || {
        echo "Failed to initialize audio system"
        return 1
    }
    
    echo "Initializing Bluetooth..."
    
    # Reset Bluetooth controller and agent
    bluetoothctl power off
    sleep 2
    bluetoothctl power on
    sleep 2
    
    # Remove existing agent if any
    bluetoothctl agent off
    sleep 1
    
    # Configure Bluetooth with proper agent handling and retries
    for i in {1..3}; do
        echo "Attempt $i: Configuring Bluetooth agent..."
        
        # Try to register agent
        if bluetoothctl agent NoInputNoOutput && bluetoothctl default-agent; then
            echo "Agent registered successfully"
            break
        fi
        
        echo "Agent registration failed. Retrying..."
        bluetoothctl agent off
        sleep 2
    done
    
    # Configure discoverable and pairable modes
    bluetoothctl << EOF
discoverable on
pairable on
EOF
    
    # Verify settings with retries
    for i in {1..3}; do
        if ! bluetoothctl show | grep -q "Powered: yes"; then
            echo "Attempt $i: Bluetooth is not powered on. Retrying..."
            bluetoothctl power on
            sleep 2
        else
            break
        fi
    done
    
    for i in {1..3}; do
        if ! bluetoothctl show | grep -q "Discoverable: yes"; then
            echo "Attempt $i: Bluetooth is not discoverable. Retrying..."
            bluetoothctl discoverable on
            sleep 2
        else
            break
        fi
    done
    
    # Final verification
    if ! bluetoothctl show | grep -q "Powered: yes"; then
        echo "Error: Failed to power on Bluetooth after multiple attempts"
        return 1
    fi
    
    if ! bluetoothctl show | grep -q "Discoverable: yes"; then
        echo "Error: Failed to make Bluetooth discoverable after multiple attempts"
        return 1
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
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" systemctl --user status pipewire.socket pipewire.service --no-pager
    
    echo -e "\n=== Bluetooth Controller ==="
    bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias|UUID|Class"
    
    echo -e "\n=== Connected Devices ==="
    bluetoothctl devices Connected
    bluetoothctl info BC:D0:74:A3:4D:09
    
    echo -e "\n=== Audio Devices ==="
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" pw-cli list-objects | grep -A 2 "bluetooth"
    
    echo -e "\n=== PipeWire Audio Nodes ==="
    sudo -u $REAL_USER XDG_RUNTIME_DIR=/run/user/$USER_ID DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" pw-cli list-objects | grep -A 2 "node.name"
    
    echo -e "\n=== Bluetooth Audio Status ==="
    hcitool dev
    echo "Audio Class: $(hciconfig hci0 class | grep 'Class' | awk '{print $2}')"
    echo "Controller Status:"
    hciconfig hci0
    
    echo -e "\n=== Debug Information ==="
    echo "XDG_RUNTIME_DIR: $XDG_RUNTIME_DIR"
    echo "DBUS_SESSION_BUS_ADDRESS: $DBUS_SESSION_BUS_ADDRESS"
    echo "User ID: $USER_ID"
    echo "Real User: $REAL_USER"
    echo "User Groups: $(groups $REAL_USER)"
    echo "PipeWire Config:"
    ls -la /home/$REAL_USER/.config/pipewire/ || true
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