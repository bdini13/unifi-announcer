from unittest.mock import patch

import httpx
import pytest

from app.observability import AnnouncementTiming, MetricsRegistry
from scripts.benchmark import percentile, summarize


def test_announcement_timing_uses_perf_counter_ns():
    timing = AnnouncementTiming()
    with patch("app.observability.perf_counter_ns", side_effect=[1_000_000, 4_500_000]):
        timing.start("tts")
        timing.stop("tts")
    assert timing.tts_ms == 3.5
    assert timing.as_dict() == {"tts_ms": 3.5}


def test_unmeasured_stages_are_not_reported_as_zero():
    timing = AnnouncementTiming()
    timing.set("announce_total", 1.25)
    assert timing.as_dict() == {"announce_total_ms": 1.25}


def test_metrics_registry_exposes_required_histograms_and_counters():
    metrics = MetricsRegistry()
    metrics.observe("announce_total_ms", 12.5)
    metrics.inc("cache_hits")
    snapshot = metrics.snapshot()
    assert snapshot["histograms"]["announce_total_ms"]["count"] == 1
    assert snapshot["histograms"]["announce_total_ms"]["max"] == 12.5
    for name in ("cache_hits", "cache_misses", "direct_fallback", "direct_401",
                 "rules_fired", "queue_deduped", "queue_dropped"):
        assert name in snapshot["counters"]


def test_benchmark_percentiles_are_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 99) == 99
    assert summarize(values) == {
        "count": 100, "min": 1, "p50": 50, "p90": 90,
        "p95": 95, "p99": 99, "max": 100,
    }


@pytest.mark.asyncio
async def test_metrics_json_is_in_memory_and_timing_header_is_debug_only(main_module):
    main_module.metrics.inc("cache_hits")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics/json", headers={"X-API-Key": "configured-test-key"})
        health = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["counters"]["cache_hits"] >= 1
    assert "X-Process-Time-ms" not in health.headers
