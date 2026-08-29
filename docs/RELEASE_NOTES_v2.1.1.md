# v2.1.1 — Secure public installation hardening

v2.1.1 is a patch release focused on safe, repeatable public installation and
upgrade behavior. It does not move or replace the immutable `v2.1.0` tag.

## Highlights

- Fails closed when `APP_API_KEY` is empty or still set to a documented
  placeholder, and requires authentication for write and detailed diagnostic
  routes.
- Keeps public health output coarse while protecting installation identities,
  device/ringtone mappings, filenames, cache details, and error diagnostics.
- Uses a writable project-scoped Docker volume for fresh installs while
  preserving explicit legacy `DATA_PATH` bind mounts.
- Adds documented migration for the older implicit `./data` layout.
- Hardens backup and rollback instructions with private permissions, host-user
  ownership, archive validation, and non-destructive restore staging.
- Requires an API key in the Home Assistant integration and corrects all REST,
  Home Assistant, and MCP verification examples.
- Aligns the application, Home Assistant integration, workflow, and immutable
  release automation on `v2.1.1`.

## Validation

- Core regression, authentication, public-installation, release-state, Ruff,
  compile, Compose, metadata, Docker build, startup, and backup/restore checks
  passed for the release candidate.
- Single-device physical validation from v2.1.0 remains the available hardware
  evidence. Multi-chime behavior is covered with synthetic automated fixtures;
  physical multi-device playback was not validated for this patch release.
- The Home Assistant test dependency is pinned to `homeassistant==2026.3.2`;
  local execution remains unavailable until that version is published by the
  package index. HACS and Hassfest remain required release-workflow gates.

## Upgrade

Keep your existing `.env` and persistent data. Follow the migration and backup
steps in the README before changing tags.

```bash
git fetch --tags
git checkout v2.1.1
docker compose up -d --build
```

Generate and configure a unique `APP_API_KEY`; do not retain the
`REPLACE_ME` placeholder. Existing explicit `DATA_PATH` values continue to be
honored.
