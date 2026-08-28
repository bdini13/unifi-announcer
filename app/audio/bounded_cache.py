"""Bounded LRU policy for the disk-backed TTS MP3 cache."""
from __future__ import annotations

import asyncio
from pathlib import Path
import os
from typing import Awaitable, Callable


class BoundedTtsSynthesizer:
    """Wrap the existing content-addressed synthesizer with LRU disk pruning."""

    def __init__(
        self,
        delegate: Callable[[str], Awaitable[bytes]],
        *,
        cache_dir: str | Path,
        key_factory: Callable[[str], str],
        max_files: int = 256,
        max_bytes: int = 256 * 1024 * 1024,
        metrics=None,
    ) -> None:
        self.delegate = delegate
        self.cache_dir = Path(cache_dir)
        self.key_factory = key_factory
        self.max_files = max(2, int(max_files))
        self.max_bytes = max(1, int(max_bytes))
        self.metrics = metrics
        self._prune_lock = asyncio.Lock()
        self._last_stats = {"files": 0, "bytes": 0, "evicted": 0}

    async def __call__(self, text: str) -> bytes:
        data = await self.delegate(text)
        path = self.cache_dir / f"{self.key_factory(text)}.mp3"
        try:
            if path.exists():
                os.utime(path, None)
        except OSError:
            pass
        await self.prune()
        return data

    async def startup(self) -> dict:
        return await self.prune()

    async def prune(self) -> dict:
        async with self._prune_lock:
            stats = await asyncio.to_thread(self._prune_sync)
            self._last_stats = stats
            if self.metrics is not None and hasattr(self.metrics, "inc") and stats["evicted"]:
                self.metrics.inc("tts_cache_evictions", stats["evicted"])
            return stats

    def _prune_sync(self) -> dict:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        for path in self.cache_dir.glob("*.mp3"):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((stat.st_mtime, path, stat.st_size))
        entries.sort(key=lambda item: item[0])
        total = sum(size for _, _, size in entries)
        evicted = 0
        undeletable = []
        while entries and (
            len(entries) + len(undeletable) > self.max_files
            or total > self.max_bytes
        ):
            entry = entries.pop(0)
            _, path, size = entry
            try:
                path.unlink(missing_ok=True)
                total -= size
                evicted += 1
            except OSError:
                # Keep failed entries in accounting while trying other candidates.
                undeletable.append(entry)
        remaining = undeletable + entries
        return {"files": len(remaining), "bytes": max(0, total), "evicted": evicted,
                "max_files": self.max_files, "max_bytes": self.max_bytes}

    def stats(self) -> dict:
        return dict(self._last_stats)
