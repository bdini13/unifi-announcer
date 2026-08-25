"""Setup and entity regression tests for UniFi Announcer."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_announcer import async_setup_entry
from custom_components.unifi_announcer.api import (
    AuthenticationError,
    CannotConnect,
    CommandResult,
    UniFiAnnouncerClient,
)
from custom_components.unifi_announcer.const import DOMAIN


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
                "groups": {"whole_house": ["kitchen"]},
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

        await hass.services.async_call(
            DOMAIN,
            "announce",
            {"message": "Test announcement"},
            blocking=True,
        )
        announce_mock.assert_awaited()
        _, kwargs = announce_mock.await_args
        assert kwargs["target"] == "kitchen"
        assert kwargs["volume"] == 0
        assert kwargs["repeat_times"] == 2

        assert hass.services.has_service(DOMAIN, "announce")
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not hass.services.has_service(DOMAIN, "announce")
