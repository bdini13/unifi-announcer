import os
from pathlib import Path

import pytest

from app.audio.bounded_cache import BoundedTtsSynthesizer


@pytest.mark.asyncio
async def test_bounded_cache_prunes_oldest_files_by_count(tmp_path):
    cache = tmp_path / "tts"
    cache.mkdir()
    for index in range(5):
        path = cache / f"old-{index}.mp3"
        path.write_bytes(b"x" * 10)
        os.utime(path, (100 + index, 100 + index))

    async def delegate(text):
        path = cache / f"{text}.mp3"
        path.write_bytes(text.encode())
        return text.encode()

    synth = BoundedTtsSynthesizer(
        delegate, cache_dir=cache, key_factory=lambda text: text,
        max_files=3, max_bytes=10_000,
    )

    await synth("new")

    files = sorted(path.name for path in cache.glob("*.mp3"))
    assert len(files) == 3
    assert "new.mp3" in files
    assert "old-0.mp3" not in files
    assert "old-1.mp3" not in files
    assert "old-2.mp3" not in files


@pytest.mark.asyncio
async def test_bounded_cache_prunes_to_byte_limit(tmp_path):
    cache = tmp_path / "tts"
    cache.mkdir()
    for index in range(4):
        path = cache / f"{index}.mp3"
        path.write_bytes(b"x" * 25)
        os.utime(path, (100 + index, 100 + index))

    async def delegate(text):
        return b"cached"

    synth = BoundedTtsSynthesizer(
        delegate, cache_dir=cache, key_factory=lambda text: text,
        max_files=20, max_bytes=50,
    )

    stats = await synth.startup()

    assert stats["bytes"] <= 50
    assert stats["files"] <= 2
    assert Path(cache, "0.mp3").exists() is False


@pytest.mark.asyncio
async def test_bounded_cache_counts_undeletable_entries(monkeypatch, tmp_path):
    cache = tmp_path / "tts"
    cache.mkdir()
    for index in range(3):
        (cache / f"{index}.mp3").write_bytes(b"x" * 10)

    original_unlink = Path.unlink

    def refuse_mp3_unlink(path, *args, **kwargs):
        if path.suffix == ".mp3":
            raise PermissionError("undeletable")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_mp3_unlink)

    async def delegate(_text):
        return b"cached"

    synth = BoundedTtsSynthesizer(
        delegate, cache_dir=cache, key_factory=lambda text: text,
        max_files=20, max_bytes=15,
    )

    stats = await synth.startup()

    assert stats["files"] == 3
    assert stats["bytes"] == 30
    assert stats["bytes"] > stats["max_bytes"]
    assert stats["evicted"] == 0
