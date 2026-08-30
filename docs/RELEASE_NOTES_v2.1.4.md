# v2.1.4 — Reliable preset playback

This patch release includes Home Assistant naming improvements, slot-backed spoken presets, sparse physical-slot handling, and a bounded physical-device synchronization gate before first playback.

## Highlights

- Waits until the Smart Chime reports the exact overwritten MP3 fingerprint.
- Adds a short settle delay before Protect receives the first playback request.
- Fails closed on synchronization timeout rather than reporting a false success.
- Uses the two existing service-owned TTS slots for spoken presets.
- Adds friendly preset management to the project roadmap.

## Validation

- 264 core tests
- 9 Home Assistant integration tests
- Ruff, compile, HACS, Hassfest, Docker build, and release checks
