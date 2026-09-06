"""Buttons for buzzer, default tone, and selected preset playback."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .api import UniFiAnnouncerError
from .entity import UniFiAnnouncerEntity, configured_targets, target_supports


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.coordinator
    entities = []
    for target, chime_id, is_group in configured_targets(coordinator):
        for kind, capability in (
            ("buzzer", "buzzer"),
            ("default", "play_default"),
            ("preset", "play_preset"),
        ):
            if target_supports(coordinator, target, capability):
                entities.append(
                    UniFiAnnouncerButton(
                        entry, coordinator, target, chime_id, is_group, kind
                    )
                )
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
                    self.runtime.record_playback_result(self.target, "failed")
                    raise HomeAssistantError("Select a preset first")
                result = await self.runtime.client.async_play_preset(preset, target=self.target)
        except UniFiAnnouncerError as exc:
            self.runtime.record_playback_result(self.target, "failed")
            raise HomeAssistantError(str(exc)) from exc
        self.runtime.record_playback_result(self.target, result.disposition)
