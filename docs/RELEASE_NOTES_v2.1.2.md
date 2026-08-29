# v2.1.2 — Public launch polish

v2.1.2 is a release-quality patch over v2.1.1. It does not change the announcement dispatcher, Protect playback path, fixed-slot ownership model, queue semantics, or Home Assistant entity behavior.

## Highlights

- Rebuilds the public README around a shorter, clearer install path and removes stale pre-release/v2.1.1 launch language.
- Makes the HACS boundary explicit: the Home Assistant custom integration is a client for the separately running UniFi Announcer Docker service.
- Creates `.env` with private permissions in the Quick Start and avoids putting the UniFi password into shell history in the optional chime-ID discovery example.
- Keeps the advanced arbitrary-TTS credential requirement visible before installation and preserves the credential-free `TTS_ENGINE=none` baseline.
- Removes the default Watchtower label from the locally built Compose image so release pinning remains deliberate and understandable.
- Adds a feature-request issue template for public feedback.
- Aligns application, Home Assistant manifest/constants, tests, documentation, and release automation on `v2.1.2`.
- Corrects the v2.1.1 documentation note about Home Assistant testing: the project runs Home Assistant custom-component tests through the pinned `pytest-homeassistant-custom-component` test stack, plus HACS and Hassfest validation.

## Validation boundary

The playback architecture shipped in v2.1.0 was physically validated on one Smart Chime for alternating fixed slots, preset/default/buzzer playback, restart persistence, and service status. A separate 100-unique-message automated regression kept dynamic Protect identities fixed at two and preserved synthetic per-device slot mappings.

v2.1.1 and v2.1.2 are public-installation/release-polish patches and do not change that playback architecture. Multi-chime behavior remains covered by automated fixtures but has not yet been physically validated with multiple Smart Chimes. No measured acoustic-latency claim is made.

Before v2.1.2 is published, the release candidate must pass the existing core regression suite, authentication/public-install tests, release-state tests, Home Assistant custom-component tests, Ruff, compile checks, Compose validation, Docker build, HACS validation, and Hassfest against the exact release commit.

## Upgrade

Keep your existing `.env` and persistent data. If an older installation used the former implicit `./data` bind mount, preserve it with `DATA_PATH=./data` before changing tags. Do not delete `track_registry.json`.

```bash
git fetch --tags
git checkout v2.1.2
docker compose up -d --build
```

If `APP_API_KEY` is not already configured, generate a unique key before starting the service. New installations should follow the README Quick Start, which creates `.env` with mode `0600`.
