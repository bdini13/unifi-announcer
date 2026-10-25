# Direct chime HTTP API

Direct Smart Chime endpoints are undocumented and experimental. Production
ringtone creation and playback use the authenticated Protect/NVR path.

Deployment-specific identifiers, filenames, hashes, certificate details, and
raw authentication research are intentionally excluded from this public
repository.

## Supported boundary

| Operation | Authentication | Project behavior |
|---|---|---|
| Device information | Device credential provider | Capability-gated read with Protect fallback |
| Redacted device support log | Device credential provider plus app API key | Experimental diagnostic read |
| Protect ringtone creation | UniFi console session plus CSRF | Production backend |
| Protect play-speaker / play-buzzer | UniFi console session plus CSRF | Production backend |
| Direct overwrite of a proven service-owned slot | Device credential provider | Production dynamic TTS only, after ownership validation |
| Generic direct ringtone-slot staging | Unpublished experimental path | Disabled and not wired to production |
| Direct playback or deletion | No verified public route | Unsupported |
| Adopt, reset, or password operations | Not applicable | Refused before network I/O |

## Safety rules

- Unknown firmware fails closed for direct writes.
- Generic direct staging is refused before network I/O.
- The owned-slot overwrite method requires an explicitly owned, non-built-in
  slot with a positive slot number and exact filename.
- A retained rollback artifact is required before any separately approved local
  experiment.
- Direct deletion is prohibited because slot deletion semantics are unproven.
- Protect/NVR ringtone identity remains mandatory for playback.

## Controller interaction

Protect can rewrite physical slots from its canonical ringtone files during synchronization. The unreleased candidate requires a matching current inventory fingerprint before reusing resident speech, and invalidates preparation when an observed controller change races it. Immediately after a successful direct overwrite, the existing bounded stale-inventory allowance still requires the exact proven slot and filename.

Normal Protect playback checks catalog identity and target connection; presets also compare canonical audio with reported device fingerprints. Protect omits canonical filename/track number from its public ringtone catalog, so this preflight reduces known fallback cases without proving an atomic controller-to-device mapping. Manual play without a ringtone ID selects built-in track 1, independently of camera ringtone assignments.

Initial silent-slot provisioning uses a separate journaled staging path because physical ownership has not yet been established. Its original before-snapshots survive interrupted responses. Delayed recovery requires positive identity or exact known content evidence and never claims a transformed, unidentified delta. Preserve `dynamic_tts_provisioning.json` with the installation and slot registry. All new behavior above has been tested offline; no new firmware or audible playback validation is claimed.

## Public evidence policy

The repository keeps portable protocol boundaries and safety findings. It does
not publish live deployment IDs, certificate fingerprints, track hashes, raw
support logs, local evidence paths, timestamps, or authentication-test results.
Sanitized tests use synthetic fixtures only.
