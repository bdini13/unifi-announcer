# Protect camera-speaker setup

UniFi Announcer `v2.2.0-beta.3` can use explicitly configured UniFi Protect cameras as experimental text-announcement speakers. Stable `v2.1.8` remains the recommended release for Smart Chime-only installations.

> [!WARNING]
> Camera-speaker support is a prerelease feature built on private Protect talkback behavior. Do not infer compatibility from `hasSpeaker=true` or from AAC support alone. Review [Compatibility](COMPATIBILITY.md) before enabling a camera.

## Compatibility boundary

The production model table contains one physically validated camera profile:

```text
model: UVC G3 Instant
codec: AAC-LC
transport: serverudp
sample rate: 22050 Hz
channels: 1
bits per sample: 16
compatibility: physically_validated
```

`v2.2.0-beta.3` also provides the empty-by-default `EXPERIMENTAL_CAMERA_PROFILES` protocol allowlist. One representative UVC G4 Instant with the same five wire dimensions passed the project's complete physical gate, but it remains `experimental_opt_in`; this is not a broad G4 or generic-camera compatibility claim.

The experimental allowlist is **protocol-level, not model-level**. An entry can admit any camera that is explicitly named in `CAMERAS_CONFIG` and reports the exact same five dimensions. Keep `CAMERAS_CONFIG` narrow and add only devices you intend to test.

## Prerequisites

Before configuring a camera, have:

- a local UniFi console account with the Protect access already required by UniFi Announcer;
- a configured `APP_API_KEY`;
- a working text-to-speech engine (`TTS_ENGINE=piper` or `TTS_ENGINE=edge`); `TTS_ENGINE=none` cannot produce a camera text announcement;
- a connected Protect camera with a speaker;
- the backend and, when used, Home Assistant integration on the same prerelease version.

## 1. Use the matching prerelease

Camera support requires the backend and Home Assistant custom integration from the same `v2.2.0-beta.3` release.

For a source-built backend, select the published prerelease before changing configuration:

```bash
git fetch --tags
git checkout v2.2.0-beta.3
```

Do not start the new backend yet; configure and verify the intended camera profile first, then recreate it in Step 5 with exact build provenance.

If Home Assistant is installed, select the same prerelease in HACS and reload/restart the integration as required. Do not mix a stable HA component with a prerelease backend or vice versa.

## 2. Find the Protect camera ID and observed profile

Cameras are never auto-enrolled into UniFi Announcer. Each target needs the camera UUID from Protect bootstrap.

The following read-only shell session uses a temporary cookie jar and keeps the local UniFi password out of shell history. It prints only the fields needed for camera selection and compatibility review.

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

curl -ksS -b "$COOKIE_JAR" "$UNIFI_HOST/proxy/protect/api/bootstrap" | \
python3 -c '
import json, sys
bootstrap = json.load(sys.stdin)
for camera in bootstrap.get("cameras", []):
    flags = camera.get("featureFlags") or {}
    talkback = camera.get("talkbackSettings") or {}
    print(json.dumps({
        "name": camera.get("name"),
        "id": camera.get("id"),
        "model": camera.get("type") or camera.get("modelKey"),
        "state": camera.get("state"),
        "has_speaker": flags.get("hasSpeaker"),
        "codec": talkback.get("typeFmt"),
        "transport": talkback.get("typeIn"),
        "sample_rate": talkback.get("samplingRate"),
        "channels": talkback.get("channels"),
        "bits_per_sample": talkback.get("bitsPerSample"),
    }))
'

rm -f "$COOKIE_JAR"
trap - EXIT
unset UNIFI_USERNAME UNIFI_PASSWORD
```

Do not copy authentication cookies, signed talkback URLs, controller credentials, private addresses, or raw bootstrap data into an issue or validation report.

## 3. Configure the camera target

Add only the intended camera IDs to `.env`. Keep your existing working Piper or Edge TTS configuration enabled; the camera path consumes the same synthesized MP3 input as other text announcements.

### Physically validated G3 Instant profile

For a G3 Instant that reports the exact validated dimensions, no experimental protocol allowlist entry is required:

```env
CAMERAS_CONFIG='[
  {"name":"family_room_camera","id":"<camera-uuid>"}
]'
EXPERIMENTAL_CAMERA_PROFILES=[]
```

### Exact-profile experimental opt-in

For the representative beta.3 G4 Instant profile:

```env
CAMERAS_CONFIG='[
  {"name":"family_room_camera","id":"<camera-uuid>"}
]'
EXPERIMENTAL_CAMERA_PROFILES='[
  {"codec":"aac","transport":"serverudp","sample_rate":22050,"channels":1,"bits_per_sample":16}
]'
```

Every experimental profile object must contain exactly these five keys. The service rejects malformed entries, duplicate profiles, extra keys, non-integer numeric fields, Opus/RTP, non-mono audio, non-16-bit audio, and unsupported AAC/ADTS sample rates at startup.

For another camera, do **not** copy the G4 entry merely because the device has a speaker. Compare the read-only bootstrap output first and opt in only to the exact observed profile you deliberately intend to test.

## 4. Optional groups

A group may mix Smart Chimes and compatible camera targets:

```env
GROUPS_CONFIG='{
  "mixed":["kitchen","family_room_camera"]
}'
```

Group configuration is strict. Unknown members, duplicate members, empty groups, reserved/colliding names, and malformed JSON fail startup.

Cameras never join the implicit `default` target. They must be addressed by their configured name or through an explicit group.

## 5. Recreate and verify without playing audio

Recreate the backend after changing topology or experimental profile configuration, embedding the checked-out source revision in the image:

```bash
export GIT_SHA="$(git rev-parse HEAD)"
docker compose up -d --build
```

Then verify the service and target catalog:

```bash
export ANNOUNCER_URL="http://<announcer-host-or-ip>:8095"
export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")

