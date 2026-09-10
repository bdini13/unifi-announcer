from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.unifi_announcer.api import CannotConnect
from custom_components.unifi_announcer.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.mark.asyncio
async def test_camera_diagnostics_are_sanitized_and_include_backend_support():
    coordinator = SimpleNamespace(data={
        "health": {"status": "ok"},
        "chimes": {
            "chimes": [],
            "cameras": [{
                "name": "family_camera",
                "id": "private-camera-id",
                "queue_depth": 1,
                "capability_state": {
                    "status": "available",
                    "model": "UVC G3 Instant",
                    "signed_url": "wss://controller/ws/talkback?token=secret",
                },
                "capabilities": {"announce": True, "buzzer": False},
            }],
            "groups": {"mixed": ["family_camera"]},
            "group_capabilities": {
                "mixed": {"announce": True, "buzzer": False}
            },
        },
        "presets": [],
    })
    backend_support = {
        "schema_version": 1,
        "redaction": {"device_identifiers": "omitted"},
        "targets": [{"target": "target_1", "type": "camera"}],
    }
    client = SimpleNamespace(
        async_get_support_bundle=AsyncMock(return_value=backend_support)
    )
    runtime = SimpleNamespace(
        coordinator=coordinator,
        version={"version": "fixture"},
        client=client,
    )
    entry = SimpleNamespace(
        runtime_data=runtime,
        data={"url": "http://announcer.test", "api_key": "secret"},
        options={},
    )

    result = await async_get_config_entry_diagnostics(None, entry)

    assert result["backend_support"] == backend_support
    client.async_get_support_bundle.assert_awaited_once_with()
    assert result["cameras"] == [{
        "name": "family_camera",
        "model": "UVC G3 Instant",
        "queue_depth": 1,
        "status": "available",
        "capabilities": {"announce": True, "buzzer": False},
    }]
    assert "private-camera-id" not in str(result)
    assert "signed_url" not in str(result)
    assert "token=secret" not in str(result)
    assert result["config_entry"]["api_key"] == "**REDACTED**"


@pytest.mark.asyncio
async def test_backend_diagnostics_failure_does_not_copy_exception_text():
    coordinator = SimpleNamespace(data={"health": {}, "chimes": {}, "presets": []})
    client = SimpleNamespace(
        async_get_support_bundle=AsyncMock(
            side_effect=CannotConnect("failed to connect to 192.168.10.55 secret-host")
        )
    )
    runtime = SimpleNamespace(coordinator=coordinator, version={}, client=client)
    entry = SimpleNamespace(
        runtime_data=runtime,
        data={"url": "http://announcer.test", "api_key": "secret"},
        options={},
    )

    result = await async_get_config_entry_diagnostics(None, entry)

    assert result["backend_support"] == {
        "available": False,
        "error_type": "CannotConnect",
    }
    assert "192.168.10.55" not in str(result)
    assert "secret-host" not in str(result)
