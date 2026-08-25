"""Preset selectors for each configured chime/group."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .entity import UniFiAnnouncerEntity, configured_targets


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([
        UniFiAnnouncerPresetSelect(entry, coordinator, target, chime_id, is_group)
        for target, chime_id, is_group in configured_targets(coordinator)
    ])


class UniFiAnnouncerPresetSelect(UniFiAnnouncerEntity, SelectEntity):
    """Choose the preset used by the companion Play Preset button."""

    _attr_translation_key = "preset"
    _attr_name = None

    def __init__(self, entry, coordinator, target, chime_id, is_group) -> None:
        super().__init__(entry, coordinator, target, chime_id, is_group)
        self._attr_unique_id = f"{entry.entry_id}_{target}_preset_select"

    @property
    def options(self) -> list[str]:
        return sorted({
            str(item.get("name"))
            for item in (self.coordinator.data or {}).get("presets", [])
            if item.get("name")
        })

    @property
    def current_option(self) -> str | None:
        selected = self.runtime.preset_selection.get(self.target)
        return selected if selected in self.options else None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unknown preset: {option}")
        self.runtime.preset_selection[self.target] = option
        self.async_write_ha_state()
