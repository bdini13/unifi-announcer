# Contributing

Thanks for helping improve UniFi Announcer.

## Project guardrails

The Docker service and `AnnouncementDispatcher` are the source of truth. REST, Home Assistant, MQTT, MCP, and local rules should remain thin adapters over the same dispatcher rather than growing separate playback implementations.

For dynamic TTS, preserve the fixed-slot safety model:

- exactly two persistent service-owned dynamic slots per installation;
- no guessed physical slot writes;
- ownership rechecked before direct overwrite;
- ambiguous, user-created, built-in, preset, or unknown tracks never become dynamic overwrite targets;
- safety failures should fail closed rather than silently allocate new identities.

Changes that alter these boundaries need explicit tests, documentation, and physical validation where practical.

## Before opening an issue

- Search existing issues and release notes.
- Reproduce on the latest stable release when practical.
- Include semantic version and `/version` git SHA when available.
- Distinguish automated/synthetic evidence from physical Smart Chime behavior.
- Remove credentials, API keys, LAN addresses, device IDs, certificate details, support logs, and private audio from all output.
- Use the private process in [SECURITY.md](SECURITY.md) for vulnerabilities.

## Development setup

Core/runtime checks:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -W error -m pytest -q tests --durations=20
.venv/bin/ruff check .
.venv/bin/python -m compileall -q app custom_components
docker compose config
```

Home Assistant checks use a separate environment:

```bash
python3.14 -m venv .venv-ha
.venv-ha/bin/pip install -r requirements-ha-test.txt
.venv-ha/bin/python -m pytest -q tests_ha --durations=10
```

Repeat HA tests in a separate Python 3.14 environment using `requirements-ha-current-test.txt` for HA 2026.10.0. The minimum environment remains pinned to 2026.3.4; both CI lanes must pass.

CI additionally builds the Docker image, validates HACS metadata, and runs Hassfest.
Both workflows run for PRs, `main`, version tags, and manual dispatch; branch pushes
without a PR do not start duplicate CI. Scheduled HA validation is weekly.
The [CI review and performance guide](docs/CI.md) records coverage decisions,
caching, timings, and how to profile regressions. Test fake devices without
production settle waits; retain focused delay/deadline tests. Prefer behavioral
assertions over frozen release prose or implementation-identity assertions.

## Pull requests

1. Create a focused branch from `main`.
2. Add or update a regression test before changing observable behavior.
3. Keep public fixtures synthetic, portable, and free of deployment-specific data.
4. Keep source comments focused on invariants and non-obvious safety decisions rather than restating code.
5. Update README, focused docs, compatibility notes, and release notes when user-visible behavior or claims change.
6. Run the full relevant test/validation set.
7. Describe validation honestly: distinguish automated fixtures from physical Smart Chime testing and state how many physical devices were used.
8. For playback changes, include a rollback path and avoid merging until any release-specific physical gate is complete.

Do not submit credential-extraction procedures, destructive device operations, raw private authentication research, private network topology, or deployment-specific artifacts.

## Release changes

A release PR should keep these values aligned:

- `app/version.py`;
- `custom_components/unifi_announcer/const.py`;
- `custom_components/unifi_announcer/manifest.json`;
- release script/workflow target;
- README install/upgrade version;
- release notes and [release checklist](docs/RELEASE_CHECKLIST.md).

The release workflow is intentionally fail-closed and must never move or replace an existing release tag to make CI pass.
