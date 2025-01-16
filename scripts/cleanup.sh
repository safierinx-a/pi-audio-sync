#!/bin/bash

echo "This script will clean up PipeWire state and configuration."
echo "Your system audio will be temporarily disrupted."
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Stop services gracefully
echo "Stopping PipeWire services..."
systemctl --user stop pipewire pipewire-pulse wireplumber
sleep 2

# Clear state files
echo "Clearing PipeWire state..."
rm -rf ~/.local/state/pipewire
rm -rf ~/.local/state/wireplumber

# Start services in correct order
echo "Starting PipeWire services..."
systemctl --user daemon-reload
systemctl --user start pipewire.socket
sleep 2
systemctl --user start pipewire.service
sleep 2
systemctl --user start wireplumber.service
sleep 2
systemctl --user start pipewire-pulse.socket
sleep 2
systemctl --user start pipewire-pulse.service

echo "PipeWire cleanup complete."
echo "Check status with: systemctl --user status pipewire wireplumber pipewire-pulse" 