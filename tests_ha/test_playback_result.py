"""Playback-result state regressions for Home Assistant controls."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_announcer import async_setup_entry
from custom_components.unifi_announcer.api import (
    CommandResult,
    PlaybackFailed,
    UniFiAnnouncerClient,
)
from custom_components.unifi_announcer.const import DOMAIN


BASE_DATA = {
    "url": "http://announcer.local:8095",
    "api_key": "test-key",
    "verify_ssl": False,
    "instance_name": "UniFi Announcer",
}


async def _setup(hass, play_preset):
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
            AsyncMock(return_value={"version": "2.1.5", "service": "unifi-announcer"}),
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
                "chimes": [{"name": "default", "id": "chime-1", "queue_depth": 0}],
                "groups": {},
            }),
        ),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_presets",
            AsyncMock(return_value=[{"name": "package-delivered", "slot_backed": True}]),
        ),
        patch.object(UniFiAnnouncerClient, "async_play_preset", play_preset),
    )
    for item in patches:
        item.start()
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    finally:
        for item in reversed(patches[:-1]):
            # Keep the play-preset patch alive for the caller's button press.
            item.stop()

    entry.runtime_data.preset_selection["default"] = "package-delivered"
    registry = er.async_get(hass)
    preset_button = next(
        entity.entity_id
        for entity in registry.entities.values()
        if entity.config_entry_id == entry.entry_id
        and entity.unique_id == f"{entry.entry_id}_chime-1_preset"
    )
    result_sensor = next(
        entity.entity_id
        for entity in registry.entities.values()
        if entity.config_entry_id == entry.entry_id
        and entity.unique_id == f"{entry.entry_id}_chime-1_last_disposition"
    )
    return entry, preset_button, result_sensor, patches[-1]


async def test_preset_button_updates_last_playback_result_to_success(hass):
    play = AsyncMock(return_value=CommandResult(
        "played", {"disposition": "played"}, 200
    ))
    entry, button_entity, sensor_entity, play_patch = await _setup(hass, play)
    try:
        assert hass.states.get(sensor_entity).state == "unknown"
        await hass.services.async_call(
            "button", "press", {"entity_id": button_entity}, blocking=True
        )
        await hass.async_block_till_done()

        play.assert_awaited_once_with("package-delivered", target="default")
        assert hass.states.get(sensor_entity).state == "success"
    finally:
        play_patch.stop()
        await hass.config_entries.async_unload(entry.entry_id)


async def test_preset_button_updates_last_playback_result_to_failure(hass):
    play = AsyncMock(side_effect=PlaybackFailed("Protect playback rejected"))
    entry, button_entity, sensor_entity, play_patch = await _setup(hass, play)
    try:
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "button", "press", {"entity_id": button_entity}, blocking=True
            )
        await hass.async_block_till_done()

        assert hass.states.get(sensor_entity).state == "failure"
    finally:
        play_patch.stop()
        await hass.config_entries.async_unload(entry.entry_id)
