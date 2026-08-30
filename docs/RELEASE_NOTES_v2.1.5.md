# v2.1.5 — Live slot verification

## Fixed

- Verify the Smart Chime's live physical-slot MP3 fingerprint before skipping a repeated TTS overwrite.
- Rewrite stale slot contents when persisted registry state disagrees with the physical chime.
- Preserve the existing ownership checks, bounded synchronization wait, and fail-closed behavior.

This prevents Protect `play-speaker` HTTP 200 responses from masking silent playback caused by stale cached slot metadata.