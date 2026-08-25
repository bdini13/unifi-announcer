# Home Assistant integration

UniFi Announcer includes a HACS-compatible custom integration under `custom_components/unifi_announcer`.

## Install

### HACS custom repository

1. In HACS, add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
2. Install **UniFi Announcer**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → UniFi Announcer**.
5. Enter the Announcer URL, for example `http://announcer.local:8095`.
6. Enter `APP_API_KEY` if the Announcer service uses one.

### Manual

Copy `custom_components/unifi_announcer` into Home Assistant's `/config/custom_components/` directory and restart Home Assistant.

## Config flow

The UI validates the service with:

- `GET /health`
- `GET /version`
- `GET /auth/check`

No playback occurs during setup. A rejected key uses Home Assistant's reauthentication flow rather than requiring the integration to be deleted.

## Entities

For each configured physical chime and group, the integration creates appropriate entities:

- `notify` — standard text announcements
- `media_player` — `play_media` for text and existing presets
- buzzer button
- assigned-default button
- preset selector
- play-selected-preset button
- queue-depth and last-disposition sensors

Groups are logical targets and attach to the Announcer service device rather than pretending to be physical devices.

## Standard announcements

```yaml
action: notify.send_message
target:
  entity_id: notify.unifi_announcer_kitchen
data:
  message: "Dinner is ready"
```

The notify entity uses the integration's configured defaults for volume/repeat behavior.

## Advanced announcement action

Use the native service when an automation needs per-call controls:

```yaml
action: unifi_announcer.announce
data:
  message: "Dinner is ready"
  target: kitchen
  volume: 45
  repeat_times: 1
  priority: 50
  dedupe_key: dinner-ready
```

Supported fields are `message`, `target`, `volume`, `repeat_times`, `profile`, `priority`, and `dedupe_key`.

## Media player

The media player intentionally advertises only `PLAY_MEDIA`. Smart Chimes are not normal streaming speakers: there is no honest pause, seek, playback-position, or persistent transport state.

### Text

```yaml
action: media_player.play_media
target:
  entity_id: media_player.unifi_announcer_kitchen
data:
  media_content_type: text
  media_content_id: "The laundry is finished"
```

### Preset

```yaml
action: media_player.play_media
target:
  entity_id: media_player.unifi_announcer_kitchen
data:
  media_content_type: unifi-announcer/preset
  media_content_id: package-delivered
```

Native `tts.speak` / `media-source://` binary ingestion is intentionally deferred to v2.2 so v2.1 can remain a thin client over the existing, proven announcement stack.

## Availability

The integration polls lightweight state. A temporary Piper outage does not make buzzer/default/preset controls unavailable when Protect itself remains reachable.

## Diagnostics

Home Assistant diagnostics include safe service version, health, chime/group names, preset names, queue depths, and configuration metadata. API keys and credentials are redacted; raw Protect responses and support logs are not included.

## Troubleshooting

- **Cannot connect:** verify Home Assistant can reach the Docker host and port.
- **Invalid API key:** update the key through the reauthentication flow.
- **No preset options:** verify `/presets` returns custom ringtones and reload the integration.
- **TTS unavailable but buttons work:** check Piper separately; non-TTS controls can remain operational.

Keep UniFi Announcer on a trusted LAN or behind a VPN/authenticated reverse proxy. Do not expose it directly to the public internet.
