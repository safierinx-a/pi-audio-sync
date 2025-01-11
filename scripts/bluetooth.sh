#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Function to ensure PulseAudio is running
ensure_pulseaudio() {
    echo "Configuring PulseAudio..."
    
    # Stop any existing PulseAudio and disable user service
    systemctl --global disable pulseaudio.service pulseaudio.socket || true
    pkill -9 pulseaudio || true
    sleep 2
    
    # Create system service file for PulseAudio
    cat > /etc/systemd/system/pulseaudio.service << EOF
[Unit]
Description=PulseAudio Sound System
After=network.target bluetooth.service
Wants=bluetooth.service

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=pulse
Group=pulse
RuntimeDirectory=pulse
RuntimeDirectoryMode=0755
ExecStart=/usr/bin/pulseaudio --system --realtime --disallow-exit --no-cpu-limit --log-target=journal
Restart=always
RestartSec=30
EOF

    # Create required directories with proper permissions
    mkdir -p /var/run/pulse
    mkdir -p /var/lib/pulse
    chown -R pulse:pulse /var/run/pulse
    chown -R pulse:pulse /var/lib/pulse
    
    # Configure system-wide PulseAudio
    cat > /etc/pulse/system.pa << EOF
#!/usr/bin/pulseaudio -nF
.fail

### Load core protocols
load-module module-native-protocol-unix auth-cookie-enabled=0 auth-anonymous=1
load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1;192.168.0.0/16;172.16.0.0/12;10.0.0.0/8

### Bluetooth support
.ifexists module-bluetooth-policy.so
load-module module-bluetooth-policy auto_switch=2
.endif

.ifexists module-bluetooth-discover.so
load-module module-bluetooth-discover headset=auto
.endif

### Hardware support
load-module module-udev-detect
load-module module-alsa-card
load-module module-switch-on-connect

### Allow pulse access through local system
load-module module-native-protocol-unix auth-cookie-enabled=0 auth-anonymous=1 socket=/var/run/pulse/native

### Automatically switch to newly-connected devices
load-module module-switch-on-connect

### Allow direct connection from local system
load-module module-native-protocol-tcp auth-anonymous=1
EOF

    chmod 644 /etc/pulse/system.pa
    
    # Configure client settings
    cat > /etc/pulse/client.conf << EOF
default-server = unix:/var/run/pulse/native
autospawn = no
daemon-binary = /bin/true
enable-shm = yes
EOF

    chmod 644 /etc/pulse/client.conf
    
    # Configure daemon settings for better audio
    cat > /etc/pulse/daemon.conf << EOF
resample-method = speex-float-5
default-sample-format = s16le
default-sample-rate = 44100
alternate-sample-rate = 48000
default-sample-channels = 2
default-channel-map = front-left,front-right
default-fragments = 4
default-fragment-size-msec = 25
enable-remixing = yes
enable-lfe-remixing = no
high-priority = yes
nice-level = -11
realtime-scheduling = yes
realtime-priority = 9
exit-idle-time = -1
flat-volumes = no
EOF

    chmod 644 /etc/pulse/daemon.conf
    
    # Set permissions
    usermod -a -G pulse-access $SUDO_USER
    usermod -a -G audio $SUDO_USER
    usermod -a -G bluetooth pulse
    usermod -a -G bluetooth $SUDO_USER
    
    # Restart and enable the service
    systemctl daemon-reload
    systemctl enable pulseaudio.service
    systemctl restart pulseaudio.service
    sleep 2
    
    echo "PulseAudio configured and started as system service"
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
    
    # Configure Bluetooth audio profiles
    bluetoothctl << EOF
agent on
default-agent
power on
discoverable on
pairable on
EOF
    
    echo "Bluetooth is ready for pairing"
    echo "Pairing will be available for $duration seconds"
    echo "Waiting for connections..."
}

# Function to get Bluetooth status
get_status() {
    echo "=== PulseAudio Status ==="
    LANG=C pactl info
    
    echo -e "\n=== PulseAudio Modules ==="
    LANG=C pactl list modules short
    
    echo -e "\n=== System Status ==="
    systemctl status bluetooth pulseaudio --no-pager
    
    echo -e "\n=== Bluetooth Controller ==="
    bluetoothctl show | grep -E "Name|Powered|Discoverable|Pairable|Alias"
    
    echo -e "\n=== Connected Devices ==="
    bluetoothctl devices Connected
    
    echo -e "\n=== Audio Devices ==="
    LANG=C pactl list cards | grep -A 2 "bluez"
    
    echo -e "\n=== Audio Sinks ==="
    LANG=C pactl list sinks short
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