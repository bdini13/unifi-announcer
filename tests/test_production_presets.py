from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.playback.arbitration import ChimeDescriptor, ChimeRuntime


@pytest.mark.asyncio
@pytest.mark.parametrize("name,existing,status,spoken", [
    ("alert", True, 200, None),
    ("package-delivered", True, 200, None),
    ("package-delivered", False, 200, "package delivered"),
    ("missing", False, 404, None),
])
async def test_production_preset_selection(monkeypatch, name, existing, status, spoken):
    from app import server

    core = server.core
    index = SimpleNamespace(resolve_or_refresh=AsyncMock(
        return_value={"id": "saved-audio", "name": name} if existing else None),
        get=lambda _: {"id": "saved-audio", "name": name} if existing else None)
    monkeypatch.setattr(core, "ringtone_index", index)
    monkeypatch.setattr(core, "APP_API_KEY", "test-key")
    monkeypatch.setattr(server, "SLOT_BACKED_PRESETS", ("package-delivered",))
    synthesize = AsyncMock(return_value=b"spoken bytes")
    monkeypatch.setattr(server, "tts_cache", synthesize)
    lease = SimpleNamespace(logical_slot=1, ringtone_id="dynamic-audio",
                            duration_ms=1, release_after=Mock(), release_now=AsyncMock())
    slots = SimpleNamespace(prepare=AsyncMock(return_value=lease))
    target = ChimeRuntime(ChimeDescriptor("default", "chime-fixture"))
    from app.playback.admission import DispatchAdmission
    admission = DispatchAdmission()
    dispatcher = core.dispatcher
    monkeypatch.setattr(dispatcher, "admission", admission)
    monkeypatch.setattr(dispatcher, "dynamic_slots", slots)
    monkeypatch.setattr(dispatcher, "synthesize_preset", server._synthesize_preset)
    monkeypatch.setattr(dispatcher, "resolve_targets", lambda _: [target])
    monkeypatch.setattr(dispatcher, "quiet", lambda: False)
    protect = SimpleNamespace(play=AsyncMock(return_value={"played": True}))
    monkeypatch.setattr(dispatcher, "protect", protect)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                    base_url="http://test",
                                    headers={"X-API-Key": "test-key"}) as client:
            response = await client.post(f"/presets/{name}/play")
        assert response.status_code == status
        if spoken:
            synthesize.assert_awaited_once_with(spoken)
            slots.prepare.assert_awaited_once()
        else:
            synthesize.assert_not_awaited()
            slots.prepare.assert_not_awaited()
        if existing:
            assert protect.play.await_args.args[0] == "saved-audio"
        if status == 404:
            protect.play.assert_not_awaited()
    finally:
        await admission.stop()
        await target.stop()
