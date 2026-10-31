"""Lifecycle-owned retries for unavailable fixed slots, preserving proof checks."""
from __future__ import annotations

import asyncio


class SlotRecovery:
    def __init__(self, manager, startup, *, interval: float = 30,
                 timeout: float = 90) -> None:
        self.manager = manager
        self.startup = startup
        self.interval = interval
        self.timeout = timeout
        self.task = None

    async def attempt(self) -> dict:
        try:
            async with asyncio.timeout(self.timeout):
                return await self.startup()
        except Exception as exc:
            self.manager.ready = False
            self.manager.last_error = f"{type(exc).__name__}: slot startup did not complete"
            return self.manager.status()

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self.manager.ready:
            await asyncio.sleep(self.interval)
            await self.attempt()

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
