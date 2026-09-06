"""Setup and entity regression tests for UniFi Announcer."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_announcer import async_setup_entry
from custom_components.unifi_announcer.api import (
    AuthenticationError,
    CannotConnect,
    CommandResult,
    UniFiAnnouncerClient,
)
from custom_components.unifi_announcer.const import DOMAIN
from custom_components.unifi_announcer.notify import UniFiAnnouncerNotify


BASE_DATA = {
    "url": "http://announcer.local:8095",
    "api_key": "test-key",
    "verify_ssl": False,
    "instance_name": "UniFi Announcer",
}


async def test_setup_invalid_key_requests_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=BASE_DATA)
    with patch.object(
        UniFiAnnouncerClient,
        "async_check_auth",
        AsyncMock(side_effect=AuthenticationError("bad key")),
    ):
        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, entry)


async def test_setup_offline_is_retryable(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=BASE_DATA)
    with patch.object(
        UniFiAnnouncerClient,
        "async_check_auth",
        AsyncMock(side_effect=CannotConnect("offline")),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


async def test_full_setup_entity_topology_and_service(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=BASE_DATA,
        options={
            "poll_interval": 30,
            "default_target": "kitchen",
            "default_volume": 0,
            "default_repeat": 2,
        },
        unique_id=BASE_DATA["url"],
    )
    entry.add_to_hass(hass)

    announce_result = CommandResult("played", {"disposition": "played"}, 200)
    announce_mock = AsyncMock(return_value=announce_result)

    with (
        patch.object(UniFiAnnouncerClient, "async_check_auth", AsyncMock(return_value=None)),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_version",
            AsyncMock(return_value={
                "version": "2.1.0-beta.2",
                "service": "unifi-announcer",
                "git_sha": "test-sha",
            }),
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
                "chimes": [
                    {
                        "name": "kitchen",
                        "id": "chime-1",
                        "queue_depth": 1,
                        "capability_state": {"status": "available"},
                    }
                ],
                "cameras": [
                    {
                        "name": "family_room_camera",
                        "id": "camera-1",
                        "target_type": "camera",
                        "queue_depth": 0,
                        "capability_state": {"status": "available"},
                        "supports": ["announce"],
                    }
                ],
                "groups": {
                    "whole_house": ["kitchen"],
                    "mixed": ["kitchen", "family_room_camera"],
                },
                "group_capabilities": {
                    "whole_house": {"announce": True, "volume": True},
                    "mixed": {"announce": True, "volume": False},
                },
            }),
        ),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_presets",
            AsyncMock(return_value=[{"name": "package-delivered"}]),
        ),
        patch.object(UniFiAnnouncerClient, "async_announce", announce_mock),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        device_registry = dr.async_get(hass)
        service_device = device_registry.async_get_device(
            identifiers={(DOMAIN, BASE_DATA["url"])}
        )
        chime_device = device_registry.async_get_device(
            identifiers={(DOMAIN, "chime-1")}
        )
        camera_device = device_registry.async_get_device(
            identifiers={(DOMAIN, "camera-1")}
        )
        assert service_device is not None
        assert chime_device is not None
        assert camera_device is not None
        assert chime_device.via_device_id == service_device.id
        assert camera_device.via_device_id == service_device.id
        assert camera_device.model == "Protect Camera Speaker"

        registry = er.async_get(hass)
        entries = [
            item for item in registry.entities.values()
            if item.config_entry_id == entry.entry_id
        ]
        unique_ids = {item.unique_id for item in entries}

        # Physical queue depth exists and follows the Protect ID.
        assert f"{entry.entry_id}_chime-1_queue_depth" in unique_ids
        # Logical groups expose dispositions/controls but no fake aggregate queue.
        assert f"{entry.entry_id}_whole_house_queue_depth" not in unique_ids
        assert f"{entry.entry_id}_whole_house_last_disposition" in unique_ids
        camera_prefix = f"{entry.entry_id}_camera-1"
        assert f"{camera_prefix}_media_player" in unique_ids
        assert f"{camera_prefix}_notify" in unique_ids
        assert f"{camera_prefix}_queue_depth" in unique_ids
        assert f"{camera_prefix}_last_disposition" in unique_ids
        assert f"{camera_prefix}_buzzer" not in unique_ids
        assert f"{camera_prefix}_default" not in unique_ids
        assert f"{camera_prefix}_preset" not in unique_ids
        assert f"{camera_prefix}_preset_select" not in unique_ids

        await hass.services.async_call(
            DOMAIN,
            "announce",
            {"message": "Test announcement"},
            blocking=True,
        )
        assert announce_mock.await_args is not None
        kwargs = announce_mock.await_args.kwargs
        assert kwargs["target"] == "kitchen"
        assert kwargs["volume"] == 0
        assert kwargs["repeat_times"] == 2

        await hass.services.async_call(
            DOMAIN,
            "announce",
            {"message": "Camera test", "target": "family_room_camera"},
            blocking=True,
        )
        assert announce_mock.await_args is not None
        camera_kwargs = announce_mock.await_args.kwargs
        assert camera_kwargs["target"] == "family_room_camera"
        assert camera_kwargs["volume"] is None
        assert camera_kwargs["repeat_times"] == 2

        mixed_notify = UniFiAnnouncerNotify(
            entry, entry.runtime_data.coordinator, "mixed", None, True, "group"
        )
        await mixed_notify.async_send_message("Mixed group test")
        assert announce_mock.await_args is not None
        mixed_kwargs = announce_mock.await_args.kwargs
        assert mixed_kwargs["target"] == "mixed"
        assert mixed_kwargs["volume"] is None

        assert hass.services.has_service(DOMAIN, "announce")
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not hass.services.has_service(DOMAIN, "announce")


async def test_default_target_uses_intuitive_device_and_entity_names(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="UniFi Announcer",
        data=BASE_DATA,
        unique_id=BASE_DATA["url"],
    )
    entry.add_to_hass(hass)

    with (
        patch.object(UniFiAnnouncerClient, "async_check_auth", AsyncMock(return_value=None)),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_version",
            AsyncMock(return_value={"version": "2.1.2", "service": "unifi-announcer"}),
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
                }],
                "groups": {},
            }),
        ),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_presets",
            AsyncMock(return_value=[{"name": "package-delivered"}]),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    service_device = device_registry.async_get_device(
        identifiers={(DOMAIN, BASE_DATA["url"])}
    )
    chime_device = device_registry.async_get_device(
        identifiers={(DOMAIN, "chime-1")}
    )
    assert service_device.name == "UniFi Announcer Service"
    assert chime_device.name == "Protect Smart Chime"

    registry = er.async_get(hass)
    names_by_unique_id = {
        item.unique_id: item.original_name
        for item in registry.entities.values()
        if item.config_entry_id == entry.entry_id and "chime-1" in item.unique_id
    }
    prefix = f"{entry.entry_id}_chime-1"
    assert names_by_unique_id[f"{prefix}_buzzer"] == "Play buzzer"
    assert names_by_unique_id[f"{prefix}_default"] == "Play default ringtone"
    assert names_by_unique_id[f"{prefix}_preset"] == "Play selected preset"
    assert names_by_unique_id[f"{prefix}_preset_select"] == "Ringtone preset"
    assert names_by_unique_id[f"{prefix}_queue_depth"] == "Queue depth"
    assert names_by_unique_id[f"{prefix}_last_disposition"] == "Last playback result"


async def test_existing_generated_device_names_are_migrated(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="UniFi Announcer",
        data=BASE_DATA,
        unique_id=BASE_DATA["url"],
    )
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, BASE_DATA["url"])},
        name="UniFi Announcer",
    )
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "chime-1")},
        name="default",
    )

    with (
        patch.object(UniFiAnnouncerClient, "async_check_auth", AsyncMock(return_value=None)),
        patch.object(
            UniFiAnnouncerClient,
            "async_get_version",
            AsyncMock(return_value={"version": "2.1.2", "service": "unifi-announcer"}),
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
            AsyncMock(return_value=[]),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert registry.async_get_device(
        identifiers={(DOMAIN, BASE_DATA["url"])}
    ).name == "UniFi Announcer Service"
    assert registry.async_get_device(
        identifiers={(DOMAIN, "chime-1")}
    ).name == "Protect Smart Chime"
