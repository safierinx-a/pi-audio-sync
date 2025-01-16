#!/bin/bash

echo "This script will clean up PipeWire state and configuration."
echo "Your system audio will be temporarily disrupted."
read -p "Press Enter to continue or Ctrl+C to cancel..."

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

# Restart services
echo "Restarting PipeWire services..."
systemctl --user daemon-reload
systemctl --user start pipewire pipewire-pulse wireplumber

echo "PipeWire cleanup complete. If you experience issues, your backup is at ~/.config/pipewire.bak"
echo "To restore: mv ~/.config/pipewire.bak ~/.config/pipewire" 