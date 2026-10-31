"""Cancellation cannot race an executor write and resurrect temporary audio."""
import asyncio
from pathlib import Path
import threading
from unittest.mock import AsyncMock

import pytest

from app.audio import media_ingest
from app.audio.media_ingest import AudioMediaNormalizer


@pytest.fixture
def delayed_writer(tmp_path, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    paths = []
    state = {"fail": False}
    original_write = Path.write_bytes
    original_create = media_ingest.tempfile.mkstemp

    def create(**kwargs):
        return original_create(dir=tmp_path, **kwargs)

    def write(path, payload):
        if path.parent != tmp_path:
            return original_write(path, payload)
        paths.append(path)
        started.set()
        try:
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release file writer")
            if state["fail"]:
                raise OSError("synthetic disk failure")
            return original_write(path, payload)
        finally:
            finished.set()

    monkeypatch.setattr(media_ingest.tempfile, "mkstemp", create)
    monkeypatch.setattr(Path, "write_bytes", write)
    yield started, release, finished, paths, state
    release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 2])
@pytest.mark.parametrize("disk_failure", [False, True])
async def test_cancelled_media_joins_writer_before_unlink(delayed_writer, cancel_count, disk_failure):
    started, release, finished, paths, state = delayed_writer
    state["fail"] = disk_failure
    normalizer = AudioMediaNormalizer()
    normalizer._probe_duration = AsyncMock(side_effect=AssertionError("cancelled media must not decode"))
    task = asyncio.create_task(normalizer.normalize(b"bounded audio", "audio/wav"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        for _ in range(cancel_count):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()  # Cleanup cannot outrun the still-running writer.
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        assert paths and all(not path.exists() for path in paths)
        normalizer._probe_duration.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_media_deadline_preserves_timeout_after_file_cleanup(delayed_writer):
    started, release, finished, paths, _ = delayed_writer
    normalizer = AudioMediaNormalizer()
    normalizer._probe_duration = AsyncMock(side_effect=AssertionError("expired media must not decode"))

    async def prepare():
        async with asyncio.timeout(0.01):
            await normalizer.normalize(b"bounded audio", "audio/wav")

    task = asyncio.create_task(prepare())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        with pytest.raises(TimeoutError):
            await task
        assert finished.is_set()
        assert paths and all(not path.exists() for path in paths)
        normalizer._probe_duration.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
