import httpx
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/presets", "/tts/slots/status", "/tts/cache/status"],
)
async def test_production_outer_diagnostics_require_api_key(monkeypatch, path):
    from app import server

    monkeypatch.setattr(server.core, "APP_API_KEY", "configured-test-key")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get(path)

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/presets", "/tts/slots/status", "/tts/cache/status"],
)
async def test_production_outer_diagnostics_accept_api_key(monkeypatch, path):
    from app import server

    monkeypatch.setattr(server.core, "APP_API_KEY", "configured-test-key")
    monkeypatch.setattr(
        server.core.protect_backends.ringtone,
        "list_ringtones",
        AsyncMock(return_value=[]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get(
            path, headers={"X-API-Key": "configured-test-key"}
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_public_health_exposes_only_coarse_readiness(monkeypatch):
    from app import server

    monkeypatch.setattr(server.core, "APP_API_KEY", "configured-test-key")
    monkeypatch.setattr(
        server.dynamic_slots,
        "status",
        lambda: {
            "ready": False,
            "mode": "two_slot_overwrite",
            "slot_count": 2,
            "installation_id": "secret-installation-id",
            "bindings": {"secret-chime-id": "secret-ringtone-id"},
            "binding_diagnostics": {"filename": "/data/private.json"},
            "last_error": "sensitive detail",
        },
    )
    monkeypatch.setattr(
        server.tts_cache,
        "stats",
        lambda: {"files": 3, "bytes": 99, "cache_dir": "/data/cache/private"},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    health = response.json()
    assert health["dynamic_tts"] == {
        "ready": False,
        "mode": "two_slot_overwrite",
        "slot_count": 2,
    }
    assert health["tts_cache"] == {"ready": True}
    serialized = response.text
    for secret in (
        "secret-installation-id",
        "secret-chime-id",
        "secret-ringtone-id",
        "/data/private.json",
        "sensitive detail",
        "/data/cache/private",
    ):
        assert secret not in serialized


def test_backup_permissions_are_applied_by_root_container():
    from pathlib import Path

    readme = Path("README.md").read_text()
    rollback = readme.split("## Roll back", 1)[1].split("## Troubleshooting", 1)[0]
    assert 'BACKUP_UID="$(id -u)"' in rollback
    assert 'chown "$BACKUP_UID:$BACKUP_GID" "$file"' in rollback
    assert 'chmod 600 "$file"' in rollback
    assert 'chmod 600 "backups/data-$STAMP.tgz"' not in rollback
