"""Background component health with constant-time snapshot reads."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


_COMPONENTS = ("protect", "event_stream", "direct_device", "mqtt", "chimes")


class BackgroundHealth:
    """Refresh external state off the request path and expose cached snapshots."""

    def __init__(
        self,
        *,
        protect_check: Callable[[], Awaitable[int]],
        local_state: Callable[[], dict[str, tuple[str, str]]],
        interval_seconds: float = 30,
    ) -> None:
        self._protect_check = protect_check
        self._local_state = local_state
        self._interval_seconds = interval_seconds
        self._components: dict[str, dict[str, str]] = {
            name: {"status": "unknown", "detail": "not_checked"} for name in _COMPONENTS
        }
        self._task: asyncio.Task[Any] | None = None

    def set_component(self, name: str, status: str, detail: str) -> None:
        if name not in self._components:
            raise ValueError(f"unknown health component: {name}")
        self._components[name] = {"status": status, "detail": detail}

    def snapshot(self) -> dict[str, Any]:
        components = {name: dict(value) for name, value in self._components.items()}
        degraded = any(
            value["status"] in {"degraded", "error"} for value in components.values()
        )
        return {"status": "degraded" if degraded else "ok", "components": components}

    async def refresh(self) -> None:
        try:
            chime_count = await self._protect_check()
        except Exception as exc:
            self.set_component("protect", "error", type(exc).__name__)
            self.set_component("chimes", "error", "protect_unavailable")
        else:
            self.set_component("protect", "ok", "background_check")
            chime_status = "ok" if chime_count else "degraded"
            self.set_component("chimes", chime_status, f"{chime_count} discovered")

        try:
            local = self._local_state()
        except Exception as exc:
            local = {
                name: ("error", type(exc).__name__)
                for name in ("event_stream", "direct_device", "mqtt")
            }
        for name in ("event_stream", "direct_device", "mqtt"):
            if name in local:
                status, detail = local[name]
                self.set_component(name, status, detail)

    async def _run(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(self._interval_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
