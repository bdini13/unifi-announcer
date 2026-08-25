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
| Direct ringtone-slot staging | Unpublished experimental path | Disabled and not wired to production |
| Direct playback or deletion | No verified public route | Unsupported |
| Adopt, reset, or password operations | Not applicable | Refused before network I/O |

## Safety rules

- Unknown firmware fails closed for direct writes.
- Generic direct staging is refused before network I/O.
- The research-only overwrite method requires an explicitly owned, non-built-in
  slot with a positive slot number and exact filename.
- A retained rollback artifact is required before any separately approved local
  experiment.
- Direct deletion is prohibited because slot deletion semantics are unproven.
- Protect/NVR ringtone identity remains mandatory for playback.

## Public evidence policy

The repository keeps portable protocol boundaries and safety findings. It does
not publish live deployment IDs, certificate fingerprints, track hashes, raw
support logs, local evidence paths, timestamps, or authentication-test results.
Sanitized tests use synthetic fixtures only.
