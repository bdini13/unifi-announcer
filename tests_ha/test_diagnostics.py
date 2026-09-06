from types import SimpleNamespace

import pytest

from custom_components.unifi_announcer.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.mark.asyncio
async def test_camera_diagnostics_are_sanitized():
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
    runtime = SimpleNamespace(
        coordinator=coordinator,
        version={"version": "fixture"},
    )
    entry = SimpleNamespace(
        runtime_data=runtime,
        data={"url": "http://announcer.test", "api_key": "secret"},
        options={},
    )

    result = await async_get_config_entry_diagnostics(None, entry)

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
