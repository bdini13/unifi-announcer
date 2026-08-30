# UniFi Announcer

[![CI](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml)
[![HA validation](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/validate-ha.yml)
[![Latest release](https://img.shields.io/github/v/release/bdini13/unifi-announcer?display_name=tag&label=stable)](https://github.com/bdini13/unifi-announcer/releases/latest)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-blue)](docs/HOME_ASSISTANT.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Turn a UniFi Protect Smart Chime into a local, programmable announcement speaker.**

UniFi Announcer is a self-hosted announcement service for UniFi Protect Smart Chimes. It adds text-to-speech, reusable spoken presets, buzzer/default playback, queues, quiet-hours policy, Home Assistant controls, REST/MQTT, and an optional MCP interface while keeping UniFi Protect in the actual playback path.

For arbitrary speech it synthesizes audio with Piper or Edge TTS, stores MP3s in a bounded host cache, overwrites one of exactly two persistent service-owned Smart Chime slots, then asks Protect to play that persistent ringtone ID. New phrases do **not** create a new Protect ringtone each time.

> [!IMPORTANT]
> UniFi Protect interfaces used by this project are undocumented and can change. The current v2.1 feature set has been physically validated on Protect 7.2.105 with Smart Chime firmware 1.7.20. Review [Compatibility](docs/COMPATIBILITY.md) before upgrading Protect or chime firmware.
>
> UniFi Announcer is an unofficial community project and is not affiliated with or endorsed by Ubiquiti.

> [!CAUTION]
> Arbitrary TTS requires a current per-device Smart Chime adoption credential that you already maintain through an authorized method. This project does **not** retrieve that credential and does not document enabling console/device SSH, querying internal UniFi databases, or weakening console security to obtain it. Without that credential, use `TTS_ENGINE=none`; preset/default/buzzer playback remains available.

> [!NOTE]
> Native Home Assistant `tts.speak` / `media-source://` ingestion is planned for v2.2. Stable v2.1 supports `notify.send_message`, text/preset `media_player.play_media`, buttons, selectors, sensors, and the `unifi_announcer.announce` action.

## Why this exists

Home Assistant's native UniFi Protect integration is the right place for normal Protect device state and configuration, but a Smart Chime is not exposed as a general announcement speaker. UniFi Announcer fills that gap without pretending the device is a normal streaming media player.

Typical uses include:

- "Dinner is ready" / "Garage door is still open" announcements;
- package, laundry, alarm, or door alerts;
- AI-generated spoken notifications;
- reusable presets and hardware buzzer actions;
- targeted chimes or named groups;
- Home Assistant, REST, MQTT, rules, or MCP clients sharing one dispatcher.

## What works today

| Capability | Status |
|---|---|
| Arbitrary text announcements | ⚠️ Advanced; requires separately maintained device credential |
| Piper local TTS | ✅ Stable |
| Edge TTS | ✅ Supported |
| Reusable preset tones | ✅ Stable |
| Buzzer and assigned-default playback | ✅ Stable |
| Two fixed service-owned dynamic TTS slots | ✅ Stable |
| Bounded host-side TTS cache | ✅ Stable |
| Quiet hours, priority, dedupe, bounded queues | ✅ Stable |
| Home Assistant HACS integration | ✅ Stable |
| HA `notify.send_message` | ✅ Stable |
| HA text/preset `media_player.play_media` | ✅ Stable |
| HA immediate playback-result sensor | ✅ v2.1.6 |
| REST API | ✅ Stable |
| MCP server and playback tools | ✅ Stable |
| MQTT discovery | ✅ Supported |
| Multiple chimes and named groups | 🧪 Automated coverage; multi-device physical validation pending |
| Protect event rules | 🧪 Experimental |
| Native HA `tts.speak` media ingestion | ⏭️ v2.2 |

## Architecture

```text
Home Assistant ─┐
REST            ├──► AnnouncementDispatcher ─► Protect play-speaker ─► Smart Chime
MQTT            │            ▲                         ▲
MCP ────────────┤            │                         │
Protect rules ──┘       queue / policy           fixed TTS slot ID
```

Arbitrary TTS follows this path:

```text
text
  -> Piper or Edge TTS
  -> bounded MP3 cache on Announcer host
  -> overwrite UA-TTS-1 or UA-TTS-2 on the target chime
  -> Protect play-speaker using the persistent ringtone ID
  -> Smart Chime
```

Direct Smart Chime HTTPS is used only to overwrite an **exact previously proven UniFi-Announcer-owned slot**. The service never guesses a physical slot and never treats built-in, user-created, preset, ambiguous, or unknown tracks as overwrite candidates.

## Requirements

- UniFi console running Protect, such as UDM Pro, UDM Pro SE, CloudKey+, or UNVR;
- at least one adopted UniFi Protect Smart Chime;
- a local UniFi OS account with only the Protect permissions the service needs;
- Docker Engine and Docker Compose;
- optional Home Assistant 2026.3+ for the HACS client;
- for arbitrary TTS, Piper or Edge TTS plus the separately maintained Smart Chime device credential described above.

Home Assistant, MQTT, rules, and MCP are optional. The Docker service is the source of truth.

## Quick start

### 1. Clone a pinned release and create private configuration

```bash
git clone https://github.com/bdini13/unifi-announcer.git
cd unifi-announcer
git checkout v2.1.6
install -m 600 .env.example .env
```

Create a **local** UniFi console account in **Admins & Users** and grant only the Protect access required to view chimes and manage ringtones.

If you do not already know the Protect chime ID, this temporary shell session lists chimes without placing the UniFi password in shell history:

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

curl -ksS -b "$COOKIE_JAR" "$UNIFI_HOST/proxy/protect/api/chimes"

rm -f "$COOKIE_JAR"
trap - EXIT
unset UNIFI_USERNAME UNIFI_PASSWORD
```

Alternatively, obtain the chime ID through your normal authorized Protect tooling and skip the temporary login example.

Edit `.env`:

```env
UNIFI_HOST=https://<your-unifi-console-host-or-ip>
UNIFI_USERNAME=<local-unifi-username>
UNIFI_PASSWORD=<local-unifi-password>
UNIFI_VERIFY_SSL=false

CHIME_ID=<protect-chime-id>

# Safe baseline: no arbitrary text TTS.
TTS_ENGINE=none

# Advanced arbitrary TTS only when you already maintain the device credential:
# CHIME_DIRECT_PASSWORD=<current-device-adoption-credential>
# TTS_ENGINE=piper
PIPER_URL=tcp://<piper-host-or-ip>:10200
PIPER_SYNTH_TIMEOUT=15

HOST_PORT=8095
CONTAINER_NAME=unifi-announcer
APP_API_KEY=<generate-a-unique-secret>
```

`APP_API_KEY` is required; write routes and detailed diagnostics fail closed without it. Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep `.env` private:

```bash
chmod 600 .env
ls -l .env
```

### 2. Start the service with exact build provenance

Pass the checked-out commit into the Docker build so `/version` and the image metadata identify the code that produced the container:

```bash
export GIT_SHA="$(git rev-parse HEAD)"
docker compose up -d --build
docker compose logs -f unifi-announcer
```

Persistent data defaults to the Docker-managed `unifi-announcer-data` volume, writable by the non-root container user.

To use a host bind mount instead:

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

With arbitrary TTS configured, healthy slot status reports `"mode":"two_slot_overwrite"`, `"slot_count":2`, and `"ready":true`. A credential-free `TTS_ENGINE=none` deployment should not expect dynamic-slot readiness.

You can also confirm the embedded image revision:

```bash
docker image inspect unifi-announcer:local \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

It should match `git rev-parse HEAD`.

## Home Assistant — recommended setup

> [!IMPORTANT]
> **The HACS integration is a client for the Docker service.** Install and start UniFi Announcer first. HACS does not replace or run the backend.

1. Start and verify the Docker service.
2. In **HACS**, add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
3. Select the latest stable release and install **UniFi Announcer**.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → UniFi Announcer**.
6. Enter the Announcer URL, such as `http://announcer.local:8095`, and `APP_API_KEY`.

The setup flow checks `/health`, `/version`, and `/auth/check`; it never plays audio during setup.

### Standard announcement

```yaml
action: notify.send_message
target:
  entity_id: notify.unifi_announcer_kitchen_announcements
data:
  message: "Dinner is ready"
```

### Advanced announcement action

```yaml
action: unifi_announcer.announce
data:
  message: "Garage door is still open"
  target: kitchen
  volume: 45
  repeat_times: 1
  priority: 50
  dedupe_key: garage-open
```

### Media player

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen_announcer
data:
  media_content_type: text
  media_content_id: "The laundry is finished"
```

For a preset use `media_content_type: unifi-announcer/preset` and the preset name as `media_content_id`.

### Playback result

Each target has a **Last playback result** sensor. In v2.1.6 it updates immediately after HA actions:

- `success` — the Announcer action completed with canonical dispatcher disposition `played`;
- `failure` — the request failed through the Announcer client/transport path;
- `suppressed`, `deduped`, `dropped`, or `partial` — intentional canonical dispatcher outcomes that are preserved rather than misreported as success.

See [Home Assistant documentation](docs/HOME_ASSISTANT.md) for the complete entity/action model and troubleshooting.

## MCP — optional AI-agent interface

Enable the Streamable HTTP MCP endpoint in `.env`:

```env
MCP_ENABLED=true
MCP_API_KEY=<generate-a-dedicated-secret>
MCP_ALLOWED_HOSTS=announcer.local,<announcer-lan-ip>
```

Recreate the service with provenance preserved:

```bash
export GIT_SHA="$(git rev-parse HEAD)"
docker compose up -d --build
```

Endpoint: `http://<announcer-host>:8095/mcp`

Authentication uses `Authorization: Bearer <MCP_API_KEY>`. Keep `MCP_API_KEY` separate from `APP_API_KEY`.

Read tools include `get_status`, `list_chimes`, `list_presets`, `get_recent_events`, and `get_queue_status`. Playback tools include `announce`, `play_preset`, `play_default`, and `buzzer`.

The MCP surface deliberately excludes credential retrieval, raw Protect administration, reboot/reset/adoption, arbitrary direct staging, firmware research, and arbitrary URL/file playback. See [MCP documentation](docs/MCP.md).

## REST examples

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

```env
CHIMES_CONFIG='[
  {"name":"kitchen","id":"<kitchen-chime-id>","direct_ip":"<optional-chime-ip>"},
  {"name":"upstairs","id":"<upstairs-chime-id>"}
]'
GROUPS_CONFIG='{"downstairs":["kitchen"],"whole_house":["kitchen","upstairs"]}'
```

Then target `whole_house` from REST/HA/MCP. Each physical chime has its own bounded queue and group members execute concurrently. Multi-chime behavior has automated coverage but still requires independent physical multi-device validation.

## MQTT and local rules

MQTT discovery remains optional; configure `MQTT_URL`, `MQTT_USERNAME`, and `MQTT_PASSWORD`. See [MQTT](docs/MQTT.md).

Local rules can react directly to Protect events without a Home Assistant round trip. See [Rules](docs/RULES.md).

## Upgrade to v2.1.6

Keep the existing `.env` and persistent `/data` state. Older installs that used the former implicit `./data` bind mount may have no `DATA_PATH` line. Preserve that source explicitly before upgrading:

```bash
if test -d ./data && ! grep -q '^DATA_PATH=' .env; then
  printf '\nDATA_PATH=./data\n' >>.env
fi
docker compose config | grep -A4 '/data'
```

Confirm the rendered `/data` source before starting the new image. **Do not delete `track_registry.json`**; it is ownership evidence used by conservative slot migration/reconciliation.

```bash
cd unifi-announcer
git fetch --tags
git checkout v2.1.6
export GIT_SHA="$(git rev-parse HEAD)"
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

For HA users, reload/restart Home Assistant after updating the custom integration, select a preset or send text, and verify **Last playback result** changes to `success` after audible playback.

## Roll back

Back up both `.env` and the actual `/data` mount before changing release tags. These commands discover the source mounted by the current container, so they work with Docker named volumes and `DATA_PATH` bind mounts:

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

Retain `track_registry.json` in the backup. Do not delete or hand-edit it.

To roll code back while preserving compatible current data:

```bash
git fetch --tags
git checkout <previous-tag>
export GIT_SHA="$(git rev-parse HEAD)"
docker compose up -d --build
curl -fsS http://<announcer-host-or-ip>:8095/health
curl -fsS http://<announcer-host-or-ip>:8095/version
```

If data compatibility is uncertain, validate and extract the backup into a **new** restore directory rather than erasing the current mount:

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
export GIT_SHA="$(git rev-parse HEAD)"
docker compose up -d --build
```

Verify the final `DATA_PATH` before starting the restored container.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UniFi Announcer does not appear in HA | Backend not running or old HACS version installed | Start Docker backend; select latest stable integration; reinstall/restart HA |
| HA reports invalid API key | `APP_API_KEY` changed or mismatches | Complete the integration reauthentication flow |
| HA button times out but direct slot test works | Backend older than v2.1.6 or stale Protect inventory behavior | Upgrade backend and HA client together; verify `/version`; inspect logs for slot sync/play-speaker result |
| Last playback result remains `unknown` after using a control | HA integration older than v2.1.6 or action never reached the integration | Update/restart HA integration, then retry a button/action |
| Buttons/presets work but arbitrary TTS fails | Fixed TTS slots are not ready | Check `/tts/slots/status` with `X-API-Key`; verify current direct-device credential and chime reachability |
| Slot status reports ownership drift | Physical slot metadata no longer matches proof | Stop TTS and reconcile; do not force or guess a slot |
| `/version` shows `git_sha: unknown` | Image was built without `GIT_SHA` | Rebuild with `export GIT_SHA="$(git rev-parse HEAD)"` |
| Piper synthesis fails | Piper unavailable | Check `PIPER_URL` and Piper service |
| MCP returns HTTP 401 | Bearer key mismatch | Check `MCP_API_KEY` and Authorization header |
| MCP returns HTTP 421 | Host not allowlisted | Add the client hostname/IP to `MCP_ALLOWED_HOSTS` and recreate the container |
| New chime/group is absent in HA | Entity topology predates config change | Reload/restart the integration |

## Playback and safety model

Commands use canonical dispositions: `played`, `suppressed`, `deduped`, `dropped`, `partial`, or `failed`. Home Assistant, REST, MQTT, local rules, and MCP reuse the same `AnnouncementDispatcher` semantics.

Dynamic TTS safety properties:

- repeated text uses a content-addressed bounded MP3 cache on the Announcer host;
- dynamic TTS consumes exactly two persistent service-owned slots per Announcer installation;
- new phrases overwrite those slots instead of creating new Protect ringtone identities;
- slot reuse is lease/guard based so a slot is not overwritten while prior playback may still depend on it;
- before every direct overwrite, the service rechecks the exact physical slot against persisted ownership evidence;
- v2.1.6 can tolerate a stale Protect fingerprint only when the exact proven physical slot and owned filename still match after a bounded synchronization wait;
- filename/slot drift, ambiguity, or missing ownership evidence continues to fail closed;
- destructive direct chime endpoints are blocked before network I/O.

See [Track registry](docs/TRACKS.md), [Playback policy](docs/POLICY.md), and [Architecture](docs/ARCHITECTURE.md).

## Validation boundary

The stable v2.1 architecture has been physically exercised on one Smart Chime for alternating fixed TTS slots, preset/default/buzzer playback, restart persistence, and service status. A 100-unique-message **automated** regression keeps dynamic identities fixed at two. Automated coverage also includes concurrency, dedupe, stale-inventory handling, HA result-state behavior, and multi-target fixtures.

Multi-chime/group playback has **not** been physically validated with multiple Smart Chimes. No synchronized microphone benchmark was available, so the project does not claim measured acoustic latency.

Public CI uses sanitized fixtures and does not contact live UniFi equipment or play audio. It runs the core suite, Home Assistant tests, Ruff, compile checks, metadata/Compose validation, Docker build, HACS validation, and Hassfest.

See the exact pre-release evidence requirements in [Release checklist](docs/RELEASE_CHECKLIST.md).

## Documentation

- [Home Assistant](docs/HOME_ASSISTANT.md)
- [MCP](docs/MCP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Compatibility](docs/COMPATIBILITY.md)
- [Direct-device safety boundary](docs/DIRECT_DEVICE_API.md)
- [Latency and metrics](docs/LATENCY.md)
- [MQTT](docs/MQTT.md)
- [Playback policy](docs/POLICY.md)
- [Protect API matrix](docs/PROTECT_API_MATRIX.md)
- [Rules](docs/RULES.md)
- [Track registry](docs/TRACKS.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [v2.1.6 release notes](docs/RELEASE_NOTES_v2.1.6.md)

## Support and security

Use [GitHub Issues](https://github.com/bdini13/unifi-announcer/issues) for reproducible bugs and focused feature requests. Include the Announcer version, Protect version, Smart Chime model/firmware, reproduction steps, and whether evidence came from automated fixtures or physical devices.

**Never post credentials, private IPs/hostnames, device IDs, certificate material, raw authentication data, private audio, or unredacted support logs.** For vulnerabilities, follow [SECURITY.md](SECURITY.md) rather than opening a public issue.

Keep UniFi Announcer and MCP on a trusted LAN/VPN or deliberately configured authenticated reverse proxy. Do not expose either endpoint directly to the public internet.

Contributions are covered by [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Support is best-effort.

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

Home Assistant validation:

```bash
python3.14 -m venv .venv-ha
.venv-ha/bin/pip install -r requirements-ha-test.txt
.venv-ha/bin/python -m pytest -q tests_ha
```

CI additionally builds the Docker image with a revision SHA and runs HACS validation and Hassfest.

## AI-assisted development

This project was developed with assistance from AI coding and research tools for implementation, debugging, review, tests, documentation, and research. Architecture choices, safety boundaries, release decisions, and physical-device validation remain human-directed.

## Release status

- **Stable:** `v2.1.6` — HA playback reliability, immediate playback-result reporting, and build provenance
- **Planned:** `v2.2.0` — native Home Assistant `tts.speak`, binary media ingestion, and optional SSE integration

See [ROADMAP.md](ROADMAP.md) and the [Releases page](https://github.com/bdini13/unifi-announcer/releases).

## License

MIT. Unofficial community project; not affiliated with or endorsed by Ubiquiti.
