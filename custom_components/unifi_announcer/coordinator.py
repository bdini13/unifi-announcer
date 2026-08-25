"""Coordinator for UniFi Announcer Home Assistant state."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UniFiAnnouncerError
from .const import DOMAIN


class UniFiAnnouncerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll lightweight service/chime state and refresh presets less often."""

    def __init__(self, hass, client, interval: int = 30) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self._presets: list[dict[str, Any]] = []
        self._preset_tick = 0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            health, chimes = await asyncio.gather(
                self.client.async_get_health(),
                self.client.async_get_chimes(),
            )
            self._preset_tick += 1
            if not self._presets or self._preset_tick >= 3:
                self._presets = await self.client.async_get_presets()
                self._preset_tick = 0
            return {"health": health, "chimes": chimes, "presets": self._presets}
        except UniFiAnnouncerError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_refresh_presets(self) -> None:
        """Refresh presets immediately after a user-facing preset operation."""
        self._presets = await self.client.async_get_presets()
        self._preset_tick = 0
        if self.data is not None:
            self.async_set_updated_data({**self.data, "presets": self._presets})
