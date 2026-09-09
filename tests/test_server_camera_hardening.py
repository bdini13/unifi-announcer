import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.playback.camera_hardening import CameraProtocolProfile


def test_production_composition_loads_exact_experimental_profiles(
    main_module, monkeypatch
):
    monkeypatch.setenv("GROUPS_CONFIG", "{}")
    monkeypatch.setenv(
        "EXPERIMENTAL_CAMERA_PROFILES",
        '[{"codec":"aac","transport":"serverudp","sample_rate":22050,'
        '"channels":1,"bits_per_sample":16}]',
    )
    sys.modules.pop("app.server", None)

    server = importlib.import_module("app.server")

    assert server.core.camera_talkback.experimental_profiles == frozenset({
        CameraProtocolProfile(
            codec="aac",
            transport="serverudp",
            sample_rate=22050,
            channels=1,
            bits_per_sample=16,
        )
    })


@pytest.mark.asyncio
async def test_production_target_catalog_refreshes_camera_availability(
    main_module, monkeypatch
):
    monkeypatch.setenv("GROUPS_CONFIG", "{}")
    sys.modules.pop("app.server", None)
    server = importlib.import_module("app.server")

    runtime = SimpleNamespace(
        desc=SimpleNamespace(
            name="family_camera",
            kind="camera",
            camera_id="camera-one",
            device_id="camera-one",
        ),
        capability_state={"status": "unavailable"},
        queue=SimpleNamespace(depth=0),
    )
    monkeypatch.setattr(server.core, "camera_runtimes", {"family_camera": runtime})
    monkeypatch.setattr(server.core, "target_runtimes", {"family_camera": runtime})
    monkeypatch.setattr(server.core, "GROUPS", {})

    inspect = AsyncMock(
        side_effect=[
            {"status": "unavailable", "model": "UVC G3 Instant"},
            {
                "status": "available",
                "model": "UVC G3 Instant",
                "compatibility": "physically_validated",
            },
        ]
    )
    monkeypatch.setattr(
        server.core,
        "camera_talkback",
        SimpleNamespace(inspect=inspect),
    )

    await server._refresh_camera_capabilities()
    first = server._target_catalog_payload()["targets"][0]
    assert first["status"] == "unavailable"
    assert first["capabilities"]["announce"] is False

    await server._refresh_camera_capabilities()
    second = server._target_catalog_payload()["targets"][0]
    assert second["status"] == "available"
    assert second["capabilities"]["announce"] is True
    assert second["compatibility"] == "physically_validated"
    assert inspect.await_count == 2
