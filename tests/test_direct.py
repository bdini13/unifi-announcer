import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.playback.arbitration import ChimeDescriptor, ChimeRuntime


def test_runtime_registry_binds_each_direct_client_to_its_chime_id(
    main_module, monkeypatch
):
    monkeypatch.setattr(main_module, "CHIME_ID", "")
    monkeypatch.setenv("CHIMES_CONFIG", json.dumps([
        {"name": "one", "id": "id-one"},
        {"name": "two", "id": "id-two"},
    ]))

    runtimes = main_module._load_chime_runtimes()

    assert runtimes["one"].direct_client._chime_id == "id-one"
    assert runtimes["two"].direct_client._chime_id == "id-two"


@pytest.mark.asyncio
async def test_direct_info_failure_uses_mocked_nvr_fallback(main_module, monkeypatch):
    direct = AsyncMock(side_effect=RuntimeError("fixture failure"))
    fallback = AsyncMock(
        return_value={"name": "Fixture", "state": "CONNECTED", "firmwareVersion": "1.7.20"}
    )
    monkeypatch.setattr(main_module.chime_client.direct, "info_wrapped", direct)
    monkeypatch.setattr(main_module.protect, "get_chime", fallback)

    result = await main_module.chime_client.info()

    assert result == {
        "via": "nvr",
        "info": {"name": "Fixture", "state": "CONNECTED", "firmware": "1.7.20"},
    }
    direct.assert_awaited_once()
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_per_chime_direct_ip_discovery_never_reuses_default_ip(
    main_module, monkeypatch
):
    monkeypatch.setattr(main_module, "CHIME_ID", "id-default")
    monkeypatch.setattr(main_module, "CHIME_DIRECT_IP", "192.0.2.10")
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"host": "192.0.2.22"},
    )
    request = AsyncMock(return_value=response)
    monkeypatch.setattr(main_module.protect, "_do", request)
    client = main_module.DirectChimeClient(chime_id="id-two")
    client._credential_provider = SimpleNamespace()

    await client._ensure_ready()

    assert client._base == "https://192.0.2.22:8080"
    request.assert_awaited_once_with(
        "GET", "/proxy/protect/api/chimes/id-two")


@pytest.mark.asyncio
async def test_runtime_capability_probes_are_isolated_per_chime():
    good_caps = type("Caps", (), {"to_dict": lambda self: {
        "firmware": "v1.7.20", "direct_upload_allowed": True}})()
    good = SimpleNamespace(
        capabilities=good_caps,
        info=AsyncMock(return_value={"version": "v1.7.20"}),
    )
    bad = SimpleNamespace(
        capabilities=None,
        info=AsyncMock(side_effect=RuntimeError("credential=must-not-leak")),
    )
    one = ChimeRuntime(ChimeDescriptor("one", "id-one", "192.0.2.1"),
                       direct_client=good)
    two = ChimeRuntime(ChimeDescriptor("two", "id-two", "192.0.2.2"),
                       direct_client=bad)

    one.start()
    two.start()
    await asyncio.gather(one.probe_task, two.probe_task)

    assert one.capability_state == {
        "status": "available", "firmware": "v1.7.20",
        "direct_upload_allowed": True,
    }
    assert two.capability_state == {
        "status": "unavailable", "error_type": "RuntimeError",
    }
    assert "must-not-leak" not in str(two.capability_state)


@pytest.mark.asyncio
async def test_capabilities_endpoint_reports_sanitized_per_chime_state(main_module, monkeypatch):
    runtimes = {
        "one": SimpleNamespace(
            desc=SimpleNamespace(chime_id="id-one", direct_ip="192.0.2.1"),
            direct_client=SimpleNamespace(),
            capability_state={"status": "available", "firmware": "v1.7.20"},
        ),
        "two": SimpleNamespace(
            desc=SimpleNamespace(chime_id="id-two", direct_ip="192.0.2.2"),
            direct_client=SimpleNamespace(),
            capability_state={"status": "unavailable", "error_type": "RuntimeError"},
        ),
    }
    monkeypatch.setattr(main_module, "chime_runtimes", runtimes)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.get("/chime/capabilities")

    assert response.status_code == 200
    assert response.json()["chimes"] == [
        {"name": "one", "direct_configured": True,
         "capabilities": {"status": "available", "firmware": "v1.7.20"}},
        {"name": "two", "direct_configured": True,
         "capabilities": {"status": "unavailable", "error_type": "RuntimeError"}},
    ]
    assert "credential" not in response.text.lower()
    assert "password" not in response.text.lower()


@pytest.mark.asyncio
async def test_protect_get_chime_accepts_explicit_chime_id(main_module, monkeypatch):
    response = type("Response", (), {
        "status_code": 200,
        "json": lambda self: {"id": "chime-three"},
    })()
    request = AsyncMock(return_value=response)
    monkeypatch.setattr(main_module.protect, "_do", request)

    result = await main_module.protect.get_chime(chime_id="chime-three")

    assert result["id"] == "chime-three"
    assert request.await_args.args[1].endswith("/chimes/chime-three")


