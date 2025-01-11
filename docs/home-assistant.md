# Home Assistant Integration

This guide explains how to integrate Pi Audio Sync with Home Assistant.

## Configuration

Add the following to your Home Assistant `configuration.yaml`:

```yaml
rest:
  - resource: http://pi-audio-sync:8000/api/v1/hass/states
    scan_interval: 5
    sensor:
      - name: "Pi Audio System"
        value_template: "{{ value_json | length }} devices connected"
        json_attributes_path: "$[0].attributes"
        json_attributes:
          - friendly_name
          - volume_level
          - is_volume_muted
          - source

media_player:
  - platform: rest
    name: Pi Audio System
    device_class: speaker
    state_resource: http://pi-audio-sync:8000/api/v1/status
    state_value_template: "{{ 'on' if value_json.healthy else 'off' }}"
    volume_resource: http://pi-audio-sync:8000/api/v1/devices/{}/volume
    volume_command: PUT
    mute_resource: http://pi-audio-sync:8000/api/v1/devices/{}/mute
    unmute_resource: http://pi-audio-sync:8000/api/v1/devices/{}/unmute
```

## Features

- **Device Discovery**: Automatically discovers and creates entities for each audio output
- **Volume Control**: Control volume for each device individually
- **Mute Control**: Mute/unmute each device
- **Status Monitoring**: Monitor device health and connection status
- **Combined Sink**: Shows if devices are playing in sync

## Automations

Example automations you can add:

```yaml
# Auto-recover on device failure
automation:
  - alias: "Audio System Recovery"
    trigger:
      platform: state
      entity_id: media_player.pi_audio_system
      to: "off"
    action:
      - service: homeassistant.restart
        target:
          entity_id: media_player.pi_audio_system

# Volume sync between devices
automation:
  - alias: "Sync Audio Volumes"
    trigger:
      platform: state
      entity_id: media_player.pi_audio_builtin
      attribute: volume_level
    action:
      - service: media_player.volume_set
        target:
          entity_id: media_player.pi_audio_usb
        data:
          volume_level: "{{ trigger.to_state.attributes.volume_level }}"
```

## Troubleshooting

1. **No Devices Showing**:

   - Check if Pi Audio Sync service is running
   - Verify network connectivity
   - Check if devices are properly connected

2. **Volume Control Not Working**:

   - Ensure proper permissions for PulseAudio
   - Check API endpoints are accessible

3. **Devices Show as Unavailable**:
   - Check physical connections
   - Verify PulseAudio service is running
   - Check system logs for errors

## API Endpoints

All endpoints are available at `http://pi-audio-sync:8000/api/v1/`:

- `GET /status` - Overall system status
- `GET /devices/{id}` - Individual device status
- `PUT /devices/{id}/volume` - Set device volume
- `POST /devices/{id}/mute` - Mute device
- `POST /devices/{id}/unmute` - Unmute device
- `GET /hass/states` - Home Assistant state data
