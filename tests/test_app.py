from unittest.mock import AsyncMock

import httpx
import pytest


def transport_for(module):
    return httpx.ASGITransport(app=module.app)


def test_application_imports(main_module):
    assert main_module.app.title == "UniFi Announcer"


@pytest.mark.asyncio
async def test_health_is_local_and_public(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "configured-test-key")
    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_announce_cache_hit_uses_resolved_defaults(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "")
    find = AsyncMock(return_value={"id": "ringtone-1", "name": "hello"})
    play = AsyncMock(return_value={"played": True})
    monkeypatch.setattr(main_module.protect, "find_ringtone_by_name", find)
    monkeypatch.setattr(main_module.protect, "play", play)

    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.post("/announce", json={"text": "Hello"})

    assert response.status_code == 200
    play.assert_awaited_once_with("ringtone-1", main_module.VOLUME_DEFAULT,
                                  main_module.REPEAT_DEFAULT,
                                  chime_id="chime-fixture")


@pytest.mark.asyncio
async def test_announce_cache_miss_uploads_and_preserves_zero_volume(
    main_module, monkeypatch
):
    monkeypatch.setattr(main_module, "APP_API_KEY", "")
    monkeypatch.setattr(main_module.protect, "find_ringtone_by_name",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(main_module.protect, "list_ringtones",
                        AsyncMock(return_value=[]))
    monkeypatch.setattr(main_module, "synthesize_tts_cached",
                        AsyncMock(return_value=b"sanitized-mp3-fixture"))
    upload = AsyncMock(return_value={"uploaded": True, "via": "nvr"})
    monkeypatch.setattr(main_module.chime_client, "upload_ringtone", upload)
    monkeypatch.setattr(main_module.ringtone_index, "resolve_or_refresh",
                        AsyncMock(return_value={"id": "ringtone-2", "name": "quiet"}))
    play = AsyncMock(return_value={"played": True})
    monkeypatch.setattr(main_module.protect, "play", play)

    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.post(
            "/announce", json={"text": "Quiet", "volume": 0, "repeat_times": 2}
        )

    assert response.status_code == 200
    upload.assert_awaited_once()
    assert upload.await_args.args[1] == b"sanitized-mp3-fixture"
    play.assert_awaited_once_with("ringtone-2", 0, 2,
                                  chime_id="chime-fixture")


def test_track_registry_persists_json(main_module, tmp_path):
    registry = main_module.TrackRegistry()
    path = tmp_path / "track_registry.json"
    registry._path = str(path)
    registry.put(main_module.TrackRecord("fixture-tone", "preset"))

    saved = path.read_text()
    assert '"fixture-tone"' in saved


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/announce"),
        ("POST", "/buzzer"),
        ("POST", "/play-default"),
        ("PUT", "/presets/fixture-tone"),
        ("PATCH", "/chime/settings"),
        ("POST", "/reboot?confirm=false"),
    ],
)
async def test_api_key_is_required_on_mutating_routes(
    main_module, monkeypatch, method, path
):
    monkeypatch.setattr(main_module, "APP_API_KEY", "configured-test-key")
    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json={})

    assert response.status_code == 403
