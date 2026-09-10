"""Announcement media_player targets for text, presets, and HA media sources."""
from __future__ import annotations

from homeassistant.components import media_source
from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature
from homeassistant.const import STATE_IDLE
from homeassistant.exceptions import HomeAssistantError

from .api import UniFiAnnouncerError
from .entity import (
    UniFiAnnouncerEntity,
    configured_announcement_targets,
    target_supports,
)
from .media import async_resolve_media_bytes


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
    """Announcement target; media is bounded and forwarded, never streamed."""

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

    @property
    def available(self) -> bool:
        return bool(
            super().available
            and target_supports(self.coordinator, self.target, "announce")
        )

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        try:
            if media_type == "text":
                if not media_id or not media_id.strip():
                    self.runtime.record_playback_result(self.target, "failed")
                    raise HomeAssistantError("Announcement text cannot be empty")
                if not self.available:
                    self.runtime.record_playback_result(self.target, "failed")
                    raise HomeAssistantError(
                        "This announcement target is currently unavailable"
                    )
                result = await self.runtime.client.async_announce(
                    media_id.strip(), target=self.target
                )
            elif media_type == "unifi-announcer/preset":
                if not target_supports(
                    self.coordinator, self.target, "play_preset"
                ):
                    self.runtime.record_playback_result(self.target, "failed")
                    raise HomeAssistantError(
                        "This target does not support ringtone preset playback"
                    )
                result = await self.runtime.client.async_play_preset(
                    media_id, target=self.target
                )
            elif media_source.is_media_source_id(media_id):
                if not self.available:
                    self.runtime.record_playback_result(self.target, "failed")
                    raise HomeAssistantError(
                        "This announcement target is currently unavailable"
                    )
                audio, content_type = await async_resolve_media_bytes(
                    self.hass, media_id, self.entity_id
                )
                result = await self.runtime.client.async_announce_media(
                    audio, content_type, target=self.target
                )
            else:
                self.runtime.record_playback_result(self.target, "failed")
                raise HomeAssistantError(
                    "UniFi Announcer supports media_content_type 'text', "
                    "'unifi-announcer/preset', and Home Assistant media-source URIs."
                )
        except UniFiAnnouncerError as exc:
            self.runtime.record_playback_result(self.target, "failed")
            raise HomeAssistantError(str(exc)) from exc
        self.runtime.record_playback_result(self.target, result.disposition)
