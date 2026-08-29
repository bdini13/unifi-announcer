# v2.1.0 — Home Assistant, MCP, and fixed-slot TTS

v2.1.0 promotes the v2.1 beta series after automated CI and single-device live
Smart Chime validation. Multi-chime behavior is covered by automated tests but
was not physically validated with multiple Smart Chimes for this release.

## Highlights

- Native Home Assistant HACS integration with notify, media-player, button, select, sensor, diagnostics, and reauthentication support.
- Optional Streamable HTTP MCP server with read-only status tools and bounded playback tools.
- Exactly two persistent service-owned dynamic TTS slots, overwritten in place with fail-closed ownership checks.
- Bounded host-side TTS cache and conservative migration of proven beta.2 artifacts.
- Per-chime bounded queues, priority, quiet-hours policy, deduplication, groups, presets, assigned-default playback, and buzzer control.

## Validation

- Core, Home Assistant, HACS, Hassfest, Ruff, compile, Compose, and Docker build gates pass in CI.
- A 100-unique-message automated regression kept the Protect identity count
  fixed at two and preserved synthetic per-device slot mappings.
- Single-device live checks covered both alternating TTS slots,
  preset/default/buzzer playback, restart persistence, and service status.
- Multi-chime behavior is covered by automated tests using synthetic fixtures;
  physical multi-device playback remains unvalidated in v2.1.0.

## Upgrade

Keep the existing `.env` and persistent data directory. Do not delete `track_registry.json` when upgrading from a v2.1 beta.

```bash
git fetch --tags
git checkout v2.1.0
docker compose up -d --build
```

The current per-device Smart Chime credential requirement remains for arbitrary
TTS. Preset, default, and buzzer controls remain available independently.