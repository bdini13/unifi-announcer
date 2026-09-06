# Latency and benchmarking

UniFi Announcer separates request-path timing from acoustic latency. The service can measure its own pipeline and HTTP request timing precisely, but it cannot claim speaker-onset latency without a synchronized external microphone/trigger capture.

## Runtime timing model

`AnnouncementTiming` uses `perf_counter_ns()` and records:

- `announce_total_ms`
- `tts_ms` for TTS inference
- `pcm_process_ms` for optional trim/WAV packaging
- `encode_ms` for ffmpeg
- `upload_ms` for dynamic-slot preparation as seen by the dispatcher
- `play_request_ms`
- `queue_wait_ms`

v2.1.8 additionally records detailed dynamic-slot histograms:

- `slot_acquire_ms`
- `slot_preflight_ms`
- `slot_direct_upload_ms`
- `slot_sync_ms`
- `slot_settle_ms`
- `slot_prepare_ms`

Stages are independent rather than intentionally double-counted. Queue wait is the maximum member wait for group fanout, while play-request time covers concurrent fanout. Detailed per-command timing is returned only with `DEBUG_TIMINGS=true`; aggregate counters/histograms are available at authenticated `GET /metrics/json`.

Relevant v2.1.8 counters include:

- `tts_host_cache_hits` / `tts_host_cache_misses`
- `tts_slot_content_hits` / `tts_slot_content_misses`
- `tts_slot_content_partial_hits`
- `tts_slot_overwrite_skips` / `tts_slot_overwrites`
- `tts_slot_sync_successes`
- `tts_slot_sync_stale_inventory_accepts`
- `tts_slot_sync_timeouts`
- `tts_slot_sync_ownership_drift`
- `tts_slot_content_restart_validations`
- `tts_slot_content_restart_invalidations`
- `tts_slot_content_lifecycle_invalidations`
- `tts_slot_content_state_resets`

`GET /tts/slots/status` also exposes a sanitized `content_reuse` section with trusted assignment state and the most recent slot-preparation breakdown.

## Host TTS cache

Piper uses one lifecycle-owned native-async Wyoming connection. Synthesis is serialized by an async lock until Wyoming server concurrency is proven. A stale connection is closed and reconnected once.

The disk cache key includes normalized text, engine, voice/model, rate, sample rate, and encoder profile. Changing any audio dimension cannot reuse a stale MP3. `TTS_TRIM_LEADING_SILENCE=false` is the default. When explicitly enabled, only 16-bit leading quiet PCM is trimmed, 15ms pre-roll is retained (clamped to 10–20ms), and all-silent or unsupported input remains unchanged.

A host MP3 cache hit avoids Piper/Edge synthesis and ffmpeg work. Starting with v2.1.8, a **device-slot content hit** can additionally avoid the Smart Chime physical write, Protect synchronization polling, and settle delay.

## v2.1.8 live request-path results

The v2.1.8 release gate used one physical Smart Chime with Protect `7.2.105` and Smart Chime firmware `1.7.20`. Home Assistant invoked the normal UniFi Announcer action path. Audible correctness was confirmed, but timestamps were not synchronized to a microphone capture, so these are request-path measurements rather than acoustic onset measurements.

### Resident repeated content

Ten same-boot resident requests all reported:

```text
content_hit = true
overwrites = 0
slot_direct_upload_ms = 0
slot_sync_ms = 0
slot_settle_ms = 0
```

Home Assistant request round-trip summary:

```text
min:     540.195 ms
average: 591.340 ms
p50:     585.769 ms
p95:     662.733 ms
max:     662.733 ms
```

The slot-preparation portion was generally only tens of milliseconds because it consisted of boot/ownership validation and content-aware selection rather than a flash write.

### New content

Three new-content request-path samples measured:

```text
4.617 s
4.789 s
6.360 s
```

Average stage timing across those samples:

```text
slot prepare:       4108 ms
preflight:            25 ms
direct slot upload: 3312 ms
sync:                 570 ms
settle:               201 ms
```

The physical direct upload remained the dominant cost. v2.1.8's main latency win is therefore avoiding that upload for safe resident hits rather than trying to make flash writes artificially aggressive.

### Reboot lifecycle result

The first v2.1.8 candidate incorrectly trusted resident content across a physical Smart Chime reboot and played wrong audio. That candidate was not released. The remediation tied resident proof to an uptime-derived boot epoch and added lifecycle/reconnect invalidation.

On the corrected candidate:

- physical reboot invalidated both resident proofs;
- first post-reboot playback performed exactly one safe rewrite and played the requested phrase;
- second same-boot playback performed zero writes and played the requested phrase;
- Announcer-process restart during the same Chime boot preserved safe resident reuse.

The complete history is retained in [`validation/v2.1.8-live-latency-validation.md`](validation/v2.1.8-live-latency-validation.md).

## Acoustic capture analysis

`scripts/acoustic_latency.py` is an offline analyzer for a synchronized PCM WAV recording. It does not contact the service and cannot produce sound. Supply a manifest whose timestamps use the same clock as the trigger recorder:

```json
{
  "recording_started_at_ms": 1724457600000,
  "triggers": [
    {"timestamp_ms": 1724457601000},
    {"timestamp_ms": 1724457603000}
  ]
}
```

```bash
python scripts/acoustic_latency.py \
  --wav capture.wav --manifest capture.json \
  --threshold 0.1 --hold-ms 10 --max-latency-ms 5000
```

For every trigger, the analyzer finds the first sustained normalized PCM onset, reports trigger/onset/latency timestamps, and calculates nearest-rank p50, p90, p95, and p99. Tune the threshold against room noise before relying on results. Retain the manifest, WAV, microphone placement, gain, and detector settings with any published acoustic benchmark. Synthetic WAV tests cover onset detection and percentiles without using a speaker or microphone.

## Live request benchmark

A sound-producing benchmark requires warning occupants and explicit approval immediately before playback:

```bash
python scripts/benchmark.py --url http://127.0.0.1:8095 \
  --preset package-delivered --count 20 --confirm-sound
```

The request benchmark refuses to run without `--confirm-sound`; it measures HTTP round-trip latency rather than acoustic onset. Add `--api-key` when the security gate is enabled, and avoid placing keys in shell history. Pair trigger timestamps with the WAV analyzer above for a defensible end-to-end acoustic benchmark.
