# v2.2.0-beta.3 — Opt-in protocol-profile camera compatibility candidate

## Purpose

v2.2.0-beta.3 prepares an explicitly opt-in experimental path for additional Protect camera models whose observed talkback wire profile exactly matches a supported AAC/ADTS transport. Stable `v2.1.8` remains the recommended public release, and published prerelease `v2.2.0-beta.2` remains the latest published camera prerelease. The beta.3 representative physical gate has passed, but merge, tagging, publication, and release deployment still require separate owner authorization.

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

Protocol similarity is not physical validation. The candidate does not add the G4 Instant to the physically validated model table and must not claim support for every UniFi camera.

## Read-only G4 Instant discovery

One available UVC G4 Instant was initially inspected through Protect's read-only camera inventory/bootstrap path. It reported a connected speaker and the same AAC-LC, `serverudp`, 22,050 Hz, mono, 16-bit talkback metadata as the validated G3 Instant. The exact candidate later passed normal, repeat, serialization, camera-reboot recovery, and Announcer-restart physical playback on that representative device. This evidence is intentionally narrow and does not generalize compatibility to other G4 or camera models.

## Safety preserved

- Per-camera preparation leases and prepared-session profile revalidation remain in force.
- Unsupported transports still fail before synthesis, negotiation, or playback.
- Camera targets remain text/repeat only; volume, preset/default, and buzzer controls remain unavailable.
- Smart Chime fixed slots and playback behavior are unchanged.
- Home Assistant's coordinator translation retains the sanitized compatibility label from `/targets`; unsupported label values are discarded. The current MCP Chime listing does not claim camera compatibility reporting.

## Completed physical gate and remaining approvals

Automated validation proved default-deny parsing, exact matching, labeling, session checks, and regression safety. The exact frozen runtime candidate was also deployed with rollback backups and passed one-device-at-a-time physical validation on the representative G4 Instant.

See `docs/validation/v2.2.0-beta.3-g4-instant-validation.md`. Physical PASS does not itself authorize marking the PR ready, merge, tagging, publication, release deployment, stable promotion, or a compatibility claim beyond the representative exact profile; each remains a separate owner decision.
