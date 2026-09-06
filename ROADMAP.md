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

## Planned v2.2

### Native Home Assistant media ingestion

- native `tts.speak` support;
- `media-source://` ingestion;
- bounded binary media ingestion without creating a second playback stack;
- clear format/size validation before media reaches the dispatcher.

### Friendly preset management

- create, edit, and remove user-facing spoken presets through a supported API/UI workflow;
- store display name separately from spoken text;
- refresh Home Assistant preset choices without hand-editing `.env`;
- preserve the two fixed dynamic slots rather than allocating one permanent Protect ringtone for every phrase.

### Integration quality

- consider optional server-sent events for faster HA state updates while retaining polling fallback;
- improve diagnostics for queue state, slot synchronization, resident-content lifecycle state, and release/build identity;
- collect independent compatibility reports across additional Protect and Smart Chime firmware versions.

## Validation backlog

These are evidence gaps, not promises of unsupported behavior:

- physical multi-Chime/group validation with more than one Smart Chime;
- independent compatibility reports from other UniFi console models and Protect/Chime versions;
- synchronized acoustic latency measurement with a reproducible trigger/microphone setup;
- longer-term compatibility evidence across firmware upgrades and real-world reboot/power-loss events.

The project will not claim these as validated until there is direct evidence.
