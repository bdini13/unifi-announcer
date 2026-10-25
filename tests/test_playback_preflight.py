import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.dispatcher import AnnouncementCommand, StaleRingtoneError
from app.playback.admission import DispatchAdmission, Reservation
from app.playback.arbitration import ChimeDescriptor, ChimeRuntime
from app.tracks import TrackRecord, TrackRegistry
from test_dispatcher import _dispatcher


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing-id", "offline", "missing-track", "good"])
async def test_ordinary_play_does_not_send_known_fallback_request(main_module, respx_mock, case):
    client = main_module.ProtectClient()
    client._logged_in = True
    audio = b"requested canonical audio"
    respx_mock.get("https://unifi.invalid/proxy/protect/api/ringtones").respond(
        200, json=[] if case == "missing-id" else [{"id": "tone", "name": "saved"}])
    if case != "missing-id":
        respx_mock.get("https://unifi.invalid/proxy/protect/api/chimes/chime-fixture").respond(
            200, json={"state": "DISCONNECTED" if case == "offline" else "CONNECTED",
                       "speakerTrackList": [] if case == "missing-track" else [{"md5": hashlib.md5(audio).hexdigest()}]})
    if case not in ("missing-id", "offline"):
        respx_mock.get("https://unifi.invalid/proxy/protect/api/ringtones/tone").respond(200, content=audio)
    if case == "good":
        respx_mock.post("https://unifi.invalid/proxy/protect/api/chimes/chime-fixture/play-speaker").respond(204)
        assert (await client.play("tone"))["played"]
    else:
        with pytest.raises((RuntimeError, StaleRingtoneError)):
            await client.play("tone")
    assert sum(call.request.method == "POST" for call in respx_mock.calls) == (case == "good")
    await client._client.aclose()


@pytest.mark.asyncio
async def test_owned_direct_audio_uses_binding_check_instead_of_bootstrap_hash(main_module, respx_mock):
    client = main_module.ProtectClient()
    client._logged_in = True
    client.owned_ringtone_check = Mock(return_value=True)
    respx_mock.get("https://unifi.invalid/proxy/protect/api/ringtones").respond(200, json=[{"id": "owned"}])
    respx_mock.get("https://unifi.invalid/proxy/protect/api/chimes/chime-fixture").respond(200, json={"state": "CONNECTED"})
    respx_mock.post("https://unifi.invalid/proxy/protect/api/chimes/chime-fixture/play-speaker").respond(204)
    await client.play("owned")
    client.owned_ringtone_check.assert_called_once()
    await client._client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [False, True])
async def test_preset_identity_change_uses_fallback_duration(tmp_path, monkeypatch, retry):
    target = ChimeRuntime(ChimeDescriptor("one", "one"))
    play = AsyncMock(side_effect=[StaleRingtoneError("old"), {}] if retry else [{}])
    dispatcher = _dispatcher(protect=SimpleNamespace(play=play), targets=[target])
    dispatcher.admission = DispatchAdmission()
    dispatcher.track_registry = TrackRegistry(tmp_path / "tracks.json")
    dispatcher.track_registry.put(TrackRecord("saved", "preset", nvr_ringtone_id="old", duration_ms=1000))
    dispatcher.resolve_preset = AsyncMock(return_value="old" if retry else "new")
    dispatcher.index = SimpleNamespace(invalidate=Mock(), force_refresh=AsyncMock(), get=lambda _: {"id": "new", "name": "saved"})
    calls = []
    original = Reservation.hold_for
    def record(self, target, seconds, **kwargs):
        calls.append(seconds)
        original(self, target, seconds, **kwargs)
    monkeypatch.setattr(Reservation, "hold_for", record)
    assert (await dispatcher.dispatch(AnnouncementCommand(action="play_preset", preset="saved", repeat_times=1))).disposition == "played"
    assert calls[-1] == 31.25
    if not retry:
        assert calls[0] == 31.25
    else:
        assert dispatcher.track_registry.records["saved"].duration_ms is None
    await dispatcher.admission.stop()


@pytest.mark.asyncio
async def test_device_default_repeat_reserves_controller_maximum(monkeypatch):
    target = ChimeRuntime(ChimeDescriptor("one", "one"))
    dispatcher = _dispatcher(protect=SimpleNamespace(play_default=AsyncMock(return_value={})), targets=[target])
    dispatcher.admission = DispatchAdmission()
    calls = []
    monkeypatch.setattr(Reservation, "hold_for", lambda self, target, seconds, **kwargs: calls.append(seconds))
    await dispatcher.dispatch(AnnouncementCommand(action="play_default"))
    assert calls == [301.25, 301.25]
    await dispatcher.admission.stop()
