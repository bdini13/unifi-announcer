"""Global service routing must not cross configured Announcer instances."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_announcer import _async_register_services
from custom_components.unifi_announcer.api import CannotConnect, CommandResult, UniFiAnnouncerClient
from custom_components.unifi_announcer.const import DOMAIN


@pytest.fixture
def offline_clients():
    """Exercise real HA setup/unload without contacting either backend."""
    with (
        patch.object(UniFiAnnouncerClient, "async_check_auth", AsyncMock()),
        patch.object(
            UniFiAnnouncerClient, "async_get_version",
            AsyncMock(return_value={"version": "test", "service": DOMAIN}),
        ),
        patch.object(
            UniFiAnnouncerClient, "async_get_health",
            AsyncMock(return_value={"status": "ok"}),
        ),
        patch.object(
            UniFiAnnouncerClient, "async_get_chimes",
            AsyncMock(return_value={"chimes": [], "groups": {}}),
        ),
        patch.object(UniFiAnnouncerClient, "async_get_presets", AsyncMock(return_value=[])),
        patch.object(UniFiAnnouncerClient, "async_announce", playback_mock()),
    ):
        yield


def add_entry(hass, name):
    """Register an instance with its own backend identity."""
    url = f"http://{name}.invalid:8095"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=name,
        unique_id=url,
        data={"url": url, "api_key": "test-key", "instance_name": name},
        options={"default_target": f"{name}-target"},
    )
    entry.add_to_hass(hass)
    return entry


def playback_mock():
    return AsyncMock(return_value=CommandResult("played", {"disposition": "played"}, 200))


async def test_multiple_instances_route_explicitly_and_keep_service_until_last_unload(
    hass, offline_clients,
):
    first = add_entry(hass, "first")
    second = add_entry(hass, "second")
    # Initial component setup also loads its other registered entries.
    assert await hass.config_entries.async_setup(first.entry_id)
    await hass.async_block_till_done()
    assert second.state is ConfigEntryState.LOADED
    first.runtime_data.client.async_announce = first_call = playback_mock()
    second.runtime_data.client.async_announce = second_call = playback_mock()

    with pytest.raises(HomeAssistantError, match="specify config_entry_id"):
        await hass.services.async_call(
            DOMAIN, "announce", {"message": "Ambiguous destination"}, blocking=True
        )
    with pytest.raises(HomeAssistantError, match="not configured"):
        await hass.services.async_call(
            DOMAIN, "announce",
            {"message": "Unknown destination", "config_entry_id": "missing"},
            blocking=True,
        )
    first_call.assert_not_awaited()
    second_call.assert_not_awaited()

    await hass.services.async_call(
        DOMAIN, "announce",
        {"message": "Selected second", "config_entry_id": second.entry_id},
        blocking=True,
    )
    first_call.assert_not_awaited()
    assert second_call.await_count == 1
    assert second_call.await_args.kwargs["target"] == "second-target"

    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "announce")
    with pytest.raises(HomeAssistantError, match="not loaded"):
        await hass.services.async_call(
            DOMAIN, "announce",
            {"message": "Unavailable first", "config_entry_id": first.entry_id},
            blocking=True,
        )
    await hass.services.async_call(
        DOMAIN, "announce",
        {"message": "Second still works", "config_entry_id": second.entry_id},
        blocking=True,
    )
    assert second_call.await_count == 2

    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "announce")


async def test_unloaded_first_instance_cannot_redirect_to_other_backend(hass, offline_clients):
    first = add_entry(hass, "first")
    second = add_entry(hass, "second")

    async def check_auth(client):
        if client.base_url == first.data["url"]:
            raise CannotConnect("First backend offline")

    with patch.object(UniFiAnnouncerClient, "async_check_auth", check_auth):
        assert await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()
    assert first.state is ConfigEntryState.SETUP_RETRY
    second.runtime_data.client.async_announce = second_call = playback_mock()

    with pytest.raises(HomeAssistantError, match="specify config_entry_id"):
        await hass.services.async_call(
            DOMAIN, "announce", {"message": "Do not change destination"}, blocking=True
        )
    with pytest.raises(HomeAssistantError, match="not loaded"):
        await hass.services.async_call(
            DOMAIN, "announce",
            {"message": "Unavailable first", "config_entry_id": first.entry_id},
            blocking=True,
        )
    second_call.assert_not_awaited()
    assert await hass.config_entries.async_unload(second.entry_id)


@pytest.mark.parametrize("explicit_entry", [False, True])
async def test_single_unloaded_instance_reports_unavailable(hass, explicit_entry):
    entry = add_entry(hass, "unloaded")
    _async_register_services(hass)
    data = {"message": "Unavailable"}
    if explicit_entry:
        data["config_entry_id"] = entry.entry_id
    with pytest.raises(HomeAssistantError, match="not loaded"):
        await hass.services.async_call(DOMAIN, "announce", data, blocking=True)


async def test_failed_platform_unload_keeps_service(hass, offline_clients):
    entry = add_entry(hass, "first")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    with patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)):
        assert not await hass.config_entries.async_unload(entry.entry_id)
    assert hass.services.has_service(DOMAIN, "announce")
