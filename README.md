# UniFi Announcer

[![CI](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bdini13/unifi-announcer/actions/workflows/test.yml)
[![Latest release](https://img.shields.io/github/v/release/bdini13/unifi-announcer?display_name=tag&sort=semver)](https://github.com/bdini13/unifi-announcer/releases/latest)

Self-hosted text-to-speech announcements, preset tones, and event-driven playback for UniFi Protect Smart Chimes.

UniFi Announcer runs on your LAN. It uses a local UniFi OS account to create and manage Protect ringtone objects, then asks Protect to play them on one or more Smart Chimes. Piper is the recommended TTS engine; Edge TTS is also supported.

> [!IMPORTANT]
> UniFi Protect's local API is undocumented and may change. This project has been tested with Protect 7.2.105 and Smart Chime firmware 1.7.20. See [Compatibility](docs/COMPATIBILITY.md) before upgrading firmware.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Basic usage](#basic-usage)
- [Home Assistant](#home-assistant)
- [Local Protect rules](#local-protect-rules)
- [Multiple chimes and groups](#multiple-chimes-and-groups)
- [Configuration reference](#configuration-reference)
- [API summary](#api-summary)
- [Release notes](#release-notes)
- [Documentation](#documentation)
- [Development](#development)

## Features

- Ad-hoc TTS through local Piper or cloud-based Edge TTS
- Reusable preset tones
- Chime buzzer and assigned-default playback
- Protect doorbell events over its realtime WebSocket
- Local rules that do not depend on Home Assistant
- Home Assistant REST commands and optional MQTT discovery
- Multiple chimes and named groups
- Quiet hours, volume profiles, priorities, deduplication, and bounded queues
- Disk and NVR caching for repeated announcements
- Bounded cleanup of service-owned dynamic ringtones
- Automatic recovery from temporary Piper failures and stale ringtone IDs
- Health, cache, event, queue, and latency diagnostics

## How it works

```text
text
  -> Piper or Edge TTS
  -> MP3 cache
  -> Protect ringtone object
  -> Protect play-speaker command
  -> Smart Chime
```

Protect playback always goes through the NVR/controller. Direct chime HTTPS is used only for supported device information, redacted logs, and guarded research paths. Stock Smart Chime firmware 1.7.20 does not expose a usable inbound HTTP playback endpoint.

## Requirements

- A UniFi console running Protect, such as a UDM Pro, UDM Pro SE, CloudKey+, or UNVR
- At least one adopted UniFi Protect Smart Chime
- A local UniFi OS account with access to Protect (SSO-only accounts will not work)
- Docker Engine with Docker Compose
- A TTS service:
  - [Wyoming Piper](https://github.com/rhasspy/wyoming-piper) on any reachable host, recommended
  - Edge TTS with internet access

Your Docker host, UniFi console, Piper server, Home Assistant server, and chime may use any reachable addresses. They do not need to share a particular subnet.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/bdini13/unifi-announcer.git
cd unifi-announcer
cp .env.example .env
```

### 2. Create a local UniFi account

In the UniFi console:

1. Open **Admins & Users**.
2. Create a local admin account rather than an SSO-only account.
3. Grant it the Protect permissions needed to view chimes and manage ringtones.
4. Put that username and password in `.env`.

### 3. Find the chime ID

Set your own console address and credentials. The example does not assume a specific LAN range.

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

Copy the `id` or `_id` for the chime you want to use as the default.

### 4. Configure `.env`

At minimum, set:

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

Generate an API key if other systems will call the write endpoints:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then add it to `.env`:

```env
APP_API_KEY=<generated-key>
```

Leaving `APP_API_KEY` empty keeps write endpoints open to the trusted LAN.

### 5. Start the service

```bash
docker compose up -d --build
docker compose logs -f unifi-announcer
```

Persistent files are stored in `./data` beside `docker-compose.yml`; that
directory is ignored by Git. To use a NAS or another bind-mount location, set an
absolute host path in `.env`, for example `DATA_PATH=/srv/unifi-announcer/data`,
before starting the service.

Set the URL to the address of the machine running this container:

```bash
export ANNOUNCER_URL="http://<docker-host-or-ip>:8095"
curl -fsS "$ANNOUNCER_URL/health"
```

A healthy response has `"status":"ok"`. Piper can be offline during startup; non-TTS functions remain available, and later announcements retry Piper automatically.

## Basic usage

The examples below work with or without an API key:

```bash
export ANNOUNCER_URL="http://<docker-host-or-ip>:8095"

# No APP_API_KEY configured:
AUTH=()

# If APP_API_KEY is configured, use this instead:
# export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
# AUTH=(-H "X-API-Key: $UNIFI_ANNOUNCER_API_KEY")
```

### Announce text

```bash
curl -fsS -X POST "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Dinner is ready","volume":45}' \
  "$ANNOUNCER_URL/announce"
```

### Use the buzzer

```bash
curl -fsS -X POST "${AUTH[@]}" \
  "$ANNOUNCER_URL/buzzer"
```

### Play the chime's assigned default

```bash
curl -fsS -X POST "${AUTH[@]}" \
  "$ANNOUNCER_URL/play-default"
```

Without query parameters, this sends no volume or repeat override, so the chime uses its stored settings.

### Create and play a preset

```bash
curl -fsS -X PUT "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"name":"package-delivered","text":"Package delivered"}' \
  "$ANNOUNCER_URL/presets/package-delivered"

curl -fsS -X POST "${AUTH[@]}" \
  "$ANNOUNCER_URL/presets/package-delivered/play?volume=50&repeat_times=1"
```

### Read diagnostics

These endpoints do not play audio:

```bash
curl -fsS "$ANNOUNCER_URL/health"
curl -fsS "$ANNOUNCER_URL/version"
curl -fsS "$ANNOUNCER_URL/chime"
curl -fsS "$ANNOUNCER_URL/chimes"
curl -fsS "$ANNOUNCER_URL/presets"
curl -fsS "$ANNOUNCER_URL/events/recent?limit=10"
curl -fsS "$ANNOUNCER_URL/cache/ringtones/status"
curl -fsS "$ANNOUNCER_URL/metrics/json"
```

## Home Assistant

### REST commands

If `APP_API_KEY` is enabled, add the same key to `/config/secrets.yaml`:

```yaml
unifi_announcer_api_key: "<same-key-used-in-announcer-env>"
```

Add the following to `/config/configuration.yaml`. Replace `<announcer-host-or-ip>` with the address of the Docker host.

```yaml
rest_command:
  unifi_announcer_say:
    url: "http://<announcer-host-or-ip>:8095/announce"
    method: POST
    headers:
      X-API-Key: !secret unifi_announcer_api_key
    content_type: "application/json; charset=utf-8"
    payload: >-
      {"text": {{ text | tojson }}, "volume": {{ volume | default(50) }},
       "repeat_times": {{ repeat_times | default(1) }}}

  unifi_announcer_buzzer:
    url: "http://<announcer-host-or-ip>:8095/buzzer"
    method: POST
    headers:
      X-API-Key: !secret unifi_announcer_api_key

  unifi_announcer_default:
    url: "http://<announcer-host-or-ip>:8095/play-default"
    method: POST
    headers:
      X-API-Key: !secret unifi_announcer_api_key

  unifi_announcer_preset:
    url: "http://<announcer-host-or-ip>:8095/presets/{{ preset }}/play"
    method: POST
    headers:
      X-API-Key: !secret unifi_announcer_api_key
```

Remove the `headers` blocks if `APP_API_KEY` is intentionally empty. Check the Home Assistant configuration before restarting.

Test the TTS action from **Developer Tools → Actions**:

```yaml
action: rest_command.unifi_announcer_say
data:
  text: "Home Assistant test"
  volume: 35
```

Example automation:

```yaml
automation:
  - alias: "Announce front door opened"
    triggers:
      - trigger: state
        entity_id: binary_sensor.front_door
        to: "on"
    actions:
      - action: rest_command.unifi_announcer_say
        data:
          text: "Front door opened"
          volume: 40
```

### MQTT discovery

Set the broker address in `.env`:

```env
MQTT_URL=mqtt://<mqtt-broker-host-or-ip>:1883
MQTT_USERNAME=<mqtt-username>
MQTT_PASSWORD=<mqtt-password>
```

Recreate the container:

```bash
docker compose up -d
```

Home Assistant MQTT discovery creates per-chime buzzer/default buttons and status sensors. REST, events, and local rules continue working if MQTT is disabled or unavailable.

See [MQTT documentation](docs/MQTT.md) for topics and payloads.

## Local Protect rules

Local rules react to Protect events inside the announcer process, avoiding a Home Assistant round trip. Rules are stored in `${DATA_DIR}/rules.json`.

```json
[
  {
    "name": "front-door-ring",
    "when": {"event": "doorbell_ring", "model": "camera"},
    "then": {"preset": "front-door", "volume": 70},
    "cooldown_ms": 250
  }
]
```

Rules can only play existing presets. Playback runs independently from the Protect WebSocket receiver, and the rule cooldown is also used by the playback queue's dedupe window.

See [Rules documentation](docs/RULES.md).

## Multiple chimes and groups

A single `CHIME_ID` is enough for one chime. For multiple chimes, use JSON configuration:

```env
CHIMES_CONFIG='[
  {"name":"kitchen","id":"<kitchen-chime-id>","direct_ip":"<optional-chime-ip>"},
  {"name":"upstairs","id":"<upstairs-chime-id>"}
]'
GROUPS_CONFIG='{"downstairs":["kitchen"],"whole_house":["kitchen","upstairs"]}'
```

Target one chime or a group:

```bash
curl -fsS -X POST "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Dinner is ready","target":"whole_house"}' \
  "$ANNOUNCER_URL/announce"
```

The service gives each chime its own bounded queue. Group members execute concurrently, and a failed member does not prevent healthy members from playing.

## Configuration reference

See [`.env.example`](.env.example) for every option.

| Variable | Default | Purpose |
|---|---:|---|
| `UNIFI_HOST` | none | UniFi console URL, including `http://` or `https://` |
| `UNIFI_USERNAME` | none | Local UniFi OS username |
| `UNIFI_PASSWORD` | none | Local UniFi OS password |
| `UNIFI_VERIFY_SSL` | `false` | Verify the console TLS certificate |
| `CHIME_ID` | none | Default Protect chime ID |
| `TTS_ENGINE` | `piper` | `piper` or `edge` |
| `PIPER_URL` | none | Wyoming Piper endpoint |
| `PIPER_SYNTH_TIMEOUT` | `15` | Timeout in seconds for each Piper attempt |
| `APP_API_KEY` | empty | Protect write routes with `X-API-Key` |
| `HOST_PORT` | `8095` | Port exposed on the Docker host |
| `DATA_PATH` | `./data` | Host path mounted at `/data`; may be an absolute NAS/server path |
| `VOLUME_DEFAULT` | `50` | Default volume when the request does not specify one |
| `REPEAT_DEFAULT` | `1` | Default repeat count |
| `QUIET_HOURS` | empty | Suppression window such as `22:00-06:30` |
| `VOLUME_PROFILES` | `{}` | Named volume/repeat profiles as JSON |
| `MAX_DYNAMIC_TRACKS` | `32` | Maximum service-owned dynamic TTS records |
| `PLAY_QUEUE_MAX_DEPTH` | `16` | Per-chime playback queue limit |
| `EVENTS_ENABLED` | `true` | Enable the Protect WebSocket listener |
| `EVENTS_BUFFER_MAX` | `100` | Number of recent events kept in memory |
| `MQTT_URL` | empty | Optional MQTT broker URL |
| `CHIMES_CONFIG` | empty | Multi-chime definitions as JSON |
| `GROUPS_CONFIG` | empty | Named chime groups as JSON |

## API summary

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Cached component health |
| `GET` | `/version` | Service and compatibility details |
| `POST` | `/announce` | Synthesize/cache text and play it |
| `POST` | `/buzzer` | Play the hardware buzzer |
| `POST` | `/play-default` | Play the assigned default ringtone |
| `GET` | `/presets` | List Protect ringtones |
| `PUT` | `/presets/{name}` | Create or replace a preset |
| `POST` | `/presets/{name}/play` | Play a preset |
| `GET` | `/chime` | Default chime diagnostics |
| `GET` | `/chimes` | Configured chimes, groups, and queue depths |
| `GET` | `/events/recent` | Recent normalized Protect events |
| `GET` | `/events/stream` | Server-Sent Events stream |
| `GET` | `/rules/status` | Local rule status and counters |
| `POST` | `/rules/reload` | Reload rules; API key required |
| `GET` | `/cache/ringtones/status` | In-memory ringtone index status |
| `POST` | `/cache/ringtones/refresh` | Refresh the index; API key required |
| `GET` | `/metrics/json` | Timing histograms and counters |

FastAPI's interactive schema is available at `http://<announcer-host-or-ip>:8095/docs`.

## Advanced topics

### Direct chime diagnostics

Direct chime access is optional. The service works through Protect without `CHIME_DIRECT_PASSWORD`.

If you enable direct diagnostics, the adopted chime password is stored in Protect's PostgreSQL database. Database paths and PostgreSQL versions vary by console and Protect release, so consult [Compatibility](docs/COMPATIBILITY.md) rather than copying a hard-coded host or path. Set:

```env
CHIME_DIRECT_IP=<chime-host-or-ip>
CHIME_DIRECT_USER=ubnt
CHIME_DIRECT_PASSWORD=<current-adoption-password>
```

UniFi may rotate this password. A file-based provider avoids container restarts:

```env
CHIME_CREDENTIAL_FILE=/run/secrets/unifi_chime_password
```

When direct access fails, supported operations fall back to Protect. Destructive direct endpoints are blocked before network I/O.

### Caching and cleanup

- Repeated text uses a disk MP3 cache.
- Ringtone IDs live in one in-memory `RingtoneIndex`.
- Simultaneous first requests for the same phrase share ringtone creation.
- Dynamic TTS records are bounded by `MAX_DYNAMIC_TRACKS` and evicted by recent use.
- Cleanup only targets unpinned records owned by `unifi_announcer`.
- Presets, built-ins, and user-created tones are not dynamic cleanup candidates.
- Device flash is not deleted because its deletion semantics have not been proven safe.

See [Track registry documentation](docs/TRACKS.md).

### Playback responses

Commands return a disposition:

- `played`: all selected chimes played the request
- `suppressed`: quiet-hours policy suppressed it (`HTTP 202`)
- `deduped`: the queue rejected a duplicate in the configured window
- `dropped`: queue policy dropped the request
- `partial`: mixed results across targets (`HTTP 207`)
- `failed`: playback failed (`HTTP 502`)

### Firmware upgrades

Run the offline signature tool before and after an authorized Smart Chime firmware upgrade:

```bash
python3 scripts/fw_signature.py <firmware.bin>
```

If known signatures change, direct features fail closed. Protect/NVR playback remains the production path. See [Compatibility](docs/COMPATIBILITY.md).

## Release notes

### v2.0.0 - local MVP reliability release

The current release turns the earlier prototype into a continuously usable LAN service.

- Playback failures now return failure responses instead of false HTTP 200 results.
- Piper outages no longer prevent application startup.
- Piper connection and synthesis attempts have bounded timeouts and one reconnect attempt.
- Startup warmup performs actual Piper inference.
- Ad-hoc TTS creates tracked Protect ringtone identities and enforces `MAX_DYNAMIC_TRACKS`.
- `RingtoneIndex` is the only in-memory ringtone ID source.
- Cleanup refreshes the index after deletion and avoids stale IDs.
- Stale ringtone IDs refresh and retry once without masking unrelated Protect errors.
- Protect WebSocket event intake no longer waits for rule playback.
- Bare `/play-default` requests preserve the chime's stored volume and repeat settings.
- Simultaneous cold requests for the same phrase create one ringtone.
- Rule cooldown and playback deduplication use the same window.
- Standalone, Home Assistant, and MQTT setup instructions were added.

### Earlier prototypes

Earlier private prototypes established the Protect API client, TTS and preset playback, event parsing, local rules, MQTT, multi-chime queues, direct diagnostics, and compatibility tooling. They were consolidated into the v2.0.0 public release.

The packaged GitHub release is available on the [Releases page](https://github.com/bdini13/unifi-announcer/releases).

## Project status and limits

Stable:

- TTS, presets, buzzer, and default playback through Protect
- Piper reconnect and timeout behavior
- Bounded dynamic ringtone cleanup
- Health and diagnostics endpoints

Experimental:

- Direct chime diagnostics
- Protect event parsing and local rules
- MQTT discovery and multi-chime arbitration

Not implemented:

- Direct stock-firmware HTTP playback
- Production dynamic-slot playback without Protect ringtone identities
- Official Protect API migration

Ringtones must be valid MP3 files under Protect's size limit. The service relies on private Protect endpoints, so firmware or Protect updates can require compatibility work.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Compatibility](docs/COMPATIBILITY.md)
- [Latency and metrics](docs/LATENCY.md)
- [MQTT](docs/MQTT.md)
- [Playback policy](docs/POLICY.md)
- [Rules](docs/RULES.md)
- [Track registry](docs/TRACKS.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)

## Security

Keep UniFi credentials and API keys out of Git. Store them in `.env`, Docker secrets, or another local secret manager. Do not expose UniFi Announcer directly to the internet. Use a VPN or authenticated reverse proxy if remote access is required.

The service refuses known destructive chime endpoints, including adoption and factory-reset paths.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -W error -m pytest -q
.venv/bin/ruff check .
```

Tests use mocks and sanitized fixtures. They do not contact a live console or play audio.

## License

MIT

Unofficial community project; not affiliated with or endorsed by Ubiquiti.
