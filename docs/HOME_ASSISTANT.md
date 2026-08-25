# Home Assistant integration

UniFi Announcer includes a HACS-compatible custom integration under `custom_components/unifi_announcer` for Home Assistant 2026.3+.

> [!WARNING]
> Native Home Assistant support is currently a prerelease feature. For beta testing, explicitly install `v2.1.0-beta.2`; the stable `v2.0.0` release predates this integration. HACS does not normally select prereleases automatically, so enable prereleases for UniFi Announcer or select the beta version when downloading.

## Install

### HACS custom repository

1. In HACS, add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
2. Enable prereleases for UniFi Announcer or explicitly select `v2.1.0-beta.2`.
3. Install **UniFi Announcer**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → UniFi Announcer**.
6. Enter the Announcer URL, for example `http://announcer.local:8095`.
7. Enter `APP_API_KEY` if the Announcer service uses one.

### Manual

Copy `custom_components/unifi_announcer` into Home Assistant's `/config/custom_components/` directory and restart Home Assistant.

## Config flow

The UI validates the service with:

- `GET /health`
- `GET /version`
- `GET /auth/check`

No playback occurs during setup.

If the configured application API key is rejected while Home Assistant loads the integration, the entry transitions to Home Assistant's reauthentication flow rather than loading successfully with a stale key. If the Announcer service is temporarily unreachable, setup is retried instead of treating the outage as invalid configuration.

The v2.1 integration deliberately supports one UniFi Announcer config entry. This avoids ambiguous routing for the global `unifi_announcer.announce` action; deliberate multi-instance support can be added later without silently choosing the wrong server.

## Options

Use **Settings → Devices & services → UniFi Announcer → Configure** to set:

- poll interval
- default target
- default volume
- default repeat count

Changing options reloads the integration. Volume `0` is valid and remains `0` rather than falling back to a default.

## Devices and entities

Physical Smart Chimes are represented as physical Ubiquiti devices using their stable Protect chime IDs. Logical groups attach to the UniFi Announcer service device rather than pretending to be physical hardware.

For each configured physical chime the integration creates:

- `notify` — standard text announcements
- `media_player` — `play_media` for text and existing presets
- buzzer button
- assigned-default button
- preset selector
- play-selected-preset button
- queue-depth sensor
- last-disposition sensor

For each configured logical group it creates the same playback controls plus last disposition, but **does not create a queue-depth sensor**. Queue depth is a physical-chime concept; v2.1 intentionally avoids presenting a fake group aggregate.

If `CHIMES_CONFIG` or `GROUPS_CONFIG` changes after Home Assistant has loaded the integration, reload/restart the integration so entity topology is rebuilt.

## Standard announcements

Select the actual notify entity from Home Assistant's UI; generated entity IDs can vary with device names.

```yaml
action: notify.send_message
target:
  entity_id: notify.unifi_announcer_kitchen_announcements
data:
  message: "Dinner is ready"
```

The notify entity uses the integration's configured defaults for volume/repeat behavior.

## Advanced announcement action

Use the native service/action when an automation needs per-call controls:

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
  entity_id: media_player.kitchen_announcer
data:
  media_content_type: text
  media_content_id: "The laundry is finished"
```

### Preset

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen_announcer
data:
  media_content_type: unifi-announcer/preset
  media_content_id: package-delivered
```

Native `tts.speak` / `media-source://` binary ingestion is intentionally deferred to v2.2 so v2.1 can remain a thin client over the existing, proven announcement stack.

## Availability

The integration polls lightweight state. A temporary Piper outage does not make buzzer/default/preset controls unavailable when Protect itself remains reachable.

## Diagnostics

Home Assistant diagnostics include safe service version, health, chime/group names, preset names, queue depths, and configuration metadata. API keys and credentials are redacted; raw Protect responses and support logs are not included.

The Version sensor reports the semantic UniFi Announcer version. The container git SHA remains available as diagnostic/build metadata rather than replacing the version number.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Integration not offered after HACS install | Stable `v2.0.0` was installed | Enable prereleases/select `v2.1.0-beta.2`, reinstall, restart HA |
| Invalid API key / reauthentication requested | `APP_API_KEY` changed or mismatches | Enter the current application key in the reauth flow |
| Cannot connect | Home Assistant cannot reach the Docker host/port | Verify the Announcer URL and LAN routing |
| No preset options | `/presets` failed or state is stale | Verify `/presets`, then reload the integration |
| TTS unavailable but buttons work | Piper is unavailable | Check the Piper endpoint separately |
| Group has no queue sensor | Intentional in v2.1 | Inspect member-chime queue sensors |
| Newly configured chime/group is absent | Entity topology predates config change | Reload/restart the integration |

Keep UniFi Announcer on a trusted LAN or behind a VPN/authenticated reverse proxy. Do not expose it directly to the public internet.
