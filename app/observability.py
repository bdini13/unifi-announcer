"""Process-local stage timings and low-overhead metrics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf
from time import perf_counter_ns


@dataclass
class AnnouncementTiming:
    announce_total_ms: float | None = None
    tts_ms: float | None = None
    pcm_process_ms: float | None = None
    encode_ms: float | None = None
    upload_ms: float | None = None
    play_request_ms: float | None = None
    queue_wait_ms: float | None = None
    camera_prepare_ms: float | None = None

    def __post_init__(self) -> None:
        self._starts: dict[str, int] = {}

    def start(self, stage: str) -> None:
        self._starts[stage] = perf_counter_ns()

    def stop(self, stage: str) -> float:
        elapsed = (perf_counter_ns() - self._starts.pop(stage)) / 1_000_000
        setattr(self, f"{stage}_ms", elapsed)
        return elapsed

    def set(self, stage: str, value: float) -> None:
        setattr(self, f"{stage}_ms", value)

    def as_dict(self) -> dict[str, float]:
        return {
            name: value
            for name, value in asdict(self).items()
            if value is not None
        }


class MetricsRegistry:
    HISTOGRAMS = (
        "announce_total_ms",
        "tts_ms",
        "pcm_process_ms",
        "encode_ms",
        "upload_ms",
        "play_request_ms",
        "queue_wait_ms",
        "slot_acquire_ms",
        "slot_preflight_ms",
        "slot_direct_upload_ms",
        "slot_sync_ms",
        "slot_settle_ms",
        "slot_prepare_ms",
        "camera_prepare_ms",
    )
    COUNTERS = (
        "cache_hits",
        "cache_misses",
        "tts_host_cache_hits",
        "tts_host_cache_misses",
        "tts_cache_evictions",
        "direct_fallback",
        "direct_401",
        "ringtone_capacity_retries",
        "rules_fired",
        "rules_suppressed",
        "queue_deduped",
        "queue_dropped",
        "dispatch_played",
        "dispatch_suppressed",
        "dispatch_deduped",
        "dispatch_dropped",
        "dispatch_partial",
        "dispatch_failed",
        "tts_slot_content_hits",
        "tts_slot_content_misses",
        "tts_slot_content_partial_hits",
        "tts_slot_overwrite_skips",
        "tts_slot_overwrites",
        "tts_slot_sync_successes",
        "tts_slot_sync_stale_inventory_accepts",
        "tts_slot_sync_timeouts",
        "tts_slot_sync_ownership_drift",
        "tts_slot_content_restart_validations",
        "tts_slot_content_restart_invalidations",
        "tts_slot_content_lifecycle_invalidations",
        "tts_slot_content_state_resets",
    )

    def __init__(self) -> None:
        self._counters = {name: 0 for name in self.COUNTERS}
        self._histograms = {
            name: {
                "count": 0,
                "sum": 0.0,
                "min": inf,
                "max": 0.0,
            }
            for name in self.HISTOGRAMS
        }

    def inc(self, name: str, amount: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + amount

    def observe(self, name: str, value: float) -> None:
        # Keep custom/future instrumentation fail-safe: a new histogram must
        # never break playback merely because it was not predeclared.
        h = self._histograms.setdefault(
            name,
            {"count": 0, "sum": 0.0, "min": inf, "max": 0.0},
        )
        h["count"] += 1
        h["sum"] += value
        h["min"] = min(h["min"], value)
        h["max"] = max(h["max"], value)

    def snapshot(self) -> dict:
        histograms = {}
        for name, raw in self._histograms.items():
            h = dict(raw)
            if not h["count"]:
                h["min"] = 0.0
            h["avg"] = h["sum"] / h["count"] if h["count"] else 0.0
            histograms[name] = h
        return {
            "counters": dict(self._counters),
            "histograms": histograms,
        }
