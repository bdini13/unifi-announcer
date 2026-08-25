from unittest.mock import AsyncMock

import httpx
import pytest

from app.health import BackgroundHealth


@pytest.mark.asyncio
async def test_health_snapshot_never_runs_slow_checks():
    protect_check = AsyncMock(return_value=2)
    local_state = lambda: {
        "event_stream": ("ok", "connected"),
        "direct_device": ("degraded", "nvr_fallback"),
        "mqtt": ("disabled", "not_configured"),
    }
    health = BackgroundHealth(protect_check=protect_check, local_state=local_state)

    initial = health.snapshot()
    protect_check.assert_not_awaited()
    assert set(initial["components"]) == {
        "protect",
        "event_stream",
        "direct_device",
        "mqtt",
        "chimes",
    }

    await health.refresh()
    protect_check.assert_awaited_once()
    snapshot = health.snapshot()
    protect_check.assert_awaited_once()
    assert snapshot["components"]["protect"]["status"] == "ok"
    assert snapshot["components"]["chimes"]["detail"] == "2 discovered"
    assert snapshot["components"]["direct_device"] == {
        "status": "degraded",
        "detail": "nvr_fallback",
    }
    assert snapshot["status"] == "degraded"


@pytest.mark.asyncio
async def test_background_health_contains_protect_failures():
    health = BackgroundHealth(
        protect_check=AsyncMock(side_effect=RuntimeError("offline secret=value")),
        local_state=lambda: {},
    )

    await health.refresh()

    component = health.snapshot()["components"]["protect"]
    assert component == {"status": "error", "detail": "RuntimeError"}
    assert "secret" not in str(component)


@pytest.mark.asyncio
async def test_health_and_version_routes_are_read_only_snapshots(main_module, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc123fixture")
    slow_check = AsyncMock(side_effect=AssertionError("request path ran external check"))
    monkeypatch.setattr(main_module.app.state.services.health, "_protect_check", slow_check)
    main_module.app.state.services.health.set_component("protect", "ok", "background")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        health = await client.get("/health")
        version = await client.get("/version")

    assert health.status_code == 200
    slow_check.assert_not_awaited()
    assert health.json()["components"]["protect"]["status"] == "ok"
    assert version.json() == {
        "service": "unifi-announcer",
        "git_sha": "abc123fixture",
        "tested_firmware": {
            "protect": ["7.2.105"],
            "smart_chime": ["1.7.20"],
        },
        "protocols": {
            "protect_rest": "production_private_api",
            "event_stream": "experimental",
            "direct_device_http": "experimental_read_only_and_staging",
            "direct_ucp4": "research_disconnected",
            "mqtt": "optional",
        },
    }
