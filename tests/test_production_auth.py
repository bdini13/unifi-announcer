import httpx
import pytest


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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.get(
            path, headers={"X-API-Key": "configured-test-key"}
        )

    assert response.status_code != 403


def test_backup_permissions_are_applied_by_root_container():
    from pathlib import Path

    readme = Path("README.md").read_text()
    rollback = readme.split("## Roll back", 1)[1].split("## Troubleshooting", 1)[0]
    assert 'BACKUP_UID="$(id -u)"' in rollback
    assert 'chown "$BACKUP_UID:$BACKUP_GID" "$file"' in rollback
    assert 'chmod 600 "$file"' in rollback
    assert 'chmod 600 "backups/data-$STAMP.tgz"' not in rollback
