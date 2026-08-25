"""Protect protocol boundary and lazy HTTP transport.

Reverse-engineered and verified with UniFi Protect Smart Chime firmware
v1.7.20. Direct operations fail closed on unknown firmware; playback uses the
Protect/NVR play-speaker endpoint.
"""
from __future__ import annotations

from typing import Any

import httpx

PROTOCOL_NOTES = "verified UP Chime fw v1.7.20; undocumented read/write; NVR fallback"


class LazyAsyncClient:
    """Create ``httpx.AsyncClient`` only on first network operation."""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.instance: httpx.AsyncClient | None = None

    def get(self) -> httpx.AsyncClient:
        if self.instance is None:
            self.instance = httpx.AsyncClient(**self.options)
        return self.instance

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self.get().post(*args, **kwargs)

    async def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self.get().request(*args, **kwargs)

    async def aclose(self) -> None:
        if self.instance is not None:
            await self.instance.aclose()
            self.instance = None
