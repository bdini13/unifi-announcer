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

### 1. Camera-speaker TTS — published experimental prerelease

Current published prerelease: **v2.2.0-beta.2**. Stable `v2.1.8` remains the recommended release. Beta.2 adds exact model/profile gating, prepared-session revalidation, per-camera serialization, dynamic availability recovery, and strict group validation without broadening the validated camera boundary.

The integrated path has been physically validated on one **UVC G3 Instant** using the exact **AAC-LC / 22.05 kHz / mono / 16-bit `serverudp`** talkback profile. Compatibility is evidence-based rather than inferred from generic `hasSpeaker` or AAC metadata.

Current compatibility-expansion priorities:

- keep `CAMERAS_CONFIG` explicit; cameras never join the implicit default target;
- permit playback only for exact model/profile records that have passed integrated physical validation;
- keep one prepared talkback session per physical camera at a time while allowing different cameras to remain independent;
- refresh camera availability through authenticated `/targets` polling so Home Assistant entities recover from reconnects without recreation;
- reject malformed groups and unknown/duplicate members at startup rather than silently dropping them;
- preserve shared dispatcher, queueing, quiet-hours, priority, dedupe, and mixed-group semantics;
- keep camera volume device-managed and continue to reject preset/default/buzzer and unvalidated Opus/RTP paths.

Additional camera models enter the compatibility table only after exact integrated-path audible validation and regression coverage. The next representative target is an opt-in G4 Instant profile; success on that device must not be generalized to every UniFi camera. A metadata match alone is not sufficient.

Published prerelease `v2.2.0-beta.3` adds an empty-by-default, exact protocol-profile allowlist for additional-camera experiments. Normal speech, repeat-times-two, rapid serialization, camera-reboot recovery, and post-Announcer-restart playback passed on one representative G4 Instant. An initially uncertain restart observation triggered a fail-closed beta.2 rollback; a later explicitly approved retry on the same immutable candidate was heard clearly once at confirmed device volume `100`. The tagged release was subsequently deployed by immutable digest with exact source/OCI/runtime provenance and clean silent verification. This validates only that representative exact profile and does not generalize to other G4 or camera models or promote the prerelease to stable.

### 2. Native Home Assistant media ingestion

- native `tts.speak` support;
- `media-source://` ingestion;
- bounded binary media ingestion through the same validated dispatcher and target backends;
- clear format, duration, and size validation before media reaches a Protect device.

### 3. Diagnostics and compatibility

- redacted diagnostic bundles covering queue state, slot synchronization, resident-content lifecycle state, camera capability state, and release/build identity;
- per-stage latency reporting that distinguishes Home Assistant dispatch, synthesis/cache work, device preflight, upload, synchronization, camera negotiation, and playback acceptance;
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
- additional camera models and talkback profiles beyond the validated G3 Instant AAC profile;
- independent compatibility reports from other UniFi console models and Protect/Chime versions;
- synchronized acoustic latency measurement with a reproducible trigger/microphone setup;
- longer-term compatibility evidence across firmware upgrades and real-world reboot/power-loss events.

The project will not claim these as validated until there is direct evidence.
