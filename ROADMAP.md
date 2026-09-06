# Roadmap

UniFi Announcer keeps the Docker service and `AnnouncementDispatcher` as the source of truth. Home Assistant, MCP, MQTT, REST, and local rules should remain thin interfaces over the same playback implementation.

## Stable v2.1

The v2.1 line establishes the production foundation:

- exactly two persistent service-owned dynamic TTS slots;
- bounded host-side TTS cache;
- Protect-mediated playback with fail-closed direct-slot ownership checks;
- Home Assistant HACS client with notify, buttons, selectors, sensors, and text/preset media-player actions;
- optional Streamable HTTP MCP server;
- REST, MQTT, queueing, quiet-hours policy, dedupe, and named targets/groups;
- build/version diagnostics and release validation gates.

Key stable milestones:

- **v2.1.6** — Home Assistant playback reliability when Protect's ringtone inventory lags a successful owned-slot overwrite, plus immediate HA playback-result reporting.
- **v2.1.7** — validated Protect UI onboarding for the Smart Chime's unique device password through Manual Recovery → Reveal.
- **v2.1.8** — content-aware same-boot resident TTS reuse, boot-epoch validation, durable write-ahead content invalidation, and Smart Chime reboot/reconnect safety.

v2.1.8 substantially reduces repeated-announcement request-path latency by avoiding redundant physical slot writes when content is already resident and the current Smart Chime boot remains proven. New-content latency is still dominated by the device's physical ringtone write.

## Prioritized expansion roadmap

The next development work is ordered by user value and available validation hardware. Features that depend on undocumented Protect behavior remain experimental until they pass model-specific automated and physical validation.

### 1. Camera-speaker TTS

- extend Announcer targets to compatible Protect cameras through controller-minted talkback sessions;
- discover and enforce each camera's advertised codec, sample rate, channel count, and transport settings;
- route generated speech through the existing dispatcher, queueing, quiet-hours, priority, and group model rather than creating a second playback stack;
- fail closed for unsupported camera models and require physical audibility before claiming support.

### 2. Native Home Assistant media ingestion

- native `tts.speak` support;
- `media-source://` ingestion;
- bounded binary media ingestion through the same validated dispatcher and target backends;
- clear format, duration, and size validation before media reaches a Protect device.

### 3. Diagnostics and compatibility

- redacted diagnostic bundles covering queue state, slot synchronization, resident-content lifecycle state, and release/build identity;
- per-stage latency reporting that distinguishes Home Assistant dispatch, synthesis/cache work, device preflight, upload, synchronization, and playback acceptance;
- firmware compatibility warnings based on capability discovery rather than optimistic version assumptions;
- compatibility reports across additional Protect, Smart Chime, and camera firmware versions.

### Hardware-gated: Protect AI Horn and AI Speaker

AI Horn and AI Speaker support is a future expansion candidate, not a current compatibility claim. Development requires acquiring representative hardware first. Once hardware is available, research should prefer UniFi's official speaker, siren, Alarm Manager, and talkback APIs, with private endpoints considered only for missing capabilities. Support must remain disabled until physical playback, grouping, volume, interruption, failure, and recovery behavior are validated.

### Additional backlog

- friendly creation, editing, and removal of user-facing spoken presets;
- display names stored separately from spoken text;
- automatic Home Assistant preset-choice refresh without `.env` edits;
- optional server-sent events for faster Home Assistant state updates while retaining polling fallback.

## Validation backlog

These are evidence gaps, not promises of unsupported behavior:

- physical multi-Chime/group validation with more than one Smart Chime;
- independent compatibility reports from other UniFi console models and Protect/Chime versions;
- synchronized acoustic latency measurement with a reproducible trigger/microphone setup;
- longer-term compatibility evidence across firmware upgrades and real-world reboot/power-loss events.

The project will not claim these as validated until there is direct evidence.
