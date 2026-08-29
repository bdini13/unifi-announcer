# Release checklist

This checklist records the evidence required before a tagged release. Passing
CI or deploying a commit does not clear approval-gated research blockers.

## Automated gates

- [ ] Core lane uses Python 3.12 with `pip install -r requirements-dev.txt`, then runs `EVENTS_ENABLED=false TTS_ENGINE=none UNIFI_HOST=https://unifi.invalid CHIME_DIRECT_IP=192.0.2.10 python -W error -m pytest -q tests`
- [ ] Home Assistant lane uses a separate Python 3.14 environment with `pip install -r requirements-ha-test.txt`, then runs `python -m pytest -q tests_ha` without interpreter-level `-W error` (the HA test stack emits upstream import-time deprecations before `pytest.ini` loads)
- [ ] `ruff check .`
- [ ] `python -m compileall -q app scripts tests`
- [ ] application modules import without network activity
- [ ] `git diff --check`
- [ ] changed-file credential/secret scan
- [ ] Docker image builds with the release commit in `GIT_SHA`
- [ ] read-only live checks pass for `/health`, `/version`, capabilities, cache,
      metrics, rules, and recent events

## Open release blockers

- **Acoustic benchmark blocked:** Phase 21 implemented and synthetically tested
  the offline analyzer, but no synchronized microphone recording path was
  available and no sound-producing benchmark was approved. No acoustic latency
  numbers may be claimed.
- **Dynamic-slot A/B overwrite inconclusive:** the two dedicated, pinned,
  service-owned slots and their NVR-to-device mapping were established. The
  inactive-slot overwrite and ping-pong test were not run because authenticated
  raw-MP3 overwrite semantics remain unverified. Production dynamic slots stay
  default-off and disconnected from I/O.
- Direct raw-upload authentication and route research is outside the public
  release scope. Do not probe authentication variants, unknown routes, or reuse
  controller identity material.
- **Direct UCP4 blocked:** no legitimate callable Protect module, IPC endpoint,
  or approved certificate trust path was found. The research client remains a
  default-off local mock with no transport.

Do not tag a release while any blocker relevant to the claimed feature set is
open. A safe service deployment is not a release tag and must not be represented
as clearing these blockers.