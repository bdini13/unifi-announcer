# Latency and benchmarking

`AnnouncementTiming` uses `perf_counter_ns()` and records:

- `announce_total_ms`
- `tts_ms` for Piper inference
- `pcm_process_ms` for optional trim and WAV packaging
- `encode_ms` for ffmpeg
- `upload_ms`
- `play_request_ms`
- `queue_wait_ms`

Stages are independent rather than double-counted. Queue wait is the maximum
member wait for group fanout, while play-request time covers concurrent fanout.
Detailed per-command timing is returned only with `DEBUG_TIMINGS=true`;
aggregates are available at `GET /metrics/json`.

Piper uses one lifecycle-owned native-async Wyoming connection. Synthesis is
serialized by an async lock until Wyoming server concurrency is proven. A stale
connection is closed and reconnected once. The mocked structural benchmark
`PiperTTS.mock_connection_benchmark(10)` reports 10 fresh connections versus one
persistent connection; this is not an acoustic or network latency claim.

The disk cache key includes normalized text, engine, voice/model, rate, sample
rate, and encoder profile. Changing any audio dimension cannot reuse a stale MP3.
`TTS_TRIM_LEADING_SILENCE=false` is the default. When explicitly enabled, only
16-bit leading quiet PCM is trimmed, 15ms pre-roll is retained (clamped to
10-20ms), and all-silent or unsupported input remains unchanged.

Deployment-specific experiment timings are intentionally excluded from the
public repository.

## Acoustic capture analysis

`scripts/acoustic_latency.py` is an offline analyzer for a synchronized PCM WAV
recording. It does not contact the service and cannot produce sound. Supply a
manifest whose timestamps use the same clock as the trigger recorder:

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

For every trigger, the analyzer finds the first sustained normalized PCM onset,
reports trigger/onset/latency timestamps, and calculates nearest-rank p50, p90,
p95, and p99. Tune the threshold against room noise before relying on results.
Retain the manifest, WAV, microphone placement, gain, and detector settings with
any published benchmark. Synthetic WAV tests cover onset detection and
percentiles without using a speaker or microphone.

## Live benchmark

A sound-producing benchmark requires warning occupants and explicit approval
immediately before playback:

```bash
python scripts/benchmark.py --url http://127.0.0.1:8095 \
  --preset package-delivered --count 20 --confirm-sound
```

The request benchmark refuses to run without `--confirm-sound`; it measures HTTP
round-trip latency rather than acoustic onset. Add `--api-key` when the security
gate is enabled, and avoid placing keys in shell history. Pair trigger timestamps
with the WAV analyzer above for end-to-end audible latency.
