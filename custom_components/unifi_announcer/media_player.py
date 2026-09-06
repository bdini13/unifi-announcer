"""Honest media_player targets for text and existing presets."""
from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature
from homeassistant.const import STATE_IDLE
from homeassistant.exceptions import HomeAssistantError

from .api import UniFiAnnouncerError
from .entity import (
    UniFiAnnouncerEntity,
    configured_announcement_targets,
    target_supports,
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([
        UniFiAnnouncerMediaPlayer(
            entry, coordinator, target, target_id, is_group, target_type
        )
        for target, target_id, is_group, target_type
        in configured_announcement_targets(coordinator)
    ])


class UniFiAnnouncerMediaPlayer(UniFiAnnouncerEntity, MediaPlayerEntity):
    """Announcement target; not a streaming transport."""

    _attr_supported_features = MediaPlayerEntityFeature.PLAY_MEDIA
    _attr_state = STATE_IDLE
    _attr_translation_key = "speaker"
    _attr_name = "Announcement player"

    def __init__(
        self, entry, coordinator, target, target_id, is_group, target_type="chime"
    ) -> None:
        super().__init__(
            entry, coordinator, target, target_id, is_group, target_type
        )
        self._attr_unique_id = f"{entry.entry_id}_{self.entity_key}_media_player"

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        try:
            if media_type == "text":
                if not media_id or not media_id.strip():
                    self.runtime.record_playback_result(self.target, "failed")
                    raise HomeAssistantError("Announcement text cannot be empty")
                result = await self.runtime.client.async_announce(media_id.strip(), target=self.target)
            elif media_type == "unifi-announcer/preset":
                if not target_supports(
                    self.coordinator, self.target, "play_preset"
                ):
                    self.runtime.record_playback_result(self.target, "failed")
                    raise HomeAssistantError(
                        "This target does not support ringtone preset playback"
                    )
                result = await self.runtime.client.async_play_preset(media_id, target=self.target)
            else:
                self.runtime.record_playback_result(self.target, "failed")
                raise HomeAssistantError(
                    "UniFi Announcer v2.1 supports media_content_type 'text' and "
                    "'unifi-announcer/preset'. Native tts.speak/media-source support is planned for v2.2."
                )
        except UniFiAnnouncerError as exc:
            self.runtime.record_playback_result(self.target, "failed")
            raise HomeAssistantError(str(exc)) from exc
        self.runtime.record_playback_result(self.target, result.disposition)
