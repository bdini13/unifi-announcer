from contextlib import asynccontextmanager
from http.cookiejar import Cookie
from types import SimpleNamespace
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
async def test_mutating_routes_fail_closed_when_api_key_is_empty(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "")
    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.post("/announce", json={"text": "Hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "APP_API_KEY is not configured"


@pytest.mark.asyncio
async def test_placeholder_api_key_fails_closed(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "REPLACE_ME")
    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.post(
            "/announce",
            headers={"X-API-Key": "REPLACE_ME"},
            json={"text": "Hello"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "APP_API_KEY is not configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/chime", "/chime/settings", "/chime/direct-info", "/events/recent"],
)
async def test_sensitive_get_diagnostics_require_api_key(main_module, monkeypatch, path):
    monkeypatch.setattr(main_module, "APP_API_KEY", "configured-test-key")
    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.get(path)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_announce_cache_hit_uses_resolved_defaults(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "configured-test-key")
    find = AsyncMock(return_value={"id": "ringtone-1", "name": "hello"})
    play = AsyncMock(return_value={"played": True})
    monkeypatch.setattr(main_module.protect, "find_ringtone_by_name", find)
    monkeypatch.setattr(main_module.protect, "play", play)

    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.post(
            "/announce",
            headers={"X-API-Key": "configured-test-key"},
            json={"text": "Hello"},
        )

    assert response.status_code == 200
    play.assert_awaited_once_with("ringtone-1", main_module.VOLUME_DEFAULT,
                                  main_module.REPEAT_DEFAULT,
                                  chime_id="chime-fixture")


@pytest.mark.asyncio
async def test_announce_cache_miss_uploads_and_preserves_zero_volume(
    main_module, monkeypatch
):
    monkeypatch.setattr(main_module, "APP_API_KEY", "configured-test-key")
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
            "/announce",
            headers={"X-API-Key": "configured-test-key"},
            json={"text": "Quiet", "volume": 0, "repeat_times": 2},
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


@pytest.mark.asyncio
async def test_target_catalog_requires_api_key(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "configured-test-key")
    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        denied = await client.get("/targets")
        allowed = await client.get(
            "/targets", headers={"X-API-Key": "configured-test-key"}
        )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["schema_version"] == 1


@pytest.mark.asyncio
async def test_talkback_cookie_header_sends_only_one_scoped_token(
    main_module, monkeypatch
):
    monkeypatch.setattr(main_module, "UNIFI_HOST", "https://unifi.invalid")
    cookies = httpx.Cookies()
    cookies.set("TOKEN", "scoped-token", domain="unifi.invalid", path="/")
    cookies.set("OTHER", "must-not-leak", domain="unifi.invalid", path="/")
    cookies.set("TOKEN", "wrong-domain", domain="other.invalid", path="/")
    client = main_module.ProtectClient()
    client._logged_in = True
    client._client_instance = SimpleNamespace(cookies=cookies)

    assert await client.session_cookie_header() == "TOKEN=scoped-token"


@pytest.mark.asyncio
async def test_talkback_cookie_header_rejects_ambiguous_or_unscoped_auth(
    main_module, monkeypatch
):
    monkeypatch.setattr(main_module, "UNIFI_HOST", "https://unifi.invalid")
    cookies = httpx.Cookies()
    cookies.set("TOKEN", "domainless-supercookie")
    client = main_module.ProtectClient()
    client._logged_in = True
    client._client_instance = SimpleNamespace(cookies=cookies)

    with pytest.raises(RuntimeError, match="authentication cookie is unavailable"):
        await client.session_cookie_header()

    path_mismatch = httpx.Cookies()
    path_mismatch.set(
        "TOKEN", "wrong-path", domain="unifi.invalid", path="/api-only"
    )
    client._client_instance = SimpleNamespace(cookies=path_mismatch)
    with pytest.raises(RuntimeError, match="authentication cookie is unavailable"):
        await client.session_cookie_header()

    expired = httpx.Cookies()
    expired.jar.set_cookie(Cookie(
        version=0,
        name="TOKEN",
        value="expired-token",
        port=None,
        port_specified=False,
        domain="unifi.invalid",
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=True,
        expires=1,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    ))
    client._client_instance = SimpleNamespace(cookies=expired)
    with pytest.raises(RuntimeError, match="authentication cookie is unavailable"):
        await client.session_cookie_header()


@pytest.mark.asyncio
async def test_reboot_invalidates_resident_content_before_device_reboot(
    main_module, monkeypatch
):
    monkeypatch.setattr(main_module, "APP_API_KEY", "configured-test-key")
    order = []

    class DynamicSlotsFixture:
        @asynccontextmanager
        async def target_lifecycle_guard(self, target_ids, *, reason):
            order.append(("guard-enter", list(target_ids), reason))
            yield 2
            order.append(("guard-exit",))

    async def reboot_device():
        order.append(("reboot",))
        return {"rebooting": True, "state": "CONNECTED"}

    monkeypatch.setattr(
        main_module.app.state.services,
        "dynamic_slots",
        DynamicSlotsFixture(),
        raising=False,
    )
    monkeypatch.setattr(main_module.protect, "reboot", reboot_device)

    async with httpx.AsyncClient(
        transport=transport_for(main_module), base_url="http://test"
    ) as client:
        response = await client.post(
            "/reboot?confirm=true",
            headers={"X-API-Key": "configured-test-key"},
        )

    assert response.status_code == 200
    assert order == [
        ("guard-enter", ["chime-fixture"], "device_reboot"),
        ("reboot",),
        ("guard-exit",),
    ]
