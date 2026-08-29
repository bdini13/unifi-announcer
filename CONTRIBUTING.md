# Contributing

Thanks for helping improve UniFi Announcer.

## Before opening an issue

- Search existing issues and release notes.
- Reproduce on the latest stable release when practical.
- Remove credentials, API keys, LAN addresses, device IDs, certificate details,
  support logs, and private audio from all output.
- Use the private process in [SECURITY.md](SECURITY.md) for vulnerabilities.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -W error -m pytest -q tests
.venv/bin/ruff check .
.venv/bin/python -m compileall -q app custom_components
docker compose config
```

Home Assistant tests use their separate requirements file and a supported Python
version documented in the README.

## Pull requests

1. Create a focused branch from `main`.
2. Add a failing test before changing behavior.
3. Keep public fixtures synthetic and portable.
4. Update README, compatibility notes, and release notes when claims change.
5. Run the full relevant test and validation commands.
6. Describe validation honestly; distinguish automated fixtures from physical
   Smart Chime tests and state the number of physical devices used.

Do not submit credential extraction, destructive device operations, private
network topology, or deployment-specific artifacts.
