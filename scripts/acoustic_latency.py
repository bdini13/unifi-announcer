#!/usr/bin/env python3
"""Analyze audible onset latency from a synchronized PCM WAV capture.

This tool is offline-only: it reads a WAV and timestamp manifest and never calls
UniFi Announcer or produces sound.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import wave


def percentile(values: list[float], pct: int) -> float:
    if not values:
        raise ValueError("no samples")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * pct / 100) - 1)]


def summarize(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "min": min(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
    }


def load_manifest(path: str | Path) -> tuple[float, list[float]]:
    data = json.loads(Path(path).read_text())
    if "recording_started_at_ms" not in data:
        raise ValueError("manifest requires recording_started_at_ms")
    triggers = data.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        raise ValueError("manifest requires a non-empty triggers list")
    try:
        timestamps = [float(item["timestamp_ms"]) for item in triggers]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("each trigger requires numeric timestamp_ms") from exc
    return float(data["recording_started_at_ms"]), timestamps


def _decode_frame_peaks(raw: bytes, *, channels: int, sample_width: int) -> list[float]:
    frame_width = channels * sample_width
    peaks: list[float] = []
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported PCM sample width: {sample_width}")
    maximum = float((1 << (sample_width * 8 - 1)) - 1)
    for offset in range(0, len(raw), frame_width):
        frame = raw[offset : offset + frame_width]
        channel_values = []
        for channel in range(channels):
            start = channel * sample_width
            encoded = frame[start : start + sample_width]
            if sample_width == 1:
                value = encoded[0] - 128
                denominator = 127.0
            else:
                value = int.from_bytes(encoded, "little", signed=True)
                denominator = maximum
            channel_values.append(abs(value) / denominator)
        peaks.append(max(channel_values))
    return peaks


def _find_onset(
    peaks: list[float],
    *,
    start_frame: int,
    end_frame: int,
    threshold: float,
    hold_frames: int,
) -> int | None:
    required = max(1, math.ceil(hold_frames * 0.6))
    last_candidate = max(start_frame, end_frame - hold_frames + 1)
    for frame in range(start_frame, last_candidate):
        if peaks[frame] < threshold:
            continue
        window = peaks[frame : frame + hold_frames]
        if sum(value >= threshold for value in window) >= required:
            return frame
    return None


def analyze_recording(
    wav_path: str | Path,
    *,
    recording_started_at_ms: float,
    trigger_timestamps_ms: list[float],
    threshold: float = 0.1,
    hold_ms: float = 10,
    max_latency_ms: float = 5000,
) -> dict:
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be within (0, 1]")
    if hold_ms <= 0 or max_latency_ms <= 0:
        raise ValueError("hold_ms and max_latency_ms must be positive")

    with wave.open(str(wav_path), "rb") as source:
        if source.getcomptype() != "NONE":
            raise ValueError("only uncompressed PCM WAV is supported")
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        peaks = _decode_frame_peaks(
            source.readframes(frame_count),
            channels=channels,
            sample_width=sample_width,
        )

    hold_frames = max(1, math.ceil(hold_ms * sample_rate / 1000))
    samples = []
    for index, trigger_ms in enumerate(trigger_timestamps_ms):
        relative_ms = trigger_ms - recording_started_at_ms
        start_frame = max(0, math.floor(relative_ms * sample_rate / 1000))
        end_ms = relative_ms + max_latency_ms
        if index + 1 < len(trigger_timestamps_ms):
            next_relative = trigger_timestamps_ms[index + 1] - recording_started_at_ms
            end_ms = min(end_ms, next_relative)
        end_frame = min(frame_count, math.ceil(end_ms * sample_rate / 1000))
        if start_frame >= frame_count or end_frame <= start_frame:
            raise ValueError(f"trigger {index} is outside the WAV search window")
        onset_frame = _find_onset(
            peaks,
            start_frame=start_frame,
            end_frame=end_frame,
            threshold=threshold,
            hold_frames=hold_frames,
        )
        if onset_frame is None:
            raise ValueError(f"no onset found for trigger {index}")
        onset_ms = onset_frame * 1000 / sample_rate
        samples.append(
            {
                "trigger_timestamp_ms": float(trigger_ms),
                "onset_timestamp_ms": recording_started_at_ms + onset_ms,
                "latency_ms": round(onset_ms - relative_ms, 3),
            }
        )

    latencies = [sample["latency_ms"] for sample in samples]
    return {
        "wav": {
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "frame_count": frame_count,
        },
        "detector": {
            "threshold": threshold,
            "hold_ms": hold_ms,
            "max_latency_ms": max_latency_ms,
        },
        "samples": samples,
        "summary": summarize(latencies),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.1)
    parser.add_argument("--hold-ms", type=float, default=10)
    parser.add_argument("--max-latency-ms", type=float, default=5000)
    args = parser.parse_args()
    recording_start, triggers = load_manifest(args.manifest)
    result = analyze_recording(
        args.wav,
        recording_started_at_ms=recording_start,
        trigger_timestamps_ms=triggers,
        threshold=args.threshold,
        hold_ms=args.hold_ms,
        max_latency_ms=args.max_latency_ms,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
