# UniFi Announcer

[![CI](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml)
[![HA validation](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml)
[![Stable](https://img.shields.io/badge/stable-v2.0.0-blue)](https://github.com/bdini13/unifi-announcer/releases/tag/v2.0.0)
[![Beta](https://img.shields.io/badge/beta-v2.1.0--beta.2-orange)](https://github.com/bdini13/unifi-announcer/releases/tag/v2.1.0-beta.2)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue)](docs/HOME_ASSISTANT.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Turns a UniFi Protect Smart Chime from a doorbell accessory into a local whole-home TTS announcement speaker.**

UniFi Announcer provides local text-to-speech, reusable spoken presets, multi-chime groups, Home Assistant controls, REST/MQTT interfaces, and optional MCP tools for UniFi Protect Smart Chimes.

It synthesizes speech with Piper or Edge TTS, creates and reuses Protect ringtone objects, and asks Protect to play them on one chime or a named group. Home Assistant and MCP remain thin interfaces over the same announcement engine.

> [!IMPORTANT]
> UniFi Protect's local API is undocumented and may change. This project has been tested with Protect 7.2.105 and Smart Chime firmware 1.7.20. See [Compatibility](docs/COMPATIBILITY.md) before upgrading firmware.
>
> UniFi Announcer is an unofficial community project and is not affiliated with or endorsed by Ubiquiti.

> [!NOTE]
> Native Home Assistant and MCP support are in the v2.1 beta. Native Home Assistant `tts.speak` / `media-source://` audio ingestion is planned for v2.2; v2.1 supports native notify actions plus text and preset `media_player.play_media`.

## Why this exists

Home Assistant's native [UniFi Protect integration](https://www.home-assistant.io/integrations/unifiprotect/) already supports Smart Chimes as Protect accessories. It exposes useful basic controls such as manually triggering a chime, setting chime volume, reporting the last ring time, rebooting the device, and pairing doorbells.

What it does **not** provide is a general-purpose announcement layer for Smart Chimes. There is no native way to hand the chime arbitrary text such as "Dinner is ready," synthesize that speech locally, reuse it efficiently, target several Smart Chimes as a group, or apply announcement-specific queueing and policy.

UniFi Announcer fills that gap while keeping Protect in the playback path. It is designed to **complement, not replace, Home Assistant's native UniFi Protect integration**: keep the native integration for normal Protect device state/configuration and add UniFi Announcer for spoken announcements and higher-level automation.

## Choose your setup

| Goal | Start here |
|---|---|
| Make a Smart Chime speak | [Docker quick start](#quick-start) |
| Use Home Assistant | [HACS setup](#home-assistant-recommended-setup) |
| Give an AI agent access | [MCP setup](#mcp-optional-ai-agent-interface) |
| Build custom automation | [REST examples](#rest-examples) |
| React directly to Protect events | [Local rules](docs/RULES.md) |

## What works today

| Capability | Status |
|---|---|
| Arbitrary text announcements | ✅ Stable |
| Piper local TTS | ✅ Stable |
| Edge TTS | ✅ Supported |
| Reusable preset tones | ✅ Stable |
| Buzzer and assigned-default playback | ✅ Stable |
| Multiple chimes and named groups | ✅ Stable |
| Quiet hours, priority, dedupe, bounded queues | ✅ Stable |
| Home Assistant HACS integration | 🧪 v2.1 beta |
| HA `notify.send_message` | 🧪 v2.1 beta |
| HA text/preset `media_player.play_media` | 🧪 v2.1 beta |
| MCP server and playback tools | 🧪 v2.1 beta |
| MQTT discovery | ✅ Supported |
| Protect event rules | 🧪 Experimental |
| Native HA `tts.speak` media ingestion | ⏭️ v2.2 |
| Direct stock-firmware HTTP playback | ❌ Not implemented |

## Architecture

```text
Home Assistant ─┐
REST            ├──► AnnouncementDispatcher ─► Protect ─► Smart Chime
MQTT            │            ▲
MCP ────────────┤            │
Protect rules ──┘       queue / policy / cache
```

For TTS:

```text
text
  -> Piper or Edge TTS
  -> MP3 cache
  -> Protect ringtone object
  -> Protect play-speaker command
  -> Smart Chime
```

All production playback goes through Protect. Home Assistant and MCP do not contain second playback implementations or receive UniFi device credentials. Direct Smart Chime HTTPS remains optional diagnostics/research rather than the production playback path.

## Requirements

- UniFi console running Protect, such as UDM Pro, UDM Pro SE, CloudKey+, or UNVR
- At least one adopted UniFi Protect Smart Chime
- Local UniFi OS account with access to Protect; SSO-only accounts do not work
- Docker Engine with Docker Compose
- TTS engine:
  - [Wyoming Piper](https://github.com/rhasspy/wyoming-piper), recommended for local TTS
  - Edge TTS with internet access

Home Assistant and MCP are optional.

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/bdini13/unifi-announcer.git
cd unifi-announcer
cp .env.example .env
```

Create a **local** UniFi console account in **Admins & Users** and grant it the Protect permissions needed to view chimes and manage ringtones.

Find your chime ID from Protect:

```bash
export UNIFI_HOST="https://<your-unifi-console-host-or-ip>"
export UNIFI_USERNAME="<local-unifi-username>"
export UNIFI_PASSWORD="<local-unifi-password>"

curl -ksS -c /tmp/unifi-cookies \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$UNIFI_USERNAME\",\"password\":\"$UNIFI_PASSWORD\",\"remember\":false}" \
  "$UNIFI_HOST/api/auth/login" >/dev/null

curl -ksS -b /tmp/unifi-cookies \
  "$UNIFI_HOST/proxy/protect/api/chimes"
```

Configure `.env`:

```env
UNIFI_HOST=https://<your-unifi-console-host-or-ip>
UNIFI_USERNAME=<local-unifi-username>
UNIFI_PASSWORD=<local-unifi-password>
UNIFI_VERIFY_SSL=false

CHIME_ID=<protect-chime-id>

TTS_ENGINE=piper
PIPER_URL=tcp://<piper-host-or-ip>:10200
PIPER_SYNTH_TIMEOUT=15

HOST_PORT=8095
CONTAINER_NAME=unifi-announcer
```

For integrations that can write/play, generate an application API key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then add it to `.env`:

```env
APP_API_KEY=<generated-key>
```

### 2. Start the service

```bash
docker compose up -d --build
docker compose logs -f unifi-announcer
```

Persistent data defaults to `./data`. To use another host path, set `DATA_PATH`, for example:

```env
DATA_PATH=/srv/unifi-announcer/data
```

Verify health and version:

```bash
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
```

A healthy response contains `"status":"ok"`. Piper may be offline during startup; non-TTS controls remain available.

## Home Assistant — recommended setup

UniFi Announcer includes a native HACS-compatible custom integration for Home Assistant 2026.3+.

> [!WARNING]
> **v2.1 beta testers:** Native Home Assistant support is distributed in `v2.1.0-beta.2`. The stable `v2.0.0` release does **not** contain the native integration. HACS does not normally select prereleases automatically, so after adding this repository explicitly enable prereleases for UniFi Announcer or select `v2.1.0-beta.2` when downloading.

### Install through HACS as a custom repository

1. Open **HACS** in Home Assistant.
2. Add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
3. Enable prereleases for this repository or explicitly choose `v2.1.0-beta.2`.
4. Install **UniFi Announcer**.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration → UniFi Announcer**.
7. Enter your Announcer URL, such as `http://announcer.local:8095`.
8. Enter `APP_API_KEY` if one is configured.

The setup flow validates `/health`, `/version`, and `/auth/check`; it does **not** play audio during setup. If the application API key later changes, Home Assistant requests reauthentication rather than requiring the integration to be deleted.

For manual installation, copy `custom_components/unifi_announcer` into `/config/custom_components/` and restart Home Assistant.

See the full [Home Assistant documentation](docs/HOME_ASSISTANT.md).

### Announce through a notify entity

Each physical chime and configured group gets a notify entity:

```yaml
action: notify.send_message
target:
  entity_id: notify.unifi_announcer_kitchen_announcements
data:
  message: "Dinner is ready"
```

Entity IDs are generated by Home Assistant and can vary with your device names; select the actual entity from the UI instead of relying on the example ID.

### Advanced announcement controls

Use the native action when an automation needs per-call options:

```yaml
action: unifi_announcer.announce
data:
  message: "Dinner is ready"
  target: kitchen
  volume: 45
  repeat_times: 1
  priority: 50
  dedupe_key: dinner-ready
```

Supported fields include `message`, `target`, `volume`, `repeat_times`, `profile`, `priority`, and `dedupe_key`. Volume `0` is valid and is not replaced by a default value.

### Media player

Text:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen_announcer
data:
  media_content_type: text
  media_content_id: "The laundry is finished"
```

Preset:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen_announcer
data:
  media_content_type: unifi-announcer/preset
  media_content_id: package-delivered
```

The media player intentionally does not pretend the Smart Chime is a normal streaming speaker: no pause, seek, fake playback position, or fake persistent transport state is advertised.

Native `tts.speak` media-source ingestion is planned for v2.2.

### v2.1 beta limitations

- Home Assistant supports one UniFi Announcer integration instance in v2.1.
- Native `tts.speak` and binary/media-source ingestion are deferred to v2.2.
- Queue depth is exposed per physical chime; groups intentionally do not expose a fake aggregate queue-depth sensor.
- Changes to `CHIMES_CONFIG` or `GROUPS_CONFIG` require reloading or restarting the Home Assistant integration before its entity topology is rebuilt.
- MCP is disabled by default and is independent of Home Assistant.

## What UniFi Announcer adds beyond native Home Assistant UniFi Protect

The native UniFi Protect integration and UniFi Announcer are intended to be used together.

| Capability | Native HA UniFi Protect | UniFi Announcer |
|---|---:|---:|
| Discover Smart Chime as a Protect device | ✅ | Not a replacement |
| Manually trigger normal chime | ✅ | ✅ plus buzzer/default/presets |
| Set basic chime volume | ✅ | ✅ per-announcement volume |
| Report last ring time | ✅ | Use native integration |
| Reboot Smart Chime | ✅ | Intentionally not exposed |
| Pair/unpair doorbells | ✅ | Use native integration |
| **Speak arbitrary text** | ❌ | **✅** |
| **Local Piper TTS** | ❌ | **✅** |
| Edge TTS | ❌ | **✅** |
| **Reusable spoken presets** | ❌ | **✅** |
| **Target several Smart Chimes as a named group** | ❌ | **✅** |
| **Per-chime bounded announcement queues** | ❌ | **✅** |
| **Quiet hours / priority / deduplication** | ❌ | **✅** |
| **HA `notify.send_message` endpoint per chime/group** | ❌ | **✅** |
| **Text/preset `media_player.play_media`** | ❌ | **✅** |
| REST announcement API | ❌ | ✅ |
| MQTT announcement interface | ❌ | ✅ |
| MCP tools for AI agents | ❌ | ✅ |
| Native HA `tts.speak` media ingestion | ❌ | ⏭️ v2.2 |

In short: the native integration exposes the Smart Chime as a **Protect accessory**; UniFi Announcer adds the layer that lets automations and AI treat it as a **programmable whole-home announcement endpoint**.

## MCP — optional AI-agent interface

UniFi Announcer can expose a Streamable HTTP MCP endpoint from the same process as the REST API.

Enable it in `.env`:

```env
MCP_ENABLED=true
MCP_API_KEY=<generate-a-dedicated-secret>
MCP_ALLOWED_HOSTS=announcer.local,<announcer-lan-ip>
```

Recreate the container:

```bash
docker compose up -d
```

Endpoint:

```text
http://<announcer-host>:8095/mcp
```

Authentication:

```text
Authorization: Bearer <MCP_API_KEY>
```

`MCP_API_KEY` is intentionally separate from `APP_API_KEY`. `MCP_ALLOWED_HOSTS` should include the exact LAN hostname/IP MCP clients use; the MCP transport keeps DNS-rebinding protection enabled.

### MCP tools

Read-only:

```text
get_status
list_chimes
list_presets
get_recent_events
get_queue_status
```

Playback:

```text
announce
play_preset
play_default
buzzer
```

The MCP surface deliberately excludes credential retrieval, raw Protect administration, reboot/reset/adoption, cache mutation, firmware research, direct staging, and arbitrary URL/file playback.

See [MCP documentation](docs/MCP.md) for client configuration and architecture details.

## REST examples

Set:

```bash
export ANNOUNCER_URL="http://<announcer-host-or-ip>:8095"
AUTH=()

# If APP_API_KEY is configured:
# export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
# AUTH=(-H "X-API-Key: $UNIFI_ANNOUNCER_API_KEY")
```

Announce text:

```bash
curl -fsS -X POST "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Dinner is ready","volume":45}' \
  "$ANNOUNCER_URL/announce"
```

Buzzer:

```bash
curl -fsS -X POST "${AUTH[@]}" "$ANNOUNCER_URL/buzzer"
```

Assigned default:

```bash
curl -fsS -X POST "${AUTH[@]}" "$ANNOUNCER_URL/play-default"
```

Create and play a preset:

```bash
curl -fsS -X PUT "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"name":"package-delivered","text":"Package delivered"}' \
  "$ANNOUNCER_URL/presets/package-delivered"

curl -fsS -X POST "${AUTH[@]}" \
  "$ANNOUNCER_URL/presets/package-delivered/play?volume=50&repeat_times=1"
```

## Multiple chimes and groups

For more than one chime, configure named targets:

```env
CHIMES_CONFIG='[
  {"name":"kitchen","id":"<kitchen-chime-id>","direct_ip":"<optional-chime-ip>"},
  {"name":"upstairs","id":"<upstairs-chime-id>"}
]'
GROUPS_CONFIG='{"downstairs":["kitchen"],"whole_house":["kitchen","upstairs"]}'
```

Then target a group:

```bash
curl -fsS -X POST "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Dinner is ready","target":"whole_house"}' \
  "$ANNOUNCER_URL/announce"
```

Each physical chime has its own bounded queue. Group members execute concurrently, and one failed member does not prevent healthy members from playing.

## MQTT and local rules

MQTT remains optional. Set `MQTT_URL`, `MQTT_USERNAME`, and `MQTT_PASSWORD` to enable discovery. See [MQTT documentation](docs/MQTT.md).

Local rules can react directly to Protect events without a Home Assistant round trip. See [Rules documentation](docs/RULES.md).

## Upgrade from v2.0 to the v2.1 beta

Keep your existing `.env` and persistent `DATA_PATH`. Do not delete the track registry or cache during a normal upgrade.

```bash
cd unifi-announcer
git fetch --tags
git checkout v2.1.0-beta.2
docker compose up -d --build
```

Then verify:

```bash
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
```

If you use MCP, add `MCP_ENABLED`, `MCP_API_KEY`, and `MCP_ALLOWED_HOSTS`; existing REST, MQTT, rules, tracks, presets, and cached TTS data do not require migration.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UniFi Announcer does not appear in HA | HACS installed stable `v2.0.0` | Enable prereleases/select `v2.1.0-beta.2`, reinstall, restart HA |
| HA reports invalid API key | `APP_API_KEY` changed or mismatches | Complete the integration's reauthentication flow |
| Buttons work but TTS fails | Piper is unavailable | Check `PIPER_URL` and the Piper service |
| MCP returns HTTP 401 | Bearer key mismatch | Check `MCP_API_KEY` and Authorization header |
| MCP returns HTTP 421 | Host not allowlisted | Add the hostname/IP to `MCP_ALLOWED_HOSTS` and recreate the container |
| Presets are missing | Protect read failed or integration state is stale | Check `/presets`, then reload the integration |
| No group queue-depth sensor | Intentional | Queue depth is defined per physical chime in v2.1 |
| New chime/group is absent in HA | Entity topology was created before config changed | Reload/restart the integration |

## Important configuration

See [`.env.example`](.env.example) for the complete list.

| Variable | Default | Purpose |
|---|---:|---|
| `UNIFI_HOST` | none | UniFi console URL |
| `UNIFI_USERNAME` | none | Local UniFi OS username |
| `UNIFI_PASSWORD` | none | Local UniFi OS password |
| `UNIFI_VERIFY_SSL` | `false` | Verify console TLS certificate |
| `CHIME_ID` | none | Default Protect chime ID |
| `TTS_ENGINE` | `piper` | `piper` or `edge` |
| `PIPER_URL` | none | Wyoming Piper endpoint |
| `APP_API_KEY` | empty | REST write routes with `X-API-Key` |
| `DATA_PATH` | `./data` | Host path mounted at `/data` |
| `VOLUME_DEFAULT` | `50` | Default request volume |
| `REPEAT_DEFAULT` | `1` | Default repeat count |
| `QUIET_HOURS` | empty | Suppression window such as `22:00-06:30` |
| `MAX_DYNAMIC_TRACKS` | `32` | Maximum service-owned dynamic TTS records |
| `MAX_TOTAL_RINGTONES` | `6` | Conservative total Protect ringtone ceiling |
| `PLAY_QUEUE_MAX_DEPTH` | `16` | Per-chime queue limit |
| `CHIMES_CONFIG` | empty | Multi-chime definitions as JSON |
| `GROUPS_CONFIG` | empty | Named groups as JSON |
| `MQTT_URL` | empty | Optional MQTT broker URL |
| `MCP_ENABLED` | `false` | Enable MCP endpoint |
| `MCP_API_KEY` | empty | Dedicated MCP bearer credential |
| `MCP_ALLOWED_HOSTS` | empty | LAN Host allowlist for MCP transport security |

## API summary

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Cached component health |
| `GET` | `/version` | Semantic version, build identity, compatibility |
| `GET` | `/auth/check` | Harmless API-key validation |
| `GET` | `/chimes` | Configured chimes, groups, and queue depths |
| `GET` | `/presets` | List Protect ringtones |
| `POST` | `/announce` | Synthesize/cache text and play it |
| `POST` | `/buzzer` | Play hardware buzzer |
| `POST` | `/play-default` | Play assigned default ringtone |
| `PUT` | `/presets/{name}` | Create or replace a preset |
| `POST` | `/presets/{name}/play` | Play a preset |
| `GET` | `/events/recent` | Recent normalized Protect events |
| `GET` | `/events/stream` | Server-Sent Events stream |
| `GET` | `/rules/status` | Local rule status/counters |
| `GET` | `/cache/ringtones/status` | Ringtone-index status |
| `GET` | `/metrics/json` | Timing histograms and counters |
| MCP | `/mcp` | Optional Streamable HTTP MCP endpoint |

FastAPI's interactive REST schema is available at `http://<announcer-host-or-ip>:8095/docs`.

## Playback behavior

Commands return a canonical disposition:

- `played` — all selected chimes played the request
- `suppressed` — quiet-hours policy suppressed it
- `deduped` — duplicate rejected inside the configured window
- `dropped` — queue policy dropped it
- `partial` — mixed results across targets
- `failed` — playback failed

Home Assistant, REST, MQTT, local rules, and MCP all reuse the same dispatcher semantics.

## Caching and safety

- Repeated text uses a disk MP3 cache.
- Ringtone IDs live in one in-memory `RingtoneIndex`.
- Simultaneous cold requests for the same phrase share ringtone creation.
- Dynamic TTS records are bounded by `MAX_DYNAMIC_TRACKS`.
- Before creating a ringtone, the service preserves headroom under `MAX_TOTAL_RINGTONES` and only evicts service-owned dynamic tracks.
- Presets, built-ins, and user-created tones are not dynamic-cleanup candidates.
- Destructive direct chime endpoints are blocked before network I/O.

See [Track registry documentation](docs/TRACKS.md) and [Playback policy](docs/POLICY.md).

## Documentation

- [Home Assistant](docs/HOME_ASSISTANT.md)
- [MCP](docs/MCP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Compatibility](docs/COMPATIBILITY.md)
- [Latency and metrics](docs/LATENCY.md)
- [MQTT](docs/MQTT.md)
- [Playback policy](docs/POLICY.md)
- [Rules](docs/RULES.md)
- [Track registry](docs/TRACKS.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [v2.1.0-beta.1 release notes](docs/RELEASE_NOTES_v2.1.0-beta.1.md)
- [v2.1.0-beta.2 release notes](docs/RELEASE_NOTES_v2.1.0-beta.2.md)

## Security

Keep UniFi credentials and API keys out of Git. Store them in `.env`, Docker secrets, Home Assistant config entries, or another local secret manager.

Do **not** expose UniFi Announcer or its MCP endpoint directly to the public internet. Use a VPN or deliberately configured authenticated reverse proxy for remote access.

Direct-device diagnostics require a current device adoption credential. Credential-extraction procedures and raw authentication research are intentionally not documented in the public repository.

The public repository intentionally excludes deployment-specific credentials, certificate fingerprints, raw authentication research, and private support data.

## Development

Core/runtime validation:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -W error -m pytest -q tests
.venv/bin/ruff check .
.venv/bin/python -m compileall -q app custom_components
docker compose config
```

Home Assistant integration validation uses a separate environment because Home Assistant has its own dependency graph:

```bash
python3.14 -m venv .venv-ha
.venv-ha/bin/pip install -r requirements-ha-test.txt
.venv-ha/bin/python -m pytest -q tests_ha
```

CI also runs HACS validation and Hassfest. Tests use mocks and sanitized fixtures; public CI does not contact live UniFi equipment or play sound.

## AI-assisted development

This project was developed with the assistance of AI coding and research tools. AI has been used for implementation, debugging, code review, test development, documentation, and research.

## Release status

- **Stable:** `v2.0.0` — local MVP reliability release
- **Beta:** `v2.1.0-beta.2` — Home Assistant + MCP hardening beta
- **Planned:** `v2.2.0` — native Home Assistant `tts.speak`, binary media ingestion, and optional SSE integration

See the [Releases page](https://github.com/bdini13/unifi-announcer/releases).

## License

MIT

Unofficial community project; not affiliated with or endorsed by Ubiquiti.