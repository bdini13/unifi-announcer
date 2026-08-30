"""Notify entities for text announcements."""
from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.exceptions import HomeAssistantError

from .api import UniFiAnnouncerError
from .entity import UniFiAnnouncerEntity, configured_targets


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.coordinator
    entities = [
        UniFiAnnouncerNotify(entry, coordinator, target, chime_id, is_group)
        for target, chime_id, is_group in configured_targets(coordinator)
    ]
    async_add_entities(entities)


class UniFiAnnouncerNotify(UniFiAnnouncerEntity, NotifyEntity):
    """Standard notify.send_message target for one chime or group."""

    _attr_translation_key = "announce"
    _attr_name = "Announcements"

    def __init__(self, entry, coordinator, target, chime_id, is_group) -> None:
        super().__init__(entry, coordinator, target, chime_id, is_group)
        self._attr_unique_id = f"{entry.entry_id}_{self.entity_key}_notify"

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        if not message or not message.strip():
            self.runtime.record_playback_result(self.target, "failed")
            raise HomeAssistantError("Announcement message cannot be empty")
        options = self.entry.options
        try:
            result = await self.runtime.client.async_announce(
                message.strip(),
                target=self.target,
                volume=options.get("default_volume"),
                repeat_times=options.get("default_repeat"),
            )
        except UniFiAnnouncerError as exc:
            self.runtime.record_playback_result(self.target, "failed")
            raise HomeAssistantError(str(exc)) from exc
        self.runtime.record_playback_result(self.target, result.disposition)
