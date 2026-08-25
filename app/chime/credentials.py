"""Credential providers for the direct chime API."""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("unifi-announcer")


class StaticEnvCredentialProvider:
    name = "static-env"
    refreshable = False

    def __init__(self, password: str) -> None:
        self.password = password

    async def get(self, force_refresh: bool = False) -> str:
        if force_refresh:
            raise RuntimeError("static credential cannot refresh - re-set CHIME_DIRECT_PASSWORD")
        if not self.password:
            raise RuntimeError("direct chime credential is not configured")
        return self.password

    async def invalidate(self) -> None:
        return None


class FileCredentialProvider:
    name = "file"
    refreshable = True

    def __init__(self, path: str) -> None:
        self.path = path
        self._cached: str | None = None
        self._mtime: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, force_refresh: bool = False) -> str:
        async with self._lock:
            try:
                mtime = os.stat(self.path).st_mtime
            except OSError as exc:
                raise RuntimeError(f"credential file unreadable: {exc}") from exc
            if force_refresh or self._cached is None or mtime != self._mtime:
                with open(self.path) as source:
                    self._cached = source.read().strip()
                self._mtime = mtime
                log.info("credential refreshed from %s", self.path)
            if not self._cached:
                raise RuntimeError("direct chime credential file is empty")
            return self._cached

    async def invalidate(self) -> None:
        async with self._lock:
            self._cached = None
