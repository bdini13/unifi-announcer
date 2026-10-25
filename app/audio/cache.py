"""In-memory ringtone index for the NVR lookup control plane."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable


class RingtoneIndex:
    """Name-indexed snapshot; the playback hot path is always local.

    Full-list refresh is intentionally limited to startup, authenticated admin
    refresh, not-found recovery, and upload reconciliation.
    """

    def __init__(self, loader: Callable[[], Awaitable[list[dict]]] | None = None) -> None:
        self._loader = loader
        self._by_name: dict[str, dict] = {}
        self._ambiguous_names: set[str] = set()
        self._loaded = False
        self.last_refresh_at: str | None = None
        self.refresh_count = 0
        self._refresh_lock = asyncio.Lock()

    def bind(self, loader: Callable[[], Awaitable[list[dict]]]) -> None:
        self._loader = loader

    async def load(self, *, force: bool = False) -> None:
        if self._loader is None:
            raise RuntimeError("RingtoneIndex loader is not bound")
        observed_generation = self.refresh_count
        async with self._refresh_lock:
            # Normal concurrent callers coalesce. Destructive-state callers use
            # force_refresh so their snapshot is guaranteed to begin afterward.
            if not force and self.refresh_count != observed_generation:
                return
            tones = await self._loader()
            by_name: dict[str, dict] = {}
            ambiguous = set()
            for tone in tones:
                if not tone.get("name"):
                    continue
                name = str(tone["name"]).lower()
                if name in by_name:
                    ambiguous.add(name)
                else:
                    by_name[name] = tone
            self._by_name = {name: tone for name, tone in by_name.items()
                             if name not in ambiguous}
            self._ambiguous_names = ambiguous
            self._loaded = True
            self.last_refresh_at = datetime.now(timezone.utc).isoformat()
            self.refresh_count += 1

    refresh = load

    async def force_refresh(self) -> None:
        """Always load a snapshot after earlier in-flight refreshes complete."""
        await self.load(force=True)

    def get(self, name: str) -> dict | None:
        if name.lower() in self._ambiguous_names:
            raise RuntimeError(f"Ringtone name '{name}' is ambiguous; reconcile duplicate IDs")
        return self._by_name.get(name.lower())

    def put(self, tone: dict) -> None:
        if tone and tone.get("name"):
            self._by_name[str(tone["name"]).lower()] = tone

    def invalidate(self, name: str) -> None:
        self._by_name.pop(name.lower(), None)

    async def resolve_or_refresh(self, name: str) -> dict | None:
        tone = self.get(name)
        if tone is None:
            await self.load()
            tone = self.get(name)
        return tone

    @property
    def loaded(self) -> bool:
        return self._loaded

    def status(self) -> dict:
        return {"loaded": self.loaded, "entries": len(self._by_name), "ambiguous_entries": len(self._ambiguous_names), "last_refresh_at": self.last_refresh_at, "refresh_count": self.refresh_count}
