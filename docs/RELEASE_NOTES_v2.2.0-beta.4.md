# v2.2.0-beta.4 — Native Home Assistant media-ingestion candidate

## Status

`v2.2.0-beta.4` is currently a **candidate**, not a published prerelease. Stable `v2.1.8` remains the recommended public release, and published camera prerelease `v2.2.0-beta.3` remains the latest immutable v2.2 prerelease until the beta.4 physical gate is complete.

Do not tag or publish beta.4 from an implementation-only SHA. Freeze one exact candidate, run the documented physical checks, then publish only that validated source revision.

## Purpose

Beta.4 adds native Home Assistant media-source ingestion, including the media-source handoff used by `tts.speak`, without creating a second playback path.

Home Assistant resolves `media-source://` locally and uploads bounded audio bytes to authenticated `POST /media/announce`. The backend validates and normalizes that audio to the existing MP3 contract, then dispatches it through the same `AnnouncementDispatcher` used by ordinary text announcements.

See [Native Home Assistant media ingestion](MEDIA_INGESTION.md) for the operator and architecture details.

## Home Assistant behavior

A UniFi Announcer `media_player` now accepts:

- existing `media_content_type: text` playback;
- existing `unifi-announcer/preset` playback where the target supports presets;
- Home Assistant `media-source://` IDs, including IDs produced by native `tts.speak`.

Arbitrary direct `http://` and `https://` values are not accepted as a generic fetch path. When a Home Assistant media source resolves to a URL, Home Assistant performs that resolved fetch under its own media-source flow and uploads only bounded audio bytes to Announcer.

Home Assistant applies a 4 MiB input ceiling while reading both local resolved media and HTTP-resolved media.

## Backend ingestion contract

New authenticated endpoint:

```text
POST /media/announce
```

The endpoint accepts raw audio bytes with one supported audio MIME type and optional announcement query controls. Before any Protect playback it enforces:

- configured API-key authentication;
- no compressed request body;
- supported audio MIME type;
- bounded streamed input size;
- decodable audio stream;
- finite known duration;
- default 30-second duration ceiling;
- successful normalization to mono 22.05 kHz / 64 kbps MP3;
- bounded normalized output size.

The default accepted MIME set covers AAC, FLAC, MP3, M4A/MP4 audio, Ogg audio, WAV, and WebM audio.

## Dispatcher and device safety

Normalized media is delivered through the existing canonical dispatcher. This preserves:

- target/group resolution;
- per-target queueing;
- priority and dedupe policy;
- quiet-hours suppression;
- fixed two-slot Smart Chime ownership and lifecycle safety;
- camera compatibility/availability hardening;
- one prepared talkback session per physical camera;
- mixed Chime/camera semantics;
- device-managed camera volume and the existing camera rejection of explicit volume/profile overrides;
- no automatic replay after uncertain camera delivery.

A task-local media payload is substituted only for the matching media dispatch. Concurrent ordinary text announcements continue through the configured TTS engine.

## TTS-engine distinction

Native Home Assistant `tts.speak` synthesizes through the selected Home Assistant TTS provider before UniFi Announcer receives audio. Therefore the binary media path can operate with Announcer `TTS_ENGINE=none`.

Ordinary `unifi_announcer.announce`, notify, and `media_content_type: text` requests still require a working Announcer-side TTS engine when dynamic speech is requested.

## Automated coverage

The candidate adds regression coverage for:

- unsupported MIME rejection before decode;
- oversized input rejection before decode/dispatch;
- duration-limit enforcement;
- deterministic normalization contract;
- authenticated media-route dispatch into the existing announcement command;
- task-local audio substitution rather than TTS invocation;
- Home Assistant media-source forwarding to the media API;
- arbitrary direct-URL rejection;
- raw-audio client transport parameters and extended media request timeout;
- all existing backend, camera, fixed-slot, Home Assistant, lint, compile, metadata, Compose, and Docker tests.

## Publication gate

Before beta.4 can be published, the exact frozen candidate must still complete the physical validation documented in `docs/validation/v2.2.0-beta.4-media-ingestion-validation.md`. At minimum, that gate must prove audible native `tts.speak` on a Smart Chime and validated camera, non-MP3 media normalization, mixed-target behavior, fail-before-playback rejection cases, and normal text-TTS isolation after media playback.

Until then, any successful CI result is automated candidate evidence only and is not an acoustic or device-level compatibility claim.