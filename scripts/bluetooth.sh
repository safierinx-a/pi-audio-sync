#!/bin/bash

# Function to ensure PulseAudio is running
ensure_pulseaudio() {
    # Check if PulseAudio is running
    if ! pulseaudio --check; then
        echo "Starting PulseAudio..."
        # Kill any zombie processes
        pkill -9 pulseaudio || true
        sleep 1
        # Start PulseAudio in system mode
        pulseaudio --system --start
        sleep 2
    fi
}

# Function to enable pairing mode
enable_pairing() {
    local duration=$1
    
    echo "Initializing audio system..."
    ensure_pulseaudio
    
    echo "Initializing Bluetooth..."
    
    # Restart bluetooth service to ensure clean state
    sudo systemctl restart bluetooth
    sleep 2
    
    # Kill any existing bluetoothctl sessions
    sudo pkill -f bluetoothctl
    
    # Reset bluetooth controller
    sudo bluetoothctl power off
    sleep 1
    sudo bluetoothctl power on
    sleep 1
    
    echo "Configuring Bluetooth..."
    
    # Basic setup
    sudo bluetoothctl set-alias "Pi Audio Sync"
    sudo bluetoothctl discoverable-timeout $duration
    sudo bluetoothctl pairable on
    sudo bluetoothctl discoverable on
    
    # Ensure audio profiles are loaded
    pactl load-module module-bluetooth-policy
    pactl load-module module-bluetooth-discover
    
    # Start agent with auto-accept
    sudo bluetoothctl agent on
    sudo bluetoothctl default-agent
    
    echo "Bluetooth is ready for pairing"
    echo "Pairing will be available for $duration seconds"
    echo "Waiting for connections..."
}

# Function to get Bluetooth status
get_status() {
    echo "=== PulseAudio Status ==="
    pactl info
    
    echo -e "\n=== System Status ==="
    systemctl status bluetooth --no-pager
    
    echo -e "\n=== Bluetooth Controller ==="
    sudo bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias"
    
    echo -e "\n=== Connected Devices ==="
    sudo bluetoothctl devices Connected
    
    echo -e "\n=== Audio Devices ==="
    pactl list cards | grep -A 2 "bluez"
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