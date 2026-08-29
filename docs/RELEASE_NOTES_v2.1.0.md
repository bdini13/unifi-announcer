# v2.1.0 — Home Assistant, MCP, and fixed-slot TTS

v2.1.0 promotes the v2.1 beta series to stable after automated CI, live Smart Chime soak testing, and a final physical playback matrix.

## Highlights

- Native Home Assistant HACS integration with notify, media-player, button, select, sensor, diagnostics, and reauthentication support.
- Optional Streamable HTTP MCP server with read-only status tools and bounded playback tools.
- Exactly two persistent service-owned dynamic TTS slots, overwritten in place with fail-closed ownership checks.
- Bounded host-side TTS cache and conservative migration of proven beta.2 artifacts.
- Per-chime bounded queues, priority, quiet-hours policy, deduplication, groups, presets, assigned-default playback, and buzzer control.

## Validation

- Core, Home Assistant, HACS, Hassfest, Ruff, compile, Compose, and Docker build gates pass in CI.
- A 100-unique-message live Smart Chime soak kept the Protect identity count fixed at two and preserved physical slot mappings.
- Final live checks covered both alternating TTS slots, preset/default/buzzer playback, concurrent announcements, deduplication, restart persistence, health, metrics, rules, cache, and recent events.

## Upgrade

Keep the existing `.env` and persistent data directory. Do not delete `track_registry.json` when upgrading from a v2.1 beta.

```bash
git fetch --tags
git checkout v2.1.0
docker compose up -d --build
```

Beta.3's current per-device Smart Chime credential requirement remains for arbitrary TTS. Preset, default, and buzzer controls remain available independently.