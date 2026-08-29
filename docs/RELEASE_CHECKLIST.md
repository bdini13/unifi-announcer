# Release checklist

This checklist records the evidence required before a tagged release. Passing
CI or deploying a commit does not clear approval-gated research blockers.

## Automated gates

- [ ] Core lane uses Python 3.12 with `pip install -r requirements-dev.txt`, then runs `EVENTS_ENABLED=false TTS_ENGINE=none UNIFI_HOST=https://unifi.invalid CHIME_DIRECT_IP=192.0.2.10 python -W error -m pytest -q tests`
- [ ] Home Assistant lane uses a separate Python 3.14 environment with `pip install -r requirements-ha-test.txt`, then runs `python -m pytest -q tests_ha` without interpreter-level `-W error` (the HA test stack emits upstream import-time deprecations before `pytest.ini` loads)
- [ ] `ruff check .`
- [ ] `python -m compileall -q app custom_components`
- [ ] application modules import without network activity
- [ ] `git diff --check`
- [ ] changed-file credential/secret scan
- [ ] Docker image builds with the release commit in `GIT_SHA`
- [ ] read-only live checks pass for `/health`, `/version`, capabilities, cache,
      metrics, rules, and recent events

## v2.1.0 release evidence

- [x] Fixed-slot overwrite validated on a physical Smart Chime: both alternating
      service-owned slots played distinct phrases correctly.
- [x] Concurrent three-message playback completed without cross-talk or truncation.
- [x] Simultaneous duplicate requests produced one audible playback.
- [x] Preset, assigned-default, hardware buzzer, and post-restart TTS playback passed.
- [x] A 100-unique-message soak preserved exactly two service-owned dynamic identities.
- [x] Live `/health`, `/version`, slot/cache, metrics, rules, and recent-events checks passed.

## Out-of-scope research limitations

- No synchronized microphone benchmark was available. Do not claim measured acoustic latency.
- Generic arbitrary raw upload, unknown-route probing, controller identity reuse, direct
  slot deletion, and direct UCP4 transport remain unsupported and outside v2.1.0.
- Multi-chime physical playback was not tested because only one Smart Chime was available.

These limitations do not block the validated two-slot implementation shipped in v2.1.0.
