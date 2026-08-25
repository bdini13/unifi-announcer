import json
import math
import struct
import wave

import pytest

from scripts.acoustic_latency import analyze_recording, load_manifest


def write_synthetic_wav(path, *, sample_rate=1000, duration_ms=2200, onsets_ms=()):
    samples = []
    for frame in range(duration_ms * sample_rate // 1000):
        active = any(onset <= frame < onset + 100 for onset in onsets_ms)
        value = int(0.5 * 32767 * math.sin(2 * math.pi * 100 * frame / sample_rate)) if active else 0
        samples.append(value)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_analyze_synchronized_wav_reports_onset_percentiles(tmp_path):
    wav_path = tmp_path / "capture.wav"
    write_synthetic_wav(wav_path, onsets_ms=(500, 1500))

    result = analyze_recording(
        wav_path,
        recording_started_at_ms=1_000_000,
        trigger_timestamps_ms=[1_000_400, 1_001_300],
        threshold=0.2,
        hold_ms=5,
        max_latency_ms=500,
    )

    assert [sample["latency_ms"] for sample in result["samples"]] == [101.0, 201.0]
    assert result["summary"] == {
        "count": 2,
        "min": 101.0,
        "p50": 101.0,
        "p90": 201.0,
        "p95": 201.0,
        "p99": 201.0,
        "max": 201.0,
    }
    assert result["wav"]["sample_rate"] == 1000


def test_analyze_fails_when_no_onset_is_present(tmp_path):
    wav_path = tmp_path / "silence.wav"
    write_synthetic_wav(wav_path)

    with pytest.raises(ValueError, match="no onset"):
        analyze_recording(
            wav_path,
            recording_started_at_ms=10_000,
            trigger_timestamps_ms=[10_100],
            threshold=0.2,
            max_latency_ms=250,
        )


def test_load_manifest_requires_synchronized_fields(tmp_path):
    manifest_path = tmp_path / "capture.json"
    manifest_path.write_text(json.dumps({"recording_started_at_ms": 1234, "triggers": [{"timestamp_ms": 1500}]}))

    assert load_manifest(manifest_path) == (1234.0, [1500.0])

    manifest_path.write_text("{}")
    with pytest.raises(ValueError, match="recording_started_at_ms"):
        load_manifest(manifest_path)
