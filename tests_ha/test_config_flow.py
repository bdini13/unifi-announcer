"""Config-flow regression tests for UniFi Announcer."""
from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.unifi_announcer.const import DOMAIN


async def test_user_flow_creates_entry(hass):
    with patch(
        "custom_components.unifi_announcer.config_flow._validate",
        AsyncMock(return_value=("http://announcer.local:8095", {"service": "unifi-announcer"})),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "url": "http://announcer.local:8095/",
                "api_key": "test-key",
                "verify_ssl": False,
                "instance_name": "House Announcer",
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "House Announcer"
    assert result["data"]["url"] == "http://announcer.local:8095"


async def test_user_flow_requires_api_key(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    schema_keys = {key.schema: key for key in result["data_schema"].schema}
    assert schema_keys["api_key"].__class__.__name__ == "Required"


async def test_options_flow_uses_framework_config_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"url": "http://announcer.local:8095", "api_key": "", "verify_ssl": False},
        options={"poll_interval": 30, "default_volume": 50, "default_repeat": 1},
        unique_id="http://announcer.local:8095",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "poll_interval": 45,
            "default_target": "kitchen",
            "default_volume": 0,
            "default_repeat": 2,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["poll_interval"] == 45
    assert entry.options["default_volume"] == 0
    assert entry.options["default_repeat"] == 2


async def test_reauth_updates_key_without_explicit_double_reload(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"url": "http://announcer.local:8095", "api_key": "old", "verify_ssl": False},
        unique_id="http://announcer.local:8095",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.unifi_announcer.config_flow._validate",
        AsyncMock(return_value=("http://announcer.local:8095", {"service": "unifi-announcer"})),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reauth", "entry_id": entry.entry_id, "unique_id": entry.unique_id},
            data=entry.data,
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "new-key"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert entry.data["api_key"] == "new-key"
