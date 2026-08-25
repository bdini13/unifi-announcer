# UniFi Announcer v2.1.0-beta.2

This is a hardening prerelease for the Home Assistant + MCP work introduced in `v2.1.0-beta.1`. It deliberately avoids v2.2 media-ingestion features and keeps the existing Protect/dispatcher playback architecture unchanged.

## Home Assistant fixes

- Updated the OptionsFlow implementation for Home Assistant 2026.x so **Configure** uses Home Assistant's framework-managed config entry.
- Added setup-time `/auth/check` validation so a stale `APP_API_KEY` initiates Home Assistant reauthentication instead of failing only when playback is attempted.
- Temporary Announcer connectivity failures now use retryable config-entry setup behavior.
- Reauthentication avoids the update-listener/double-reload pattern deprecated in Home Assistant 2026.6.
- Declared the integration single-config-entry for v2.1 so the global `unifi_announcer.announce` action cannot silently choose the wrong Announcer server.
- Physical entity unique IDs now follow stable Protect chime IDs rather than mutable display names.
- Entity naming now follows Home Assistant's device + translated entity-name model.
- Logical groups no longer expose a misleading always-zero queue-depth sensor; queue depth remains per physical chime.
- The Version sensor reports the semantic release version and exposes git SHA separately as build metadata.
- Added synchronized options/config translations and local custom-integration brand assets.

## MCP fix

- `list_chimes` now reports the actual configured `GROUPS_CONFIG` mapping instead of attempting to read a nonexistent public `dispatcher.groups` attribute.

## Validation hardening

- Added a real Home Assistant custom-component test environment separate from the Docker runtime dependency graph.
- Added regression coverage for config flow, OptionsFlow, reauthentication, setup auth/connectivity failures, entity topology, service defaults, and unload behavior.
- Added HACS validation and Hassfest workflows.
- CI now validates Docker Compose in addition to Python tests, Ruff, compile checks, JSON metadata, and Docker build.
- Warnings remain errors; the only retained warning filter is the exact known upstream `python-multipart` compatibility warning emitted through `starlette.formparsers`.

## Version and release identity

- Added a shared runtime version source for `2.1.0-beta.2`.
- Production `/version`, FastAPI/OpenAPI metadata, Home Assistant manifest/diagnostics, and the HA Version sensor now report the beta.2 semantic version consistently.

## Documentation and security cleanup

- Home Assistant beta installation instructions now explicitly require selecting/enabling the prerelease; stable `v2.0.0` does not contain the native integration.
- Added a choose-your-interface table, upgrade path, beta limitations, and first-user troubleshooting guidance.
- Reframed direct-device access as optional diagnostics/research rather than the production path.
- Removed direct Protect database credential-extraction commands from the public `.env.example`.
- Added the unofficial/not-affiliated-with-Ubiquiti notice near the top of the README.

## Architecture unchanged

All playback still flows through:

```text
Home Assistant / REST / MQTT / MCP / Protect rules
                    ↓
          AnnouncementDispatcher
                    ↓
             queue / policy
                    ↓
                  Protect
                    ↓
              Smart Chime
```

Home Assistant and MCP remain optional thin interfaces. Neither receives UniFi console credentials or implements a second playback stack.

## Still deferred to v2.2

- native Home Assistant `tts.speak`
- `media-source://` / binary media ingestion
- arbitrary URL/file playback
- generic streaming-speaker controls
- optional Home Assistant SSE consumption

## Beta validation focus

Please focus live testing on:

- HACS custom-repository installation with prereleases enabled
- config flow and **Configure** options
- API-key reauthentication
- physical chime and logical group entity topology
- `notify.send_message`
- `unifi_announcer.announce`
- buzzer/default/preset controls
- text and preset `media_player.play_media`
- unload/reload behavior
- MCP Host allowlist and bearer authentication
- MCP group discovery and playback tools
- behavior when Piper or one Smart Chime is unavailable
