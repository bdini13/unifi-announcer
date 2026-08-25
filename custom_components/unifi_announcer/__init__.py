"""Home Assistant integration for UniFi Announcer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, CannotConnect, PlaybackFailed, UniFiAnnouncerClient
from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_REPEAT,
    CONF_DEFAULT_TARGET,
    CONF_DEFAULT_VOLUME,
    CONF_POLL_INTERVAL,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .coordinator import UniFiAnnouncerCoordinator

PLATFORMS = [Platform.NOTIFY, Platform.BUTTON, Platform.SELECT, Platform.SENSOR, Platform.MEDIA_PLAYER]


@dataclass
class UniFiAnnouncerRuntime:
    client: UniFiAnnouncerClient
    coordinator: UniFiAnnouncerCoordinator
    version: dict[str, Any]
    preset_selection: dict[str, str] = field(default_factory=dict)
    last_disposition: dict[str, str] = field(default_factory=dict)


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    session = async_get_clientsession(hass, verify_ssl=bool(entry.data.get(CONF_VERIFY_SSL, False)))
    client = UniFiAnnouncerClient(
        session,
        entry.data[CONF_URL],
        entry.data.get(CONF_API_KEY, ""),
    )
    try:
        await client.async_check_auth()
        version = await client.async_get_version()
    except AuthenticationError as exc:
        raise ConfigEntryAuthFailed("UniFi Announcer rejected the configured API key") from exc
    except CannotConnect as exc:
        raise ConfigEntryNotReady("Cannot connect to UniFi Announcer") from exc

    coordinator = UniFiAnnouncerCoordinator(
        hass,
        client,
        int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = UniFiAnnouncerRuntime(client, coordinator, version)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and hass.services.has_service(DOMAIN, "announce"):
        hass.services.async_remove(DOMAIN, "announce")
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "announce"):
        return

    schema = vol.Schema({
        vol.Required("message"): cv.string,
        vol.Optional("target"): cv.string,
        vol.Optional("volume"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("repeat_times"): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
        vol.Optional("profile"): cv.string,
        vol.Optional("priority", default=50): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("dedupe_key"): cv.string,
    })

    async def _announce(call: ServiceCall) -> None:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise HomeAssistantError("No UniFi Announcer instance is configured")
        entry = entries[0]
        runtime: UniFiAnnouncerRuntime = entry.runtime_data
        target = call.data.get("target") or entry.options.get(CONF_DEFAULT_TARGET) or None
        kwargs = {
            "target": target,
            "volume": call.data.get("volume", entry.options.get(CONF_DEFAULT_VOLUME)),
            "repeat_times": call.data.get("repeat_times", entry.options.get(CONF_DEFAULT_REPEAT)),
            "profile": call.data.get("profile"),
            "priority": call.data.get("priority", 50),
            "dedupe_key": call.data.get("dedupe_key"),
        }
        try:
            result = await runtime.client.async_announce(call.data["message"], **kwargs)
        except PlaybackFailed as exc:
            raise HomeAssistantError(str(exc)) from exc
        runtime.last_disposition[target or "default"] = result.disposition

    hass.services.async_register(DOMAIN, "announce", _announce, schema=schema)
