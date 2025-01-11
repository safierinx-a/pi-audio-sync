#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Function to ensure PulseAudio is running
ensure_pulseaudio() {
    echo "Configuring PulseAudio..."
    
    # Stop any existing PulseAudio
    pkill -9 pulseaudio || true
    sleep 2
    
    # Create/update PulseAudio system config
    mkdir -p /etc/pulse/system.pa.d
    cat > /etc/pulse/system.pa.d/bluetooth.pa << EOF
.ifexists module-bluetooth-policy.so
load-module module-bluetooth-policy
.endif

.ifexists module-bluetooth-discover.so
load-module module-bluetooth-discover
.endif

.ifexists module-switch-on-connect.so
load-module module-switch-on-connect
.endif
EOF
    
    # Ensure system-wide PulseAudio config exists
    cat > /etc/pulse/client.conf << EOF
default-server = /var/run/pulse/native
autospawn = no
daemon-binary = /bin/true
enable-shm = yes
EOF
    
    # Set permissions
    chown -R pulse:pulse /var/run/pulse
    usermod -a -G pulse-access $SUDO_USER
    usermod -a -G audio $SUDO_USER
    usermod -a -G bluetooth pulse
    usermod -a -G bluetooth $SUDO_USER
    
    # Start PulseAudio in system mode
    pulseaudio --system --daemonize
    sleep 2
    
    echo "PulseAudio configured and started"
}

# Function to enable pairing mode
enable_pairing() {
    local duration=$1
    
    echo "Initializing audio system..."
    ensure_pulseaudio
    
    echo "Initializing Bluetooth..."
    
    # Restart bluetooth service to ensure clean state
    systemctl restart bluetooth
    sleep 2
    
    # Kill any existing bluetoothctl sessions
    pkill -f bluetoothctl
    
    # Reset bluetooth controller
    bluetoothctl power off
    sleep 1
    bluetoothctl power on
    sleep 1
    
    echo "Configuring Bluetooth..."
    
    # Basic setup
    bluetoothctl set-alias "Pi Audio Sync"
    bluetoothctl discoverable-timeout $duration
    bluetoothctl pairable on
    bluetoothctl discoverable on
    
    # Start agent with auto-accept
    bluetoothctl agent on
    bluetoothctl default-agent
    
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
    bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias"
    
    echo -e "\n=== Connected Devices ==="
    bluetoothctl devices Connected
    
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