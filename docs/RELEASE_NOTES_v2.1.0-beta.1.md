# UniFi Announcer v2.1.0-beta.1

This prerelease adds the first public usability layer on top of the existing UniFi Announcer service without changing the core Protect playback path.

## Highlights

- HACS-compatible Home Assistant custom integration
- UI-based Home Assistant config flow, reauthentication, and options
- Typed async REST client
- Per-chime and group notify entities
- Native `unifi_announcer.announce` action for advanced controls
- Buzzer, default-play, preset select, and preset-play controls
- Text and preset `media_player.play_media` support
- Diagnostics with credential redaction
- Optional embedded MCP 2.0 Streamable HTTP endpoint at `/mcp`
- Dedicated MCP bearer key and LAN Host allowlist
- Read-only and playback MCP tools that reuse `AnnouncementDispatcher`
- Harmless `GET /auth/check` endpoint for client authentication validation

## Scope

All playback still flows through the existing UniFi Announcer dispatcher and Protect backend. Home Assistant and MCP are optional interfaces; neither contains a second playback implementation or receives UniFi device credentials.

Native Home Assistant `tts.speak`, binary media ingestion, and SSE event consumption are intentionally deferred to v2.2.

## Validation before beta

- 186 tests passed
- Ruff passed
- Python compile checks passed
- JSON manifests validated
- Docker Compose validated
- Docker build passed
- GitHub Actions passed on the merged v2.1 implementation

## Beta validation goals

Please focus testing on:

- HACS custom-repository installation and upgrades
- Home Assistant config flow and reauthentication
- entity discovery for physical chimes and configured groups
- `notify.send_message`
- `unifi_announcer.announce`
- buzzer/default/preset controls
- text and preset `media_player.play_media`
- Home Assistant unload/reload behavior
- MCP discovery from Hermes or another Streamable HTTP MCP client
- MCP status/list and playback tools
- behavior when one chime or Piper is unavailable

## Known limitations

- `tts.speak` is not yet supported as a native media-source workflow.
- The media player intentionally does not advertise pause, seek, streaming, or fake playback telemetry.
- MCP is disabled by default and intended for trusted LAN/VPN use only.
- UniFi Protect interfaces used by this project are undocumented and may change with firmware or Protect updates.

## Upgrade notes

Existing Docker data, cached tracks, presets, queueing, REST, MQTT, and Protect-rule behavior are intended to remain compatible with v2.0. Existing deployments should keep their current data volume during the upgrade.
