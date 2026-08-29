# UniFi Announcer

[![CI](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml)
[![HA validation](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml)
[![Stable](https://img.shields.io/badge/stable-v2.1.0-blue)](https://github.com/bdini13/unifi-announcer/releases/tag/v2.1.0)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue)](docs/HOME_ASSISTANT.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Transforms a UniFi Smart Chime into a local Text-To-Speech (TTS) announcement speaker.**

UniFi Announcer provides local text-to-speech, reusable spoken presets, multi-chime groups, Home Assistant controls, REST/MQTT interfaces, and optional MCP tools for UniFi Protect Smart Chimes.

It synthesizes speech with Piper or Edge TTS, caches it on the Announcer host, overwrites one of two persistent service-owned TTS slots on each target Smart Chime, and asks Protect to play that slot. Presets remain persistent Protect ringtones. Home Assistant and MCP remain thin interfaces over the same announcement engine.

> [!IMPORTANT]
> UniFi Protect's local API is undocumented and may change. This project has been tested with Protect 7.2.105 and Smart Chime firmware 1.7.20. See [Compatibility](docs/COMPATIBILITY.md) before upgrading firmware.
>
> UniFi Announcer is an unofficial community project and is not affiliated with or endorsed by Ubiquiti.

> [!WARNING]
> `v2.1.0-beta.2` and earlier can leave device-side ringtone artifacts when many unique TTS phrases are used. This is especially easy to trigger with conversational AI/MCP workloads. `v2.1.0` replaces per-phrase device allocation with exactly two service-owned overwrite slots. Upgrade older betas before using high-cardinality TTS workloads.

> [!NOTE]
> Native Home Assistant `tts.speak` / `media-source://` audio ingestion is planned for v2.2; v2.1 supports native notify actions plus text and preset `media_player.play_media`.

## Why this exists

Home Assistant's native [UniFi Protect integration](https://www.home-assistant.io/integrations/unifiprotect/) already supports Smart Chimes as Protect accessories. It exposes useful basic controls such as manually triggering a chime, setting chime volume, reporting the last ring time, rebooting the device, and pairing doorbells.

What it does **not** provide is a general-purpose announcement layer for Smart Chimes. There is no native way to hand the chime arbitrary text such as "Dinner is ready," synthesize that speech locally, reuse it efficiently, target several Smart Chimes as a group, or apply announcement-specific queueing and policy.

UniFi Announcer fills that gap while keeping Protect in the playback path. It is designed to **complement, not replace, Home Assistant's native UniFi Protect integration**: keep the native integration for normal Protect device state/configuration and add UniFi Announcer for spoken announcements and higher-level automation.

## Choose your setup

| Goal | Start here |
|---|---|
| Make a Smart Chime speak (advanced) | [Docker quick start](#quick-start) |
| Use Home Assistant | [HACS setup](#home-assistant-recommended-setup) |
| Give an AI agent access | [MCP setup](#mcp-optional-ai-agent-interface) |
| Build custom automation | [REST examples](#rest-examples) |
| React directly to Protect events | [Local rules](docs/RULES.md) |

## What works today

| Capability | Status |
|---|---|
| Arbitrary text announcements | ⚠️ Advanced; requires a separately obtained device credential |
| Piper local TTS | ✅ Stable |
| Edge TTS | ✅ Supported |
| Reusable preset tones | ✅ Stable |
| Buzzer and assigned-default playback | ✅ Stable |
| Multiple chimes and named groups | ✅ Stable |
| Quiet hours, priority, dedupe, bounded queues | ✅ Stable |
| Two fixed service-owned dynamic TTS slots | ✅ Stable |
| Bounded host-side TTS MP3 cache | ✅ Stable |
| Home Assistant HACS integration | ✅ Stable |
| HA `notify.send_message` | ✅ Stable |
| HA text/preset `media_player.play_media` | ✅ Stable |
| MCP server and playback tools | ✅ Stable |
| MQTT discovery | ✅ Supported |
| Protect event rules | 🧪 Experimental |
| Native HA `tts.speak` media ingestion | ⏭️ v2.2 |

## Architecture

```text
Home Assistant ─┐
REST            ├──► AnnouncementDispatcher ─► Protect play command ─► Smart Chime
MQTT            │            ▲                        ▲
MCP ────────────┤            │                        │
Protect rules ──┘       queue / policy          fixed TTS slot ID
```

For arbitrary TTS in v2.1:

```text
text
  -> Piper or Edge TTS
  -> bounded MP3 cache on Announcer host
  -> overwrite UA-TTS-1 or UA-TTS-2 on target Smart Chime(s)
  -> Protect play-speaker with that persistent ringtone ID
  -> Smart Chime
```

The playback command still goes through Protect. Direct Smart Chime HTTPS is used only to overwrite an exact, previously proven UniFi-Announcer-owned TTS slot. The service never guesses a physical slot and never overwrites built-in, user-created, preset, or unknown tracks.

## Requirements

- UniFi console running Protect, such as UDM Pro, UDM Pro SE, CloudKey+, or UNVR
- At least one adopted UniFi Protect Smart Chime
- Local UniFi OS account with access to Protect; SSO-only accounts do not work
- Docker Engine with Docker Compose
- For arbitrary TTS, one TTS engine:
  - [Wyoming Piper](https://github.com/rhasspy/wyoming-piper), recommended for local TTS
  - Edge TTS with internet access
- For v2.1 arbitrary TTS: a current Smart Chime per-device adoption credential,
  obtained and maintained outside this project, supplied through
  `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE`

There is no supported public retrieval workflow for that undocumented device
credential. UniFi Announcer does not extract it from the console. If you do not
already have a lawful, authorized way to maintain it, configure `TTS_ENGINE=none`
and use buzzer/default/preset playback only. Do not enable console or device SSH,
query internal databases, or weaken console security solely for this project.

Home Assistant and MCP are optional.

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/bdini13/unifi-announcer.git
cd unifi-announcer
git checkout v2.1.0
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

# Safe public baseline; preset/default/buzzer playback works without direct credentials.
TTS_ENGINE=none

# Advanced arbitrary TTS only, when you already maintain the device credential:
# CHIME_DIRECT_PASSWORD=<current-device-adoption-credential>
# TTS_ENGINE=piper
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

Persistent data defaults to the Docker-managed `unifi-announcer-data` volume,
which is writable by the non-root container user without host preparation.

To use a host bind mount instead, replace the Compose volume source with the
desired absolute path and make it writable by container UID/GID `1000:1000`:

```bash
sudo mkdir -p /srv/unifi-announcer/data
sudo chown -R 1000:1000 /srv/unifi-announcer/data
```

Verify health, version, and fixed-slot readiness:

```bash
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
curl -fsS http://<announcer-host-or-ip>:8095/tts/slots/status
curl -fsS http://<announcer-host-or-ip>:8095/tts/cache/status
```

A healthy fixed-slot deployment reports `"mode":"two_slot_overwrite"`, `"slot_count":2`, and `"ready":true`. Piper may be offline during startup; non-TTS controls remain available.

## Home Assistant — recommended setup

UniFi Announcer includes a native HACS-compatible custom integration for Home Assistant 2026.3+.

> [!WARNING]
> **Upgrading from an older v2.1 beta:** Use `v2.1.0` or later. Beta.2 can leave device-side artifacts under high-cardinality TTS workloads; v2.1.0 uses the fixed two-slot design introduced in beta.3.

### Install through HACS as a custom repository

1. Open **HACS** in Home Assistant.
2. Add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
3. Select the latest stable release.
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

### v2.1 limitations

- Home Assistant supports one UniFi Announcer integration instance in v2.1.
- Native `tts.speak` and binary/media-source ingestion are deferred to v2.2.
- Queue depth is exposed per physical chime; groups intentionally do not expose a fake aggregate queue-depth sensor.
- Changes to `CHIMES_CONFIG` or `GROUPS_CONFIG` require reloading or restarting the Home Assistant integration before its entity topology is rebuilt.
- Arbitrary TTS requires fixed-slot readiness and current direct-device credentials on every target chime.
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

`get_status` includes fixed-slot and TTS-cache status in v2.1. Internal `UA-TTS-*` slot identities are excluded from `list_presets`.

The MCP surface deliberately excludes credential retrieval, raw Protect administration, reboot/reset/adoption, arbitrary direct staging, firmware research, and arbitrary URL/file playback.

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

Each physical chime has its own bounded queue. Group members execute concurrently, and one failed member does not prevent healthy members from playing. The logical TTS slot number is shared for an announcement, while each physical Smart Chime retains its own proven device-slot mapping.

## MQTT and local rules

MQTT remains optional. Set `MQTT_URL`, `MQTT_USERNAME`, and `MQTT_PASSWORD` to enable discovery. See [MQTT documentation](docs/MQTT.md).

Local rules can react directly to Protect events without a Home Assistant round trip. See [Rules documentation](docs/RULES.md).

## Upgrade to v2.1.0

Keep your existing `.env` and persistent `DATA_PATH`. **Do not delete `track_registry.json` before this upgrade**: beta.3 uses ownership records to identify and conservatively migrate beta.2 dynamic artifacts.

```bash
cd unifi-announcer
git fetch --tags
git checkout v2.1.0
docker compose up -d --build
```

v2.1 additionally requires a current per-device Smart Chime credential for arbitrary TTS. Supply it through `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE` only if you already maintain it through an authorized external process. There is no supported public retrieval workflow, and UniFi Announcer does not retrieve it from Protect.

Then verify:

```bash
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
curl -fsS http://<announcer-host-or-ip>:8095/tts/slots/status
curl -fsS http://<announcer-host-or-ip>:8095/tts/cache/status
```

The slot status should show exactly two persistent slots and `ready: true`. Legacy service-owned NVR dynamic identities are cleaned only when ownership is proven. Ambiguous device artifacts are retained/reported rather than guessed at.

## Roll back

Back up both `.env` and `/data` before changing release tags. The commands below
handle the default Docker-managed `unifi-announcer-data` volume without exposing
credentials in command output:

```bash
mkdir -p backups
docker compose stop unifi-announcer
cp -p .env "backups/env-$(date +%Y%m%d-%H%M%S)"
docker run --rm \
  -v unifi-announcer-data:/data:ro \
  -v "$PWD/backups:/backup" \
  alpine:3.22 \
  tar -C /data -czf /backup/unifi-announcer-data.tgz .
```

Retain `track_registry.json` in the backup: it is ownership evidence for dynamic
TTS slots. Do not delete or hand-edit it.

To roll the application code back while preserving current data:

```bash
git fetch --tags
git checkout <previous-tag>
docker compose up -d --build
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
```

If the previous release is incompatible with the current data, stop the service
and restore the backup before starting it:

```bash
docker compose stop unifi-announcer
docker run --rm \
  -v unifi-announcer-data:/data \
  -v "$PWD/backups:/backup:ro" \
  alpine:3.22 \
  sh -c 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -C /data -xzf /backup/unifi-announcer-data.tgz'
cp -p backups/<saved-env-file> .env
docker compose up -d --build
```

The restore command replaces the volume contents. Verify that the backup exists
and that the target is the `unifi-announcer-data` volume before running it. For a
custom host bind mount, back up and restore that host directory instead.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UniFi Announcer does not appear in HA | HACS installed `v2.0.0` or an older beta | Select `v2.1.0` or later, reinstall, restart HA |
| HA reports invalid API key | `APP_API_KEY` changed or mismatches | Complete the integration's reauthentication flow |
| Buttons/presets work but arbitrary TTS fails | Fixed TTS slots are not ready | Check `/tts/slots/status`; verify current direct-device credential and chime reachability |
| Slot status reports ownership drift | Physical slot metadata no longer matches proof | Stop TTS and reconcile; do not force/guess a slot |
| Piper synthesis fails | Piper is unavailable | Check `PIPER_URL` and the Piper service |
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
| `CHIME_DIRECT_PASSWORD` | empty | Current device credential for fixed-slot dynamic TTS |
| `CHIME_CREDENTIAL_FILE` | empty | Optional externally refreshed device-credential file |
| `TTS_ENGINE` | `piper` | `piper`, `edge`, or `none`; use `none` for the safe credential-free baseline |
| `PIPER_URL` | none | Wyoming Piper endpoint |
| `TTS_CACHE_MAX_FILES` | `256` | Host-side cached TTS file ceiling |
| `TTS_CACHE_MAX_BYTES` | `268435456` | Host-side cached TTS byte ceiling |
| `APP_API_KEY` | empty | REST write routes with `X-API-Key` |
| `DATA_PATH` | `./data` | Host path mounted at `/data` |
| `VOLUME_DEFAULT` | `50` | Default request volume |
| `REPEAT_DEFAULT` | `1` | Default repeat count |
| `QUIET_HOURS` | empty | Suppression window such as `22:00-06:30` |
| `MAX_DYNAMIC_TRACKS` | `32` | Deprecated beta.2 legacy migration setting; device TTS is fixed at two slots |
| `MAX_TOTAL_RINGTONES` | `6` | Protect capacity guard for initial slot/preset provisioning |
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
| `GET` | `/presets` | List user-facing Protect ringtones; internal TTS slots hidden |
| `GET` | `/tts/slots/status` | Fixed dynamic TTS slot readiness and proven mappings |
| `GET` | `/tts/cache/status` | Host-side bounded TTS cache statistics |
| `POST` | `/announce` | Synthesize/cache text, overwrite an owned TTS slot, and play it |
| `POST` | `/buzzer` | Play hardware buzzer |
| `POST` | `/play-default` | Play assigned default ringtone |
| `PUT` | `/presets/{name}` | Create or replace a persistent preset |
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

- Repeated text uses a content-addressed disk MP3 cache on the Announcer host.
- The host cache is pruned independently toward `TTS_CACHE_MAX_FILES` and `TTS_CACHE_MAX_BYTES` as best-effort limits.
- Files that cannot be deleted remain counted, so `/tts/cache/status` may exceed either configured maximum until filesystem permissions or other deletion errors are corrected.
- Dynamic TTS consumes exactly two persistent service-owned device slots per Announcer installation.
- New unique phrases overwrite those two slots; they do not create new Protect ringtone identities after provisioning.
- Slot reuse is lease/guard based so a slot is not overwritten while prior playback may still depend on it.
- Before every direct overwrite, the service rechecks the exact physical slot against persisted ownership evidence.
- Unknown, built-in, user-created, and preset tracks are never dynamic-slot overwrite candidates.
- `MAX_TOTAL_RINGTONES` is used for provisioning/preset headroom, not routine dynamic message churn.
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
- [v2.1.0 release notes](docs/RELEASE_NOTES_v2.1.0.md)
- [v2.1.0-beta.1 release notes](docs/RELEASE_NOTES_v2.1.0-beta.1.md)
- [v2.1.0-beta.2 release notes](docs/RELEASE_NOTES_v2.1.0-beta.2.md)
- [v2.1.0-beta.3 release notes](docs/RELEASE_NOTES_v2.1.0-beta.3.md)

## Security

Keep UniFi credentials and API keys out of Git. Store them in `.env`, Docker secrets, Home Assistant config entries, or another local secret manager.

Do **not** expose UniFi Announcer or its MCP endpoint directly to the public internet. Use a VPN or deliberately configured authenticated reverse proxy for remote access.

Dynamic TTS requires a current device adoption credential solely for exact service-owned slot overwrite. The public service does not expose that credential, and MCP/Home Assistant do not receive it. Credential-extraction procedures and raw authentication research are intentionally not documented in the public repository.

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

CI also runs HACS validation and Hassfest. Tests use mocks and sanitized fixtures; public CI does not contact live UniFi equipment or play sound. The core suite includes a 100-unique-message regression asserting that dynamic TTS creates no Protect ringtone identities beyond the initial two slots.

## AI-assisted development

This project was developed with the assistance of AI coding and research tools. AI has been used for implementation, debugging, code review, test development, documentation, and research.

## Release status

- **Stable:** `v2.1.0` — fixed-slot dynamic TTS + Home Assistant + MCP
- **Planned:** `v2.2.0` — native Home Assistant `tts.speak`, binary media ingestion, and optional SSE integration

See the [Releases page](https://github.com/bdini13/unifi-announcer/releases).

## License

MIT

Unofficial community project; not affiliated with or endorsed by Ubiquiti.
