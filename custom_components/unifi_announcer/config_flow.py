"""UI configuration flow for UniFi Announcer."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, CannotConnect, InvalidResponse, UniFiAnnouncerClient, normalize_base_url
from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_REPEAT,
    CONF_DEFAULT_TARGET,
    CONF_DEFAULT_VOLUME,
    CONF_INSTANCE_NAME,
    CONF_POLL_INTERVAL,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

STEP_SCHEMA = vol.Schema({
    vol.Required(CONF_URL): str,
    vol.Optional(CONF_API_KEY, default=""): str,
    vol.Optional(CONF_VERIFY_SSL, default=False): bool,
    vol.Optional(CONF_INSTANCE_NAME, default="UniFi Announcer"): str,
})


async def _validate(hass, data: dict) -> tuple[str, dict]:
    url = normalize_base_url(data[CONF_URL])
    session = async_get_clientsession(hass, verify_ssl=bool(data.get(CONF_VERIFY_SSL, False)))
    client = UniFiAnnouncerClient(session, url, data.get(CONF_API_KEY, ""))
    await client.async_get_health()
    version = await client.async_get_version()
    await client.async_check_auth()
    return url, version


class UniFiAnnouncerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a UniFi Announcer service instance."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                url, version = await _validate(self.hass, user_input)
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                data = {**user_input, CONF_URL: url}
                title = user_input.get(CONF_INSTANCE_NAME) or version.get("service") or "UniFi Announcer"
                return self.async_create_entry(title=title, data=data)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except (InvalidResponse, ValueError):
                errors["base"] = "invalid_response"
        return self.async_show_form(step_id="user", data_schema=STEP_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            data = {**self._reauth_entry.data, CONF_API_KEY: user_input.get(CONF_API_KEY, "")}
            try:
                await _validate(self.hass, data)
                return self.async_update_reload_and_abort(self._reauth_entry, data_updates=data)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except (InvalidResponse, ValueError):
                errors["base"] = "invalid_response"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return UniFiAnnouncerOptionsFlow(config_entry)


class UniFiAnnouncerOptionsFlow(config_entries.OptionsFlow):
    """Runtime tuning options; credentials remain in config-entry data."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        defaults = self.config_entry.options
        schema = vol.Schema({
            vol.Optional(CONF_POLL_INTERVAL, default=defaults.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)): vol.All(int, vol.Range(min=10, max=600)),
            vol.Optional(CONF_DEFAULT_TARGET, default=defaults.get(CONF_DEFAULT_TARGET, "")): str,
            vol.Optional(CONF_DEFAULT_VOLUME, default=defaults.get(CONF_DEFAULT_VOLUME, 50)): vol.All(int, vol.Range(min=0, max=100)),
            vol.Optional(CONF_DEFAULT_REPEAT, default=defaults.get(CONF_DEFAULT_REPEAT, 1)): vol.All(int, vol.Range(min=1, max=6)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
