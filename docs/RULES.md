# Local rules

Rules are loaded from `${DATA_DIR}/rules.json` after the ringtone index is loaded. They are compiled against the in-memory preset and target registries. Invalid preset, target, volume, or priority values disable only that rule and produce a warning.

```json
[
  {
    "name": "front-door-ring",
    "when": {"event": "doorbell_ring", "model": "camera"},
    "then": {
      "preset": "front-door",
      "target": "downstairs",
      "volume": 40,
      "repeat": 1,
      "priority": 10
    },
    "cooldown_ms": 250
  }
]
```

The hot path is entirely local: normalized event → compiled RAM rule → RAM preset lookup → dispatcher → per-chime queue → Protect playback. It does not synthesize TTS, upload audio, list ringtones, fetch event detail, or call Home Assistant.

- `GET /rules/status` is read-only and reports active/disabled counts and reasons.
- `POST /rules/reload` re-reads and recompiles the file and is protected by the same `X-API-Key` policy as other writes.
