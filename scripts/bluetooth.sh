#!/bin/bash

# Function to enable pairing mode
enable_pairing() {
    duration=$1
    
    # Power on Bluetooth if not already on
    bluetoothctl power on
    
    # Set friendly name
    bluetoothctl system-alias "Pi Audio Sync"
    
    # Make discoverable and pairable
    bluetoothctl discoverable on
    bluetoothctl pairable on
    
    # Set discoverable timeout
    bluetoothctl discoverable-timeout $duration
    
    echo "Bluetooth pairing enabled for $duration seconds"
}

# Function to get Bluetooth status
get_status() {
    bluetoothctl show | grep -E "Powered:|Discoverable:|Pairable:|Alias:"
}

# Handle command line arguments
case "$1" in
    "enable")
        enable_pairing "${2:-60}"  # Default 60 seconds if not specified
        ;;
    "status")
        get_status
        ;;
    *)
        echo "Usage: $0 {enable [duration]|status}"
        exit 1
        ;;
esac 