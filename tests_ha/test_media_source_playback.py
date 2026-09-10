"""Native Home Assistant media-source playback regressions."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_announcer.api import CommandResult, UniFiAnnouncerClient
from custom_components.unifi_announcer.const import DOMAIN


BASE_DATA = {
    "url": "http://announcer.local:8095",
    "api_key": "test-key",
    "verify_ssl": False,
    "instance_name": "UniFi Announcer",
}


async def _setup(hass, announce_media: AsyncMock):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="UniFi Announcer",
        data=BASE_DATA,
        unique_id=BASE_DATA["url"],
    )
    entry.add_to_hass(hass)

    patches = (
        patch.object(UniFiAnnouncerClient, "async_check_auth", AsyncMock(return_value=None)),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_version",
            AsyncMock(return_value={"version": "2.2.0-beta.4", "service": "unifi-announcer"}),
        ),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_health",
            AsyncMock(return_value={"status": "ok"}),
        ),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_chimes",
            AsyncMock(return_value={
                "chimes": [{
                    "name": "default",
                    "id": "chime-1",
                    "queue_depth": 0,
                    "capability_state": {"status": "available"},
                    "capabilities": {"announce": True},
                }],
                "cameras": [],
                "groups": {},
                "group_capabilities": {},
            }),
        ),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_presets",
            AsyncMock(return_value=[]),
        ),
        patch.object(UniFiAnnouncerClient, "async_announce_media", announce_media),
    )
    for item in patches:
        item.start()
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    finally:
        for item in reversed(patches[:-1]):
            item.stop()

    registry = er.async_get(hass)
    player = next(
        entity.entity_id
        for entity in registry.entities.values()
        if entity.config_entry_id == entry.entry_id
        and entity.unique_id == f"{entry.entry_id}_chime-1_media_player"
    )
    return entry, player, patches[-1]


async def test_media_player_forwards_resolved_media_source_bytes(hass):
    announce_media = AsyncMock(return_value=CommandResult(
        "played", {"disposition": "played"}, 200
    ))
    entry, player, media_patch = await _setup(hass, announce_media)
    resolver = AsyncMock(return_value=(b"generated-audio", "audio/mpeg"))

    try:
        with patch(
            "custom_components.unifi_announcer.media_player.async_resolve_media_bytes",
            resolver,
        ):
            await hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": player,
                    "media_content_id": "media-source://tts/test-announcement",
                    "media_content_type": "music",
                },
                blocking=True,
            )
            await hass.async_block_till_done()

        resolver.assert_awaited_once_with(
            hass, "media-source://tts/test-announcement", player
        )
        announce_media.assert_awaited_once_with(
            b"generated-audio", "audio/mpeg", target="default"
        )
        assert entry.runtime_data.last_disposition["default"] == "success"
    finally:
        media_patch.stop()
        await hass.config_entries.async_unload(entry.entry_id)


async def test_media_player_rejects_arbitrary_url_playback(hass):
    announce_media = AsyncMock(return_value=CommandResult(
        "played", {"disposition": "played"}, 200
    ))
    entry, player, media_patch = await _setup(hass, announce_media)

    try:
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": player,
                    "media_content_id": "https://example.invalid/audio.mp3",
                    "media_content_type": "music",
                },
                blocking=True,
            )
        announce_media.assert_not_awaited()
        assert entry.runtime_data.last_disposition["default"] == "failure"
    finally:
        media_patch.stop()
        await hass.config_entries.async_unload(entry.entry_id)
