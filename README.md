# UniFi Announcer

[![CI](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml)
[![HA validation](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml)
[![Stable](https://img.shields.io/badge/stable-v2.1.5-blue)](https://github.com/bdini13/unifi-announcer/releases/tag/v2.1.5)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue)](docs/HOME_ASSISTANT.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Turn a UniFi Protect Smart Chime into a local, programmable announcement speaker.**

UniFi Announcer is a self-hosted service for text-to-speech announcements, reusable spoken presets, buzzer/default playback, queues, quiet hours, Home Assistant, REST/MQTT, and optional MCP tools for UniFi Protect Smart Chimes.

It uses Piper or Edge TTS to synthesize speech, caches audio on the Announcer host, overwrites one of two persistent service-owned dynamic TTS slots on each target Smart Chime, and asks UniFi Protect to play the slot. Presets remain persistent Protect ringtones. Home Assistant and MCP are thin interfaces over the same announcement dispatcher.

> [!IMPORTANT]
> UniFi Protect's local interfaces used by this project are undocumented and may change. The validated feature set was physically tested with Protect 7.2.105 and Smart Chime firmware 1.7.20. See [Compatibility](docs/COMPATIBILITY.md) before upgrading firmware.
>
> UniFi Announcer is an unofficial community project and is not affiliated with or endorsed by Ubiquiti.

> [!WARNING]
> `v2.1.0-beta.2` and earlier can leave device-side ringtone artifacts when many unique TTS phrases are used. Stable v2.1 uses exactly two service-owned dynamic TTS slots instead. Upgrade older betas before using conversational or other high-cardinality TTS workloads.

> [!NOTE]
> Native Home Assistant `tts.speak` / `media-source://` ingestion is planned for v2.2. Current stable releases support native notify actions plus text and preset `media_player.play_media`.

## Why this exists

Home Assistant's native UniFi Protect integration already exposes Smart Chimes as Protect accessories and is the right integration for normal Protect device state and configuration.

What it does not provide is a general-purpose announcement layer: there is no native way to hand a Smart Chime arbitrary text such as "Dinner is ready," synthesize the speech locally, efficiently reuse device storage, target named groups, or apply announcement-specific queueing and policy.

UniFi Announcer fills that gap while keeping Protect in the playback path. It is designed to **complement, not replace, Home Assistant's native UniFi Protect integration**.

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
| Multiple chimes and named groups | 🧪 Automated coverage; multi-device physical validation pending |
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

For arbitrary TTS:

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

- UniFi console running Protect, such as a UDM Pro, UDM Pro SE, CloudKey+, or UNVR
- At least one adopted UniFi Protect Smart Chime
- A local UniFi OS account with the Protect permissions required by the service; SSO-only accounts do not work
- Docker Engine with Docker Compose
- For arbitrary TTS, one TTS engine:
  - [Wyoming Piper](https://github.com/rhasspy/wyoming-piper), recommended for local TTS
  - Edge TTS with internet access
- For arbitrary TTS: a current Smart Chime per-device adoption credential maintained outside this project and supplied through `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE`

There is no supported public retrieval workflow for that undocumented device credential. UniFi Announcer does not extract it from the console. If you do not already have a lawful, authorized way to maintain it, configure `TTS_ENGINE=none` and use buzzer/default/preset playback only. Do not enable console or device SSH, query internal databases, or weaken console security solely for this project.

Home Assistant, MQTT, and MCP are optional.

## Quick start

### 1. Clone and create a private configuration file

```bash
git clone https://github.com/bdini13/unifi-announcer.git
cd unifi-announcer
git checkout v2.1.5
install -m 600 .env.example .env
```

Create a **local** UniFi console account in **Admins & Users** and grant it only the Protect permissions the service needs to view chimes and manage ringtones.

If you do not already know the Protect chime ID, this temporary shell session can list chimes without putting the UniFi password into shell history:

```bash
read -r -p "UniFi console URL (for example https://192.0.2.1): " UNIFI_HOST
read -r -p "Local UniFi username: " UNIFI_USERNAME
read -r -s -p "Local UniFi password: " UNIFI_PASSWORD
echo
export UNIFI_USERNAME UNIFI_PASSWORD
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

python3 -c 'import json,os; print(json.dumps({"username":os.environ["UNIFI_USERNAME"],"password":os.environ["UNIFI_PASSWORD"],"remember":False}))' | \
  curl -ksS -c "$COOKIE_JAR" \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "$UNIFI_HOST/api/auth/login" >/dev/null

curl -ksS -b "$COOKIE_JAR" \
  "$UNIFI_HOST/proxy/protect/api/chimes"

rm -f "$COOKIE_JAR"
trap - EXIT
unset UNIFI_USERNAME UNIFI_PASSWORD
```

Alternatively, retrieve the chime ID with your normal authorized Protect tooling and skip the temporary login example entirely.

Edit `.env` with your console details and chime ID:

```env
UNIFI_HOST=https://<your-unifi-console-host-or-ip>
UNIFI_USERNAME=<local-unifi-username>
UNIFI_PASSWORD=<local-unifi-password>
UNIFI_VERIFY_SSL=false

CHIME_ID=<protect-chime-id>

# Safe baseline: preset/default/buzzer playback without direct-device credentials.
TTS_ENGINE=none

# Advanced arbitrary TTS only when you already maintain the device credential:
# CHIME_DIRECT_PASSWORD=<current-device-adoption-credential>
# TTS_ENGINE=piper
PIPER_URL=tcp://<piper-host-or-ip>:10200
PIPER_SYNTH_TIMEOUT=15

HOST_PORT=8095
CONTAINER_NAME=unifi-announcer
```

`APP_API_KEY` is required: write and detailed diagnostic routes fail closed without it. Generate a unique key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add it to `.env`:

```env
APP_API_KEY=<generated-key>
```

Keep `.env` private and confirm its mode:

```bash
chmod 600 .env
ls -l .env
```

### 2. Start the service

```bash
docker compose up -d --build
docker compose logs -f unifi-announcer
```

Persistent data defaults to the Docker-managed `unifi-announcer-data` volume, which is writable by the non-root container user without host preparation.

To use a host bind mount instead, set `DATA_PATH` in `.env` and make it writable by container UID/GID `1000:1000`:

```bash
sudo mkdir -p /srv/unifi-announcer/data
sudo chown -R 1000:1000 /srv/unifi-announcer/data
printf '\nDATA_PATH=/srv/unifi-announcer/data\n' >>.env
```

Verify health, version, and fixed-slot readiness:

```bash
export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
curl -fsS "${AUTH[@]}" http://<announcer-host-or-ip>:8095/tts/slots/status
curl -fsS "${AUTH[@]}" http://<announcer-host-or-ip>:8095/tts/cache/status
```

With arbitrary TTS configured, a healthy fixed-slot deployment reports `"mode":"two_slot_overwrite"`, `"slot_count":2`, and `"ready":true`. A credential-free `TTS_ENGINE=none` installation should not expect dynamic-slot readiness.

## Home Assistant — recommended setup

> [!IMPORTANT]
> **The HACS integration is a client for the Docker service above.** Install and start the UniFi Announcer backend first. HACS does not replace or run the backend.

### Install through HACS as a custom repository

1. Start and verify the UniFi Announcer Docker service.
2. Open **HACS** in Home Assistant.
3. Add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
4. Select the latest stable release.
5. Install **UniFi Announcer**.
6. Restart Home Assistant.
7. Open **Settings → Devices & services → Add integration → UniFi Announcer**.
8. Enter the Announcer URL, such as `http://announcer.local:8095`.
9. Enter the required `APP_API_KEY`.

The setup flow validates `/health`, `/version`, and `/auth/check`; it does **not** play audio during setup. If the application API key later changes, Home Assistant requests reauthentication rather than requiring the integration to be deleted.

For manual installation, copy `custom_components/unifi_announcer` into `/config/custom_components/` and restart Home Assistant. The Docker backend is still required.

See [Home Assistant documentation](docs/HOME_ASSISTANT.md) for the complete entity and action model.

### Notify entity

```yaml
action: notify.send_message
target:
  entity_id: notify.unifi_announcer_kitchen_announcements
data:
  message: "Dinner is ready"
```

Select the actual notify entity from Home Assistant's UI; generated entity IDs can vary with device names.

### Advanced announcement action

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

Supported fields include `message`, `target`, `volume`, `repeat_times`, `profile`, `priority`, and `dedupe_key`. Volume `0` is valid.

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

The integration intentionally does not pretend the Smart Chime is a normal streaming speaker: no pause, seek, fake playback position, or fake persistent transport state is advertised.

### Current HA limitations

- One UniFi Announcer integration instance is supported in v2.1.
- Native `tts.speak` and binary/media-source ingestion are planned for v2.2.
- Queue depth is exposed per physical chime; groups do not expose a fake aggregate queue-depth sensor.
- Changes to `CHIMES_CONFIG` or `GROUPS_CONFIG` require reloading/restarting the integration before entity topology is rebuilt.
- Arbitrary TTS requires fixed-slot readiness and current direct-device credentials on every target chime.
- Multi-chime behavior is covered by automated tests, but the stable v2.1 feature set was physically validated with only one physical Smart Chime; treat groups as experimental until independent multi-device playback reports are available.
- MCP is disabled by default and independent of Home Assistant.

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

Authentication uses a dedicated bearer token:

```text
Authorization: Bearer ***
```

`MCP_API_KEY` is intentionally separate from `APP_API_KEY`. `MCP_ALLOWED_HOSTS` should include the exact LAN hostname/IP MCP clients use; DNS-rebinding protection remains enabled.

Read-only MCP tools include `get_status`, `list_chimes`, `list_presets`, `get_recent_events`, and `get_queue_status`. Playback tools include `announce`, `play_preset`, `play_default`, and `buzzer`.

The MCP surface deliberately excludes credential retrieval, raw Protect administration, reboot/reset/adoption, arbitrary direct staging, firmware research, and arbitrary URL/file playback.

See [MCP documentation](docs/MCP.md).

## REST examples

Set reusable shell variables:

```bash
export ANNOUNCER_URL="http://<announcer-host-or-ip>:8095"
export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")
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

FastAPI's interactive REST schema is available at `http://<announcer-host-or-ip>:8095/docs` on your trusted network.

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

Each physical chime has its own bounded queue. Group members execute concurrently, and one failed member does not prevent healthy members from playing. Multi-chime behavior has automated coverage but still needs independent physical multi-device validation.

## MQTT and local rules

MQTT remains optional. Set `MQTT_URL`, `MQTT_USERNAME`, and `MQTT_PASSWORD` to enable discovery. See [MQTT documentation](docs/MQTT.md).

Local rules can react directly to Protect events without a Home Assistant round trip. See [Rules documentation](docs/RULES.md).

## Upgrade to v2.1.5

Keep the existing `.env` and persistent data. New installations default to the project-scoped Docker volume, while explicit `DATA_PATH` bind mounts remain supported.

Older installs that used the former implicit `./data` bind mount may have no `DATA_PATH` line. Before upgrading, preserve that location explicitly:

```bash
if test -d ./data && ! grep -q '^DATA_PATH=' .env; then
  printf '\nDATA_PATH=./data\n' >>.env
fi
docker compose config | grep -A4 '/data'
```

Confirm the rendered `/data` source is the expected existing directory before starting the new image. **Do not delete `track_registry.json` before upgrading**: it is ownership evidence used to conservatively migrate older dynamic artifacts.

```bash
cd unifi-announcer
git fetch --tags
git checkout v2.1.5
docker compose up -d --build
```

Then verify:

```bash
export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
curl -fsS "${AUTH[@]}" http://<announcer-host-or-ip>:8095/tts/slots/status
curl -fsS "${AUTH[@]}" http://<announcer-host-or-ip>:8095/tts/cache/status
```

With arbitrary TTS configured, slot status should show exactly two persistent slots and `ready: true`. Legacy service-owned identities are cleaned only when ownership is proven; ambiguous artifacts are retained and reported.

## Roll back

Back up both `.env` and the actual `/data` mount before changing release tags. These commands discover the source mounted by the current container, so they work with both Docker named volumes and `DATA_PATH` bind mounts:

```bash
umask 077
mkdir -p -m 700 backups
STAMP=$(date +%Y%m%d-%H%M%S)
CONTAINER_ID=$(docker compose ps -aq unifi-announcer)
DATA_SOURCE=$(docker inspect "$CONTAINER_ID" \
  --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')
test -n "$DATA_SOURCE"
docker compose stop unifi-announcer
cp .env "backups/env-$STAMP"
chmod 600 "backups/env-$STAMP"
docker run --rm \
  -e BACKUP_UID="$(id -u)" -e BACKUP_GID="$(id -g)" \
  -v "$DATA_SOURCE:/data:ro" \
  -v "$PWD/backups:/backup" \
  alpine:3.22 sh -c \
  'set -eu; file="/backup/data-'"$STAMP"'.tgz"; tar -C /data -czf "$file" .; chown "$BACKUP_UID:$BACKUP_GID" "$file"; chmod 600 "$file"'
tar -tzf "backups/data-$STAMP.tgz" >/dev/null
sha256sum "backups/data-$STAMP.tgz" >"backups/data-$STAMP.tgz.sha256"
chmod 600 "backups/data-$STAMP.tgz.sha256"
```

Retain `track_registry.json` in the backup: it is ownership evidence for dynamic TTS slots. Do not delete or hand-edit it.

To roll code back while preserving compatible current data:

```bash
git fetch --tags
git checkout <previous-tag>
docker compose up -d --build
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
```

If compatibility is unknown or the previous release requires older data, validate and extract the backup into a **new** restore directory. The current volume or bind mount is never erased:

```bash
docker compose stop unifi-announcer
sha256sum -c backups/data-<timestamp>.tgz.sha256
tar -tzf backups/data-<timestamp>.tgz >/dev/null
RESTORE_DIR="$PWD/backups/restore-test-<timestamp>"
install -d -m 700 "$RESTORE_DIR"
docker run --rm \
  -v "$RESTORE_DIR:/restore" \
  -v "$PWD/backups:/backup:ro" \
  alpine:3.22 sh -c \
  'set -eu; tar -C /restore -xzf /backup/data-<timestamp>.tgz; chown -R 1000:1000 /restore'
test -r "$RESTORE_DIR/track_registry.json" || test ! -e "$RESTORE_DIR/track_registry.json"
cp backups/<saved-env-file> .env
chmod 600 .env
printf '\nDATA_PATH=%s\n' "$RESTORE_DIR" >>.env
git checkout <previous-tag>
docker compose up -d --build
```

Verify the absolute `DATA_PATH` at the end of `.env` before starting the restored container.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UniFi Announcer does not appear in HA | Backend not running or old HACS version installed | Start Docker backend; select latest stable integration; reinstall/restart HA |
| HA reports invalid API key | `APP_API_KEY` changed or mismatches | Complete the integration's reauthentication flow |
| Buttons/presets work but arbitrary TTS fails | Fixed TTS slots are not ready | Check `/tts/slots/status` with `X-API-Key`; verify current direct-device credential and chime reachability |
| Slot status reports ownership drift | Physical slot metadata no longer matches proof | Stop TTS and reconcile; do not force or guess a slot |
| Piper synthesis fails | Piper is unavailable | Check `PIPER_URL` and the Piper service |
| MCP returns HTTP 401 | Bearer key mismatch | Check `MCP_API_KEY` and Authorization header |
| MCP returns HTTP 421 | Host not allowlisted | Add the hostname/IP to `MCP_ALLOWED_HOSTS` and recreate the container |
| Presets are missing | Protect read failed or integration state is stale | Check `/presets`, then reload the integration |
| New chime/group is absent in HA | Entity topology predates config change | Reload/restart the integration |

## Playback and safety model

Commands return a canonical disposition: `played`, `suppressed`, `deduped`, `dropped`, `partial`, or `failed`. Home Assistant, REST, MQTT, local rules, and MCP all reuse the same dispatcher semantics.

Dynamic TTS safety properties:

- repeated text uses a content-addressed disk MP3 cache on the Announcer host;
- dynamic TTS consumes exactly two persistent service-owned device slots per Announcer installation;
- new phrases overwrite those two slots instead of creating new Protect ringtone identities;
- slot reuse is lease/guard based so a slot is not overwritten while prior playback may still depend on it;
- before every direct overwrite, the service rechecks the exact physical slot against persisted ownership evidence;
- unknown, built-in, user-created, and preset tracks are never dynamic-slot overwrite candidates;
- destructive direct chime endpoints are blocked before network I/O.

See [Track registry documentation](docs/TRACKS.md) and [Playback policy](docs/POLICY.md).

## Validation boundary

The v2.1.0 feature set was physically validated on one Smart Chime for alternating fixed TTS slots, preset/default/buzzer playback, restart persistence, and service status. A separate 100-unique-message automated regression kept dynamic Protect identities fixed at two and preserved synthetic per-device slot mappings. Automated coverage also includes concurrency and deduplication.

v2.1.1, v2.1.4, and v2.1.5 are patch releases over the same playback architecture. Multi-chime/group behavior has automated fixture coverage but has **not** been physically validated with multiple Smart Chimes. No synchronized microphone benchmark was available, so the project does not claim measured acoustic latency.

CI runs the core suite, Home Assistant custom-component tests, Ruff, compile checks, Compose validation, Docker build, HACS validation, and Hassfest. Public CI uses sanitized fixtures and does not contact live UniFi equipment or play audio.

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
- [v2.1.5 release notes](docs/RELEASE_NOTES_v2.1.5.md)
- [v2.1.4 release notes](docs/RELEASE_NOTES_v2.1.4.md)
- [v2.1.1 release notes](docs/RELEASE_NOTES_v2.1.1.md)
- [v2.1.0 release notes](docs/RELEASE_NOTES_v2.1.0.md)

## Support

Use [GitHub Issues](https://github.com/bdini13/unifi-announcer/issues) for reproducible bugs and focused feature requests. Include the Announcer version, Protect version, Smart Chime model/firmware, exact reproduction steps, and whether evidence came from automated fixtures or physical devices. Redact credentials, private addresses, device IDs, certificate details, support logs, and private audio.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a public issue. Contributions are covered by [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

This is a community project with best-effort support.

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

Home Assistant integration validation uses its separate requirements file:

```bash
python3.14 -m venv .venv-ha
.venv-ha/bin/pip install -r requirements-ha-test.txt
.venv-ha/bin/python -m pytest -q tests_ha
```

CI also runs HACS validation and Hassfest.

## AI-assisted development

This project was developed with the assistance of AI coding and research tools for implementation, debugging, code review, test development, documentation, and research. Architecture choices, release decisions, safety boundaries, and physical-device validation remain human-directed.

## Release status

- **Stable:** `v2.1.5` — verifies live physical-slot contents before cached playback
- **Planned:** `v2.2.0` — native Home Assistant `tts.speak`, binary media ingestion, and optional SSE integration

See the [Roadmap](ROADMAP.md) and [Releases page](https://github.com/bdini13/unifi-announcer/releases).

## License

MIT

Unofficial community project; not affiliated with or endorsed by Ubiquiti.
