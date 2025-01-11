#!/bin/bash

# Function to enable pairing mode
enable_pairing() {
    local duration=$1
    
    # Power on and set friendly name
    sudo bluetoothctl power on
    sudo bluetoothctl set-alias "Pi Audio Sync"
    
    # Make discoverable and pairable
    sudo bluetoothctl discoverable on
    sudo bluetoothctl pairable on
    sudo bluetoothctl discoverable-timeout $duration
    
    # Start bluetoothctl agent in the background
    (
        sudo bluetoothctl << 'EOF'
agent on
default-agent
power on
discoverable on
pairable on
EOF
    ) &

    # Wait for agent to initialize
    sleep 1
    
    # Configure audio profile
    sudo bluetoothctl << 'EOF'
menu audio
discoverable on
pairable on
quit
EOF
    
    echo "Pairing mode enabled for $duration seconds"
    echo "Device is ready for pairing"
}

# Function to get Bluetooth status
get_status() {
    echo "=== Bluetooth Status ==="
    sudo bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias"
    echo -e "\n=== Connected Devices ==="
    sudo bluetoothctl devices Connected
    echo -e "\n=== Available Profiles ==="
    sudo bluetoothctl list
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