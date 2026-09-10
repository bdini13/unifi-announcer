# v2.2.0-beta.3 — Opt-in protocol-profile camera compatibility prerelease

## Purpose

Published prerelease `v2.2.0-beta.3` provides an explicitly opt-in experimental path for additional Protect camera models whose observed talkback wire profile exactly matches a supported AAC/ADTS transport. Stable `v2.1.8` remains the recommended public release; `v2.2.0-beta.2` is the previous camera prerelease.

## Default-deny compatibility model

`EXPERIMENTAL_CAMERA_PROFILES` is **empty by default**. Without an explicit exact profile entry, behavior is unchanged: the physically validated UVC G3 Instant model/profile remains available and an unvalidated G4 Instant remains unavailable.

An operator may opt in to one exact wire profile:

```env
EXPERIMENTAL_CAMERA_PROFILES=[{"codec":"aac","transport":"serverudp","sample_rate":22050,"channels":1,"bits_per_sample":16}]
```

This does not auto-discover cameras or add them to the implicit `default` target. A camera must still be explicitly listed in `CAMERAS_CONFIG`. The experimental entry matches all five protocol dimensions exactly; malformed, duplicate, extra-key, Opus/RTP, non-mono, non-16-bit, or otherwise unsupported entries fail startup.

## Evidence labeling

A model-specific entry in the established validated table continues to report:

```text
compatibility=physically_validated
```

A non-validated model admitted only by the explicit protocol allowlist reports:

```text
compatibility=experimental_opt_in
```

Protocol similarity is not physical validation. The published prerelease does not add the G4 Instant to the physically validated model table and must not claim support for every UniFi camera.

## Read-only G4 Instant discovery

One available UVC G4 Instant was initially inspected through Protect's read-only camera inventory/bootstrap path. It reported a connected speaker and the same AAC-LC, `serverudp`, 22,050 Hz, mono, 16-bit talkback metadata as the validated G3 Instant. The exact candidate later passed normal, repeat, serialization, camera-reboot recovery, and Announcer-restart physical playback on that representative device. This evidence is intentionally narrow and does not generalize compatibility to other G4 or camera models.

## Safety preserved

- Per-camera preparation leases and prepared-session profile revalidation remain in force.
- Unsupported transports still fail before synthesis, negotiation, or playback.
- Camera targets remain text/repeat only; volume, preset/default, and buzzer controls remain unavailable.
- Smart Chime fixed slots and playback behavior are unchanged.
- Home Assistant's coordinator translation retains the sanitized compatibility label from `/targets`; unsupported label values are discarded. The current MCP Chime listing does not claim camera compatibility reporting.

## Completed physical, publication, and deployment gates

Automated validation proved default-deny parsing, exact matching, labeling, session checks, and regression safety. The exact frozen runtime candidate was also deployed with rollback backups and passed one-device-at-a-time physical validation on the representative G4 Instant.

The approved PR merge, tag, and GitHub prerelease target `76fca7f25a8f3b43e73ffd0432d97e5ec3995ce4`. The tagged deployment pins image `sha256:46b1af0a5a96a9b93d0c08884b7f07a6a669a59ac170cc713ee2173837dc1966`, with matching source, OCI revision, and runtime SHA. See `docs/validation/v2.2.0-beta.3-g4-instant-validation.md`. These completed prerelease gates do not promote beta.3 to stable or extend compatibility beyond the representative exact profile.
