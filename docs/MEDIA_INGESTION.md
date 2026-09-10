# Native Home Assistant media ingestion

UniFi Announcer `v2.2.0-beta.4` candidate adds bounded binary-audio ingestion for Home Assistant media sources, including the media-source handoff used by native `tts.speak`.

> [!WARNING]
> This document describes an unreleased beta.4 candidate until the release checklist and physical playback gate are complete. Stable `v2.1.8` remains the recommended public release.

## What changes

The Home Assistant integration can now accept a `media-source://` ID on a UniFi Announcer `media_player`. Home Assistant resolves that ID locally, reads or downloads the resolved audio under a strict byte limit, and uploads only the bounded audio bytes to the Announcer backend.

The backend then validates and normalizes the payload before handing it to the same `AnnouncementDispatcher` used by ordinary text announcements. There is no separate media playback engine.

The resulting path is:

```text
Home Assistant TTS/media source
        |
        v
HA media-source resolver
        |
        | bounded audio bytes
        v
POST /media/announce
        |
        v
MIME / size / decode / duration validation
        |
        v
mono 22.05 kHz 64 kbps MP3 normalization
        |
        v
AnnouncementDispatcher
        |
        +--> Smart Chime fixed TTS slots
        |
        +--> validated/opted-in camera talkback
```

Queueing, quiet hours, target resolution, priority, dedupe, fixed-slot ownership, camera compatibility gating, and mixed-group behavior therefore remain centralized in the existing dispatcher.

## Native `tts.speak`

Use Home Assistant's normal `tts.speak` action and select a UniFi Announcer media-player entity as `media_player_entity_id`:

```yaml
action: tts.speak
target:
  entity_id: tts.<your_tts_provider>
data:
  media_player_entity_id: media_player.<unifi_announcer_target>
  message: "Dinner is ready"
```

Home Assistant synthesizes the message through the selected TTS provider and passes a media-source ID to the target media player. The UniFi Announcer integration resolves that source and sends the resulting bounded audio to the backend.

This differs from `unifi_announcer.announce`: that action sends text to the Announcer backend, which uses the backend's configured `TTS_ENGINE`.

Consequently, `TTS_ENGINE=none` does **not** prevent beta.4 media-source playback when Home Assistant has already generated the audio. It still prevents backend text synthesis for ordinary Announcer text announcements.

## Accepted media

The backend accepts only these declared audio MIME types:

- `audio/aac`
- `audio/flac`
- `audio/mpeg` / `audio/mp3`
- `audio/mp4` / `audio/x-m4a`
- `audio/ogg`
- `audio/wav` / `audio/x-wav`
- `audio/webm`

A matching MIME declaration is not enough. `ffprobe` must find a decodable audio stream with a finite duration, and `ffmpeg` must successfully normalize it.

The normalized playback contract is:

```text
format: MP3
sample rate: 22050 Hz
channels: 1
bitrate: 64 kbps
```

The camera backend may perform its existing validated AAC/ADTS conversion after this point. The Smart Chime path continues to use the existing fixed MP3 slots.

## Bounds

Default backend limits are deliberately conservative:

| Limit | Default | Environment variable |
|---|---:|---|
| Input body | 4 MiB | `MEDIA_MAX_INPUT_BYTES` |
| Duration | 30 s | `MEDIA_MAX_DURATION_SECONDS` |
| Normalize/probe operation | 15 s | `MEDIA_NORMALIZE_TIMEOUT_SECONDS` |
| Normalized MP3 | 1 MiB | existing `MAX_MP3_BYTES` |

The Home Assistant client independently applies the same 4 MiB input ceiling while reading a resolved local file or streaming a resolved media URL. It does not buffer an unbounded response first.

Compressed HTTP request bodies are rejected. Media decoding is performed only from a local temporary file, and the backend does not fetch caller-supplied URLs.

## URL boundary

The Home Assistant media player accepts Home Assistant `media-source://` IDs; it does **not** turn arbitrary `http://` or `https://` values into a generic server-side fetch primitive.

If a media source resolves to a URL, Home Assistant itself processes and fetches that URL using its own media-source resolution path. Only the resulting bounded audio bytes are uploaded to UniFi Announcer.

## Direct backend API

The beta.4 candidate exposes authenticated binary ingestion at:

```text
POST /media/announce
X-API-Key: <APP_API_KEY>
Content-Type: <supported audio MIME type>
<body: raw audio bytes>
```

Optional query parameters mirror announcement policy where applicable:

- `target`
- `volume`
- `repeat_times`
- `profile`
- `priority`
- `dedupe_key`

Existing capability rules still apply. In particular, camera targets reject explicit `volume` and `profile` overrides and use device-managed volume.

Example with a local WAV file:

```bash
curl -fsS -X POST \
  -H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}" \
  -H 'Content-Type: audio/wav' \
  --data-binary @announcement.wav \
  'http://<announcer-host>:8095/media/announce?target=kitchen'
```

A successful HTTP/dispatcher result indicates that the normal playback path accepted the request. It is not acoustic proof that sound was heard; audible validation remains part of the prerelease physical gate.

## Failure behavior

The endpoint fails before Protect playback when input is outside the contract:

| Status | Meaning |
|---:|---|
| `400` | invalid query values, undecodable media, missing/unknown duration, or duration over the configured limit |
| `403` | missing or incorrect application API key |
| `413` | input or normalized output exceeds the configured byte limit |
| `415` | unsupported/missing content type or compressed request body |
| `502` | canonical dispatcher/playback failure |

Canonical non-error queue dispositions remain unchanged, including `suppressed`, `deduped`, `dropped`, and `partial` where applicable.

## Concurrency and isolation

Binary media is injected into the existing announce operation with a task-local context value. It is visible only to the one dispatcher task associated with that upload. Concurrent normal text announcements continue to call the configured TTS synthesizer, and concurrent media requests receive independent payloads.

The task-local value is cleared in a `finally` block even if dispatch fails or is cancelled.

## Candidate physical validation

Before beta.4 is tagged or published, test the exact frozen candidate with matching backend and Home Assistant integration:

1. Native `tts.speak` to one Smart Chime; confirm the expected phrase is heard once.
2. Repeat `tts.speak`; confirm correct repeated content and normal fixed-slot behavior.
3. A Home Assistant media-source audio clip in a non-MP3 accepted format; confirm normalization and correct Chime playback.
4. Native `tts.speak` to the physically validated G3 Instant; confirm correct audible camera playback.
5. One mixed Chime + validated camera target; confirm both receive the same intended content without bypassing capability rules.
6. An oversized, over-duration, unsupported-type, and invalid-audio request; confirm each fails before any physical playback.
7. An arbitrary direct URL submitted to the HA media player; confirm it is rejected rather than fetched.
8. A normal `unifi_announcer.announce` text request after media testing; confirm regular backend TTS remains isolated and functional.
9. Record exact source SHA, Docker image revision/digest, HA version, and sanitized outcomes in the beta.4 validation report.

Do not publish `v2.2.0-beta.4` until those release-specific physical gates are complete or explicitly documented as not required for a particular unchanged hardware path.