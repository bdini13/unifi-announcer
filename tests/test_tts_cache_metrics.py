from pathlib import Path

import pytest

from app.audio.bounded_cache import BoundedTtsSynthesizer


class FakeMetrics:
    def __init__(self):
        self.counters = {}

    def inc(self, name, amount=1):
        self.counters[name] = self.counters.get(name, 0) + amount


@pytest.mark.asyncio
async def test_host_tts_cache_metrics_distinguish_hit_and_miss(tmp_path):
    metrics = FakeMetrics()
    calls = []

    def key_factory(text):
        return text.replace(" ", "-")

    async def delegate(text):
        calls.append(text)
        path = Path(tmp_path) / f"{key_factory(text)}.mp3"
        if path.exists() and path.stat().st_size:
            return path.read_bytes()
        data = f"audio:{text}".encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data

    cache = BoundedTtsSynthesizer(
        delegate,
        cache_dir=tmp_path,
        key_factory=key_factory,
        metrics=metrics,
    )

    first = await cache("hello")
    second = await cache("hello")

    assert first == second
    assert calls == ["hello", "hello"]
    assert metrics.counters["tts_host_cache_misses"] == 1
    assert metrics.counters["tts_host_cache_hits"] == 1
