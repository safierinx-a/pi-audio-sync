#!/bin/bash

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Error: This script should not be run as root"
    echo "Please run without sudo: ./scripts/cleanup.sh"
    exit 1
fi

echo "This script will clean up PipeWire state and configuration."
echo "Your system audio will be temporarily disrupted."
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Check D-Bus session
echo "Checking D-Bus session..."
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    echo "Warning: No D-Bus session found"
    # Try to start D-Bus session
    eval $(dbus-launch --sh-syntax)
fi

# Check systemd user session
echo "Checking systemd user session..."
if ! systemctl --user is-active systemd-logind.service >/dev/null 2>&1; then
    echo "Warning: systemd user session not active"
    loginctl enable-linger "$USER"
    export XDG_RUNTIME_DIR="/run/user/$UID"
fi

# Backup existing config
echo "Backing up existing PipeWire config..."
if [ -d ~/.config/pipewire ]; then
    mv ~/.config/pipewire ~/.config/pipewire.bak
fi

# Stop services gracefully
echo "Stopping PipeWire services..."
systemctl --user stop pipewire pipewire-pulse wireplumber
sleep 2

# Clear state files but preserve configs
echo "Clearing PipeWire state..."
rm -rf ~/.local/state/pipewire/*
rm -rf ~/.local/state/wireplumber/*

# Ensure D-Bus is running
echo "Starting D-Bus if needed..."
if ! pgrep -x dbus-daemon >/dev/null; then
    dbus-daemon --session --address="unix:path=$XDG_RUNTIME_DIR/bus" --nofork --nopidfile --syslog-only &
    sleep 2
fi

# Restart services
echo "Restarting PipeWire services..."
systemctl --user daemon-reload
systemctl --user start pipewire.service
sleep 2
systemctl --user start wireplumber.service
sleep 2
systemctl --user start pipewire-pulse.service

# Check service status
echo "Checking service status..."
systemctl --user status pipewire wireplumber pipewire-pulse

echo "PipeWire cleanup complete. If you experience issues, your backup is at ~/.config/pipewire.bak"
echo "To restore: mv ~/.config/pipewire.bak ~/.config/pipewire" 