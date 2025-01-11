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
    
    # Start bluetoothctl in the background to auto-confirm passkeys
    (sudo bluetoothctl << EOF
    agent on
    default-agent
    yes
    EOF
    ) &
    
    echo "Pairing mode enabled for $duration seconds"
}

# Function to get Bluetooth status
get_status() {
    sudo bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias"
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
        exit 1
        ;;
esac 