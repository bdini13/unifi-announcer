"""Buttons for buzzer, default tone, and selected preset playback."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .api import PlaybackFailed
from .entity import UniFiAnnouncerEntity, configured_targets


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.coordinator
    entities = []
    for target, chime_id, is_group in configured_targets(coordinator):
        entities.extend([
            UniFiAnnouncerButton(entry, coordinator, target, chime_id, is_group, "buzzer"),
            UniFiAnnouncerButton(entry, coordinator, target, chime_id, is_group, "default"),
            UniFiAnnouncerButton(entry, coordinator, target, chime_id, is_group, "preset"),
        ])
    async_add_entities(entities)


class UniFiAnnouncerButton(UniFiAnnouncerEntity, ButtonEntity):
    """One safe playback action for a target."""

    def __init__(self, entry, coordinator, target, chime_id, is_group, kind: str) -> None:
        super().__init__(entry, coordinator, target, chime_id, is_group)
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{self.entity_key}_{kind}"
        self._attr_translation_key = f"play_{kind}"
        self._attr_name = {
            "buzzer": "Play buzzer",
            "default": "Play default ringtone",
            "preset": "Play selected preset",
        }[kind]

    async def async_press(self) -> None:
        try:
            if self.kind == "buzzer":
                result = await self.runtime.client.async_buzzer(self.target)
            elif self.kind == "default":
                result = await self.runtime.client.async_play_default(target=self.target)
            else:
                preset = self.runtime.preset_selection.get(self.target)
                if not preset:
                    raise HomeAssistantError("Select a preset first")
                result = await self.runtime.client.async_play_preset(preset, target=self.target)
        except PlaybackFailed as exc:
            raise HomeAssistantError(str(exc)) from exc
        self.runtime.last_disposition[self.target] = result.disposition
