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

v2.1.6 focuses on Home Assistant playback reliability when Protect's ringtone inventory lags a successful owned-slot overwrite, plus immediate HA playback-result reporting.

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
- improve diagnostics for queue state, slot synchronization, and release/build identity;
- collect independent compatibility reports across additional Protect and Smart Chime firmware versions.

## Validation backlog

These are evidence gaps, not promises of unsupported behavior:

- physical multi-chime/group validation with more than one Smart Chime;
- independent compatibility reports from other UniFi console models;
- synchronized acoustic latency measurement if a reproducible test setup becomes available.

The project will not claim these as validated until there is direct evidence.
