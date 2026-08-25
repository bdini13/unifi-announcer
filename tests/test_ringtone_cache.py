import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import respx


def transport_for(module):
    return httpx.ASGITransport(app=module.app)


@pytest.mark.asyncio
async def test_cache_status_and_authenticated_refresh(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "fixture-key")
    refresh = AsyncMock()
    monkeypatch.setattr(main_module.ringtone_index, "refresh", refresh)
    async with httpx.AsyncClient(transport=transport_for(main_module), base_url="http://test") as client:
        status = await client.get("/cache/ringtones/status")
        denied = await client.post("/cache/ringtones/refresh")
        accepted = await client.post("/cache/ringtones/refresh", headers={"X-API-Key": "fixture-key"})
    assert status.status_code == 200
    assert set(status.json()) == {"loaded", "entries", "last_refresh_at", "refresh_count"}
    assert denied.status_code == 403
    assert accepted.status_code == 200
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_refresh_is_unavailable_without_admin_key(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "")
    refresh = AsyncMock()
    monkeypatch.setattr(main_module.ringtone_index, "refresh", refresh)
    async with httpx.AsyncClient(transport=transport_for(main_module), base_url="http://test") as client:
        response = await client.post("/cache/ringtones/refresh")
    assert response.status_code == 503
    assert response.json()["detail"] == "admin API key is not configured"
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_ringtone_refresh_uses_one_loader_call():
    from app.audio.cache import RingtoneIndex

    release = asyncio.Event()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        await release.wait()
        return [{"name": "tone", "id": "one"}]

    index = RingtoneIndex(loader)
    first = asyncio.create_task(index.refresh())
    second = asyncio.create_task(index.refresh())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert calls == 1


@pytest.mark.asyncio
async def test_force_refresh_waits_for_inflight_snapshot_then_loads_fresh_state():
    from app.audio.cache import RingtoneIndex

    release = asyncio.Event()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        if calls == 1:
            await release.wait()
            return [{"name": "deleted", "id": "old"}]
        return [{"name": "kept", "id": "new"}]

    index = RingtoneIndex(loader)
    ordinary = asyncio.create_task(index.refresh())
    await asyncio.sleep(0)
    forced = asyncio.create_task(index.force_refresh())
    release.set()
    await asyncio.gather(ordinary, forced)

    assert calls == 2
    assert index.get("deleted") is None
    kept = index.get("kept")
    assert kept is not None and kept["id"] == "new"


@pytest.mark.asyncio
async def test_concurrent_tts_cache_miss_synthesizes_once(main_module, monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    main_module._tts_cache_locks.clear()
    release = asyncio.Event()
    synthesize = AsyncMock()

    async def render(text):
        await release.wait()
        return b"mp3"

    synthesize.side_effect = render
    monkeypatch.setattr(main_module, "synthesize_tts", synthesize)
    first = asyncio.create_task(main_module.synthesize_tts_cached("same phrase"))
    second = asyncio.create_task(main_module.synthesize_tts_cached(" same   phrase "))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [b"mp3", b"mp3"]
    synthesize.assert_awaited_once()
    assert main_module._tts_cache_locks == {}


@pytest.mark.asyncio
async def test_cached_preset_play_is_exactly_one_protect_http_call(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "")
    monkeypatch.setattr(main_module, "CHIME_ID", "chime-fixture")
    main_module.ringtone_index.put({"name": "fixture-tone", "id": "ringtone-fixture"})
    main_module.protect._logged_in = True
    main_module.protect._csrf = "fixture-csrf"

    with respx.mock(assert_all_called=True) as router:
        play = router.post(
            "https://unifi.invalid/proxy/protect/api/chimes/chime-fixture/play-speaker"
        ).mock(return_value=httpx.Response(204))
        async with httpx.AsyncClient(transport=transport_for(main_module), base_url="http://test") as client:
            response = await client.post("/presets/fixture-tone/play")

    assert response.status_code == 200
    # RESPX rejects any unregistered request; this one registered route was
    # called exactly once, proving there was no list-ringtones preflight.
    assert play.call_count == 1


@pytest.mark.asyncio
async def test_preset_resolution_uses_refreshed_ringtone_index_id(main_module):
    main_module.ringtone_index.put({"name": "fixture-tone", "id": "old-id"})
    assert await main_module.resolve_preset_id("fixture-tone") == "old-id"

    main_module.ringtone_index.put({"name": "fixture-tone", "id": "new-id"})

    assert await main_module.resolve_preset_id("fixture-tone") == "new-id"
    assert not hasattr(main_module, "_preset_ids")
