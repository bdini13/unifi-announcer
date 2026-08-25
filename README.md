# UniFi Announcer

[![CI](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/bdini13/unifi-announcer?display_name=tag&sort=semver)](https://github.com/bdini13/unifi-announcer/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue)](docs/HOME_ASSISTANT.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Local text-to-speech, preset tones, Home Assistant control, and MCP tools for UniFi Protect Smart Chimes.**

UniFi Announcer turns a UniFi Protect Smart Chime into a flexible LAN announcement endpoint. It synthesizes speech with Piper or Edge TTS, creates/reuses Protect ringtone objects, and asks Protect to play them on one chime or a named group.

Home Assistant users get a native HACS-compatible integration. AI-agent users can enable an optional Streamable HTTP MCP endpoint. REST, MQTT, and local Protect-event rules remain available for custom automation.

> [!IMPORTANT]
> UniFi Protect's local API is undocumented and may change. This project has been tested with Protect 7.2.105 and Smart Chime firmware 1.7.20. See [Compatibility](docs/COMPATIBILITY.md) before upgrading firmware.

> [!NOTE]
> The Home Assistant and MCP interfaces are new in the v2.1 beta. Native Home Assistant `tts.speak` / `media-source://` audio ingestion is planned for v2.2; v2.1 supports native notify actions plus text and preset `media_player.play_media`.

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

All production playback goes through Protect. Home Assistant and MCP are thin interfaces over the same dispatcher; they do not contain second playback implementations or receive UniFi device credentials.

## Requirements

- UniFi console running Protect, such as UDM Pro, UDM Pro SE, CloudKey+, or UNVR
- At least one adopted UniFi Protect Smart Chime
- Local UniFi OS account with access to Protect; SSO-only accounts do not work
- Docker Engine with Docker Compose
- TTS engine:
  - [Wyoming Piper](https://github.com/rhasspy/wyoming-piper), recommended for local TTS
  - Edge TTS with internet access

Home Assistant and MCP are optional.

# Quick start

## 1. Start UniFi Announcer

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

Start the service:

```bash
docker compose up -d --build
docker compose logs -f unifi-announcer
```

Persistent data defaults to `./data`. To use another host path, set `DATA_PATH`, for example:

```env
DATA_PATH=/srv/unifi-announcer/data
```

Verify health:

```bash
curl -fsS http://<announcer-host-or-ip>:8095/health
```

A healthy response contains `"status":"ok"`. Piper may be offline during startup; non-TTS controls remain available.

# Home Assistant — recommended setup

UniFi Announcer includes a native HACS-compatible custom integration.

## Install through HACS as a custom repository

1. Open **HACS** in Home Assistant.
2. Add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
3. Install **UniFi Announcer**.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → UniFi Announcer**.
6. Enter your Announcer URL, such as `http://announcer.local:8095`.
7. Enter `APP_API_KEY` if one is configured.

The setup flow validates `/health`, `/version`, and `/auth/check`; it does **not** play audio during setup.

For manual installation, copy `custom_components/unifi_announcer` into `/config/custom_components/` and restart Home Assistant.

See the full [Home Assistant documentation](docs/HOME_ASSISTANT.md).

## Announce through a notify entity

Each physical chime and configured group gets a notify entity:

```yaml
action: notify.send_message
target:
  entity_id: notify.unifi_announcer_kitchen
data:
  message: "Dinner is ready"
```

## Advanced announcement controls

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

Supported advanced fields include `message`, `target`, `volume`, `repeat_times`, `profile`, `priority`, and `dedupe_key`.

## Media player

Text:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.unifi_announcer_kitchen
data:
  media_content_type: text
  media_content_id: "The laundry is finished"
```

Preset:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.unifi_announcer_kitchen
data:
  media_content_type: unifi-announcer/preset
  media_content_id: package-delivered
```

The media player intentionally does not pretend the Smart Chime is a normal streaming speaker: no pause, seek, fake playback position, or fake persistent transport state is advertised.

Native `tts.speak` media-source ingestion is planned for v2.2.

# MCP — optional AI-agent interface

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

## MCP tools

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

See [MCP documentation](docs/MCP.md) for Hermes configuration and architecture details.

# REST examples

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

# Multiple chimes and groups

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

# MQTT and local rules

MQTT remains optional. Set `MQTT_URL`, `MQTT_USERNAME`, and `MQTT_PASSWORD` to enable discovery. See [MQTT documentation](docs/MQTT.md).

Local rules can react directly to Protect events without a Home Assistant round trip. See [Rules documentation](docs/RULES.md).

# Important configuration

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
| `APP_API_KEY` | empty | Protect REST write routes with `X-API-Key` |
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

# API summary

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Cached component health |
| `GET` | `/version` | Service and compatibility details |
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

# Playback behavior

Commands return a canonical disposition:

- `played` — all selected chimes played the request
- `suppressed` — quiet-hours policy suppressed it
- `deduped` — duplicate rejected inside the configured window
- `dropped` — queue policy dropped it
- `partial` — mixed results across targets
- `failed` — playback failed

Home Assistant, REST, MQTT, local rules, and MCP all reuse the same dispatcher semantics.

# Caching and safety

- Repeated text uses a disk MP3 cache.
- Ringtone IDs live in one in-memory `RingtoneIndex`.
- Simultaneous cold requests for the same phrase share ringtone creation.
- Dynamic TTS records are bounded by `MAX_DYNAMIC_TRACKS`.
- Before creating a ringtone, the service preserves headroom under `MAX_TOTAL_RINGTONES` and only evicts service-owned dynamic tracks.
- Presets, built-ins, and user-created tones are not dynamic-cleanup candidates.
- Destructive direct chime endpoints are blocked before network I/O.

See [Track registry documentation](docs/TRACKS.md) and [Playback policy](docs/POLICY.md).

# Documentation

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

# Security

Keep UniFi credentials and API keys out of Git. Store them in `.env`, Docker secrets, Home Assistant config entries, or another local secret manager.

Do **not** expose UniFi Announcer or its MCP endpoint directly to the public internet. Use a VPN or deliberately configured authenticated reverse proxy for remote access.

The public repository intentionally excludes deployment-specific credentials, certificate fingerprints, raw authentication research, and private support data.

# Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -W error -m pytest -q
.venv/bin/ruff check .
python3 -m compileall -q app custom_components
```

Tests use mocks and sanitized fixtures; public CI does not contact live UniFi equipment or play sound.

# Release status

- `v2.0.0` — stable local MVP reliability release
- `v2.1.0-beta.1` — Home Assistant + MCP public beta
- `v2.2.0` — planned native Home Assistant `tts.speak` / binary media ingestion and optional SSE integration

See the [Releases page](https://github.com/bdini13/unifi-announcer/releases).

# License

MIT

Unofficial community project; not affiliated with or endorsed by Ubiquiti.