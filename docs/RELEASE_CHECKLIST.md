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
- [ ] HACS validation passes against the exact release commit
- [ ] Hassfest validation passes against the exact release commit

## v2.1 feature evidence

- [x] Fixed-slot overwrite validated on a physical Smart Chime: both alternating
      service-owned slots played distinct phrases correctly.
- [x] Concurrent three-message behavior passed automated regression coverage.
- [x] Duplicate-request deduplication passed automated regression coverage.
- [x] Preset, assigned-default, hardware buzzer, and post-restart TTS playback passed.
- [x] A 100-unique-message automated regression preserved exactly two service-owned
      dynamic identities and synthetic per-device slot mappings.
- [x] Live single-device `/health`, `/version`, slot/cache, metrics, rules, and recent-events checks passed.

## v2.1.2 public-launch gate

v2.1.2 is a public-installation and release-polish patch. It must not change the
validated playback architecture.

- [ ] `APP_VERSION`, Home Assistant manifest version, and integration constant all equal `2.1.2`.
- [ ] Release workflow and release script both target `v2.1.2` and the exact validated `main` SHA.
- [ ] README badge, Quick Start, upgrade section, release status, and release-note link all point to `v2.1.2`.
- [ ] README contains no temporary "scheduled for v2.1.1" or "next release v2.1.1" launch text.
- [ ] Fresh-install Quick Start creates `.env` with mode `0600` and does not place the UniFi password into shell history.
- [ ] HACS documentation clearly states that the custom integration requires the separately running Docker backend.
- [ ] Default Compose configuration does not opt the locally built image into Watchtower updates.
- [ ] Public bug and feature-request templates exist and repeat the redaction/security boundary.
- [ ] v2.1.2 release notes distinguish automated validation from the existing single-device physical evidence.

## Out-of-scope research limitations

- No synchronized microphone benchmark was available. Do not claim measured acoustic latency.
- Generic arbitrary raw upload, unknown-route probing, controller identity reuse, direct
  slot deletion, and direct UCP4 transport remain unsupported and outside v2.1.
- Multi-chime physical playback was not tested because only one Smart Chime was available.

These limitations do not block the validated two-slot implementation shipped in stable v2.1.