@pytest.mark.asyncio
async def test_file_credential_401_refreshes_once_after_file_change(
    main_module, tmp_path
):
    credential_file = tmp_path / "chime_password"
    credential_file.write_text("old-placeholder")
    client = main_module.DirectChimeClient()
    client._base = "https://192.0.2.10:8080"
    client._credential_provider = main_module.FileCredentialProvider(
        str(credential_file)
    )
    seen_passwords = []

    def respond(request):
        password = json.loads(request.content)["password"]
        seen_passwords.append(password)
        if len(seen_passwords) == 1:
            credential_file.write_text("new-placeholder")
            return httpx.Response(401)
        return httpx.Response(200, json={"version": "v1.7.20"})

    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://192.0.2.10:8080/api/info").mock(
            side_effect=respond
        )
        response = await client._post("/api/info")

    assert response.status_code == 200
    assert seen_passwords == ["old-placeholder", "new-placeholder"]
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_generic_direct_upload_fails_before_network_without_slot_metadata(
    main_module,
):
    client = main_module.DirectChimeClient()
    with respx.mock(assert_all_mocked=True) as router:
        with pytest.raises(RuntimeError, match="owned-slot metadata"):
            await client.upload_ringtone("fixture", b"sanitized-mp3-fixture")
    assert router.calls.call_count == 0


@pytest.mark.asyncio
async def test_owned_slot_overwrite_uses_exact_route_raw_body_and_basic_auth(
    main_module,
):
    client = main_module.DirectChimeClient()
    client._base = "https://192.0.2.10:8080"
    client._credential_provider = main_module.StaticEnvCredentialProvider(
        "test-placeholder"
    )
    expected_url = (
        "https://192.0.2.10:8080/api/uploadRingtone/7/"
        "050da2f0-fixture.mp3"
    )

    def verify_request(request):
        assert request.content == b"sanitized-mp3-fixture"
        assert request.headers["content-type"] == "audio/mpeg"
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json={})

    with respx.mock(assert_all_called=True) as router:
        info_route = router.post("https://192.0.2.10:8080/api/info").mock(
            return_value=httpx.Response(200, json={
                "version": "v1.7.20",
                "featureFlags": {"supportCustomRingtone": True},
            })
        )
        upload_route = router.post(expected_url).mock(side_effect=verify_request)
        result = await client.overwrite_owned_slot(
            slot=7, filename="050da2f0-fixture.mp3",
            mp3_bytes=b"sanitized-mp3-fixture",
            owner="unifi_announcer",
            experiment_enabled=True,
        )

    assert result == {
        "uploaded": True, "via": "direct-owned-slot", "slot": 7,
        "filename": "050da2f0-fixture.mp3",
    }
    assert info_route.call_count == 1
    assert upload_route.call_count == 1


@pytest.mark.asyncio
async def test_owned_slot_overwrite_rejects_unowned_before_network(main_module):
    client = main_module.DirectChimeClient()
    with respx.mock(assert_all_mocked=True) as router:
        with pytest.raises(RuntimeError, match="service-owned"):
            await client.overwrite_owned_slot(
                slot=5, filename="foreign.mp3", mp3_bytes=b"fixture",
                owner="unknown",
                experiment_enabled=True,
            )
    assert router.calls.call_count == 0


@pytest.mark.asyncio
async def test_owned_slot_overwrite_unknown_firmware_fails_closed(main_module):
    client = main_module.DirectChimeClient()
    client._base = "https://192.0.2.10:8080"
    client._credential_provider = main_module.StaticEnvCredentialProvider(
        "test-placeholder"
    )

    with respx.mock(assert_all_called=True) as router:
        router.post("https://192.0.2.10:8080/api/info").mock(
            return_value=httpx.Response(200, json={
                "version": "v9.9.9",
                "featureFlags": {"supportCustomRingtone": True},
            })
        )
        with pytest.raises(RuntimeError, match="capability gate"):
            await client.overwrite_owned_slot(
                slot=7, filename="fixture.mp3",
                mp3_bytes=b"sanitized-mp3-fixture",
                owner="unifi_announcer",
                experiment_enabled=True,
            )


@pytest.mark.asyncio
async def test_owned_slot_overwrite_is_default_off_before_network(main_module):
    client = main_module.DirectChimeClient()
    with respx.mock(assert_all_mocked=True) as router:
        with pytest.raises(RuntimeError, match="DYNAMIC_SLOT_EXPERIMENT"):
            await client.overwrite_owned_slot(
                slot=7, filename="fixture.mp3", mp3_bytes=b"fixture",
                owner="unifi_announcer",
            )
    assert router.calls.call_count == 0


@pytest.mark.asyncio
async def test_facade_upload_disables_generic_direct_staging(main_module, monkeypatch):
    direct_upload = AsyncMock(return_value={"uploaded": True, "via": "direct"})
    nvr_upload = AsyncMock(return_value={"id": "ringtone-id", "name": "fixture"})
    direct_client = SimpleNamespace(upload_ringtone=direct_upload)
    monkeypatch.setattr(main_module.protect, "upload_ringtone", nvr_upload)

    result = await main_module.chime_client.upload_ringtone(
        "fixture", b"mp3", direct_clients=[direct_client]
    )

    direct_upload.assert_not_awaited()
    nvr_upload.assert_awaited_once_with("fixture", b"mp3")
    assert result["via"] == "nvr"
    assert result["direct_targets_uploaded"] == 0
    assert result["id"] == "ringtone-id"


def test_destructive_endpoint_is_blocked_before_network(main_module):
    with respx.mock(assert_all_mocked=True) as router:
        with pytest.raises(RuntimeError, match="blocked destructive endpoint"):
            main_module.guard_destructive("/api/factoryResetWithoutWiFi")

    assert router.calls.call_count == 0