curl -fsS "$ANNOUNCER_URL/health"
curl -fsS "$ANNOUNCER_URL/version"
curl -fsS "${AUTH[@]}" "$ANNOUNCER_URL/targets"
```

`GET /version` should report semantic version `2.2.0-beta.3`. When built as above, `git_sha` should match `git rev-parse HEAD` for the checked-out tag.

Expected camera states:

- validated G3 Instant exact profile: `status=available`, `compatibility=physically_validated`;
- exact-profile experimental admission: `status=available`, `compatibility=experimental_opt_in`;
- offline, missing-speaker, malformed, unvalidated, or non-matching profile: `status=unavailable`.

Do not treat an unavailable camera as a setup-success state just because it appears in `/targets`. Explicitly configured cameras stay visible while unavailable so Home Assistant can preserve entities across reconnects.

## 6. First camera announcement

For the first audible test, target one camera directly rather than a mixed group. Camera requests support text and repeats. Do not send `volume` or `profile`; camera volume is managed by the device and those overrides are rejected.

```bash
curl -fsS -X POST \
  "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"text":"UniFi Announcer camera test","target":"family_room_camera","repeat_times":1}' \
  "$ANNOUNCER_URL/announce"
```

A successful HTTP/WebSocket result proves only that the software path completed. Confirm the intended camera was actually audible before expanding to groups or automation. The runtime intentionally does not retry after uncertain camera delivery because doing so could duplicate speech.

## Home Assistant behavior

With the matching prerelease installed, an available camera exposes only capability-safe controls:

- `notify` for text announcements;
- text-only `media_player.play_media`;
- queue-depth sensor;
- Last playback result sensor.

Camera targets do not expose buzzer, assigned-default, preset selector, play-preset, or volume controls. A configured camera remains represented while temporarily offline and becomes available again after a later `/targets` refresh; entity recreation is not required.

Changing `CAMERAS_CONFIG`, `CHIMES_CONFIG`, or `GROUPS_CONFIG` changes topology and requires the backend plus Home Assistant integration to be reloaded/restarted as appropriate.

See [Home Assistant integration](HOME_ASSISTANT.md) for entity and action examples.

## Troubleshooting

| Symptom | Check |
|---|---|
| Camera is absent from `/targets` | Verify its UUID and JSON syntax in `CAMERAS_CONFIG`, then recreate the backend. |
| Camera is present but unavailable | Confirm `CONNECTED`, `hasSpeaker=true`, and all five talkback dimensions from the read-only bootstrap inventory. |
| G4/other model remains unavailable | This is expected without an exact `EXPERIMENTAL_CAMERA_PROFILES` match. Do not broaden the entry beyond observed values. |
| Service fails during startup | Validate `CAMERAS_CONFIG`, `GROUPS_CONFIG`, and `EXPERIMENTAL_CAMERA_PROFILES` JSON. Experimental entries require exact keys and types. |
| Text announcement fails before playback | Confirm `TTS_ENGINE` is `piper` or `edge` and that synthesis is healthy. |
| HA camera entity remains unavailable after reconnect | Wait for the next coordinator `/targets` poll or reload the integration. |
| Preset/default/buzzer/volume call fails on a camera | Expected. Camera targets currently support text and repeats only. |
| Announcement request succeeds but sound was not heard | Treat delivery as uncertain; inspect logs/device state and do not assume an automatic retry is safe. |

## Evidence and implementation references

- [Compatibility matrix](COMPATIBILITY.md)
- [Home Assistant integration](HOME_ASSISTANT.md)
- [v2.2.0-beta.3 release notes](RELEASE_NOTES_v2.2.0-beta.3.md)
- [G4 Instant beta.3 physical validation](validation/v2.2.0-beta.3-g4-instant-validation.md)
- [G3 Instant beta.1 physical validation](validation/v2.2.0-beta.1-g3-instant-camera-validation.md)
- [Camera hardening beta.2 validation](validation/v2.2.0-beta.2-camera-hardening-validation.md)
