import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.playback.camera_hardening import (
    HardenedCameraTalkback,
    load_validated_groups,
    validate_camera_profile,
)
from app.playback.camera_talkback import CameraTalkbackError


def _camera(**overrides):
    camera = {
        "id": "camera-one",
        "name": "Family Room",
        "type": "UVC G3 Instant",
        "state": "CONNECTED",
        "featureFlags": {"hasSpeaker": True},
        "talkbackSettings": {
            "typeFmt": "aac",
            "typeIn": "serverudp",
            "samplingRate": 22050,
            "bitsPerSample": 16,
            "channels": 1,
        },
    }
    camera.update(overrides)
    return camera


def _low_level_profile(*, sample_rate=22050):
    return SimpleNamespace(
        codec="aac",
        transport="serverudp",
        sample_rate=sample_rate,
        channels=1,
        bits_per_sample=16,
    )


def test_validated_camera_profile_is_exact_model_and_transport_contract():
    profile = validate_camera_profile(_camera())
    assert profile.model == "UVC G3 Instant"
    assert profile.sample_rate == 22050
    assert profile.codec == "aac"


@pytest.mark.parametrize(
    "camera",
    [
        _camera(type="UVC G4 Instant"),
        _camera(talkbackSettings={
            "typeFmt": "aac",
            "typeIn": "serverudp",
            "samplingRate": 48000,
            "bitsPerSample": 16,
            "channels": 1,
        }),
        _camera(talkbackSettings={
            "typeFmt": "opus",
            "typeIn": "serverudp-rtp",
            "samplingRate": 24000,
            "bitsPerSample": 16,
            "channels": 1,
        }),
    ],
)
def test_unvalidated_model_or_profile_fails_closed(camera):
    with pytest.raises(CameraTalkbackError, match="not been physically validated"):
        validate_camera_profile(camera)


def test_malformed_profile_values_fail_closed_as_camera_errors():
    camera = _camera(talkbackSettings={
        "typeFmt": "aac",
        "typeIn": "serverudp",
        "samplingRate": "not-a-number",
        "bitsPerSample": 16,
        "channels": 1,
    })
    with pytest.raises(CameraTalkbackError, match="invalid talkback settings"):
        validate_camera_profile(camera)


def test_groups_reject_unknown_duplicate_or_reserved_members():
    known = {"kitchen", "family_room_camera"}
    assert load_validated_groups(
        '{"mixed":["kitchen","family_room_camera"]}',
        target_names=known,
    ) == {"mixed": ["kitchen", "family_room_camera"]}

    with pytest.raises(RuntimeError, match="unknown target"):
        load_validated_groups(
            '{"mixed":["kitchen","missing"]}', target_names=known
        )
    with pytest.raises(RuntimeError, match="duplicate target"):
        load_validated_groups(
            '{"mixed":["kitchen","kitchen"]}', target_names=known
        )
    with pytest.raises(RuntimeError, match="reserved group"):
        load_validated_groups(
            '{"kitchen":["family_room_camera"]}', target_names=known
        )


class _Prepared:
    def __init__(self, *, sample_rate=22050):
        self.closed = False
        self.played = False
        self.profile = _low_level_profile(sample_rate=sample_rate)

    async def play(self):
        self.played = True
        return {"played": True}

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_per_camera_preparation_lease_blocks_overlapping_sessions():
    first = _Prepared()
    second = _Prepared()
    delegate = SimpleNamespace(
        _camera=AsyncMock(return_value=_camera()),
        prepare=AsyncMock(side_effect=[first, second]),
    )
    hardened = HardenedCameraTalkback(delegate)

    prepared_one = await hardened.prepare("camera-one", b"mp3")
    second_task = asyncio.create_task(hardened.prepare("camera-one", b"mp3-2"))
    await asyncio.sleep(0)

    assert delegate.prepare.await_count == 1
    assert not second_task.done()

    await prepared_one.close()
    prepared_two = await asyncio.wait_for(second_task, timeout=0.2)
    assert delegate.prepare.await_count == 2
    await prepared_two.close()


@pytest.mark.asyncio
async def test_different_cameras_can_prepare_concurrently():
    entered = {"one": asyncio.Event(), "two": asyncio.Event()}
    release = asyncio.Event()

    async def camera(camera_id):
        return _camera(id=camera_id)

    async def prepare(camera_id, _mp3, **_kwargs):
        entered["one" if camera_id == "camera-one" else "two"].set()
        await release.wait()
        return _Prepared()

    delegate = SimpleNamespace(
        _camera=camera,
        prepare=prepare,
    )
    hardened = HardenedCameraTalkback(delegate)

    one = asyncio.create_task(hardened.prepare("camera-one", b"one"))
    two = asyncio.create_task(hardened.prepare("camera-two", b"two"))
    await asyncio.wait_for(entered["one"].wait(), timeout=0.2)
    await asyncio.wait_for(entered["two"].wait(), timeout=0.2)
    release.set()
    prepared_one, prepared_two = await asyncio.gather(one, two)
    await prepared_one.close()
    await prepared_two.close()


@pytest.mark.asyncio
async def test_prepared_session_profile_mismatch_fails_before_playback():
    prepared = _Prepared(sample_rate=48000)
    delegate = SimpleNamespace(
        _camera=AsyncMock(return_value=_camera()),
        prepare=AsyncMock(return_value=prepared),
    )
    hardened = HardenedCameraTalkback(delegate)

    with pytest.raises(CameraTalkbackError, match="profile changed before playback"):
        await hardened.prepare("camera-one", b"mp3")

    assert prepared.closed is True
    assert prepared.played is False


@pytest.mark.asyncio
async def test_profile_change_during_preparation_fails_closed():
    changed = _camera(talkbackSettings={
        "typeFmt": "aac",
        "typeIn": "serverudp",
        "samplingRate": 48000,
        "bitsPerSample": 16,
        "channels": 1,
    })
    prepared = _Prepared()
    delegate = SimpleNamespace(
        _camera=AsyncMock(side_effect=[_camera(), changed]),
        prepare=AsyncMock(return_value=prepared),
    )
    hardened = HardenedCameraTalkback(delegate)

    with pytest.raises(CameraTalkbackError, match="not been physically validated"):
        await hardened.prepare("camera-one", b"mp3")

    assert prepared.closed is True
    assert prepared.played is False


@pytest.mark.asyncio
async def test_inspect_reports_unvalidated_camera_as_unavailable_without_enabling_it():
    delegate = SimpleNamespace(
        _camera=AsyncMock(return_value=_camera(type="UVC G4 Instant")),
    )
    hardened = HardenedCameraTalkback(delegate)
    state = await hardened.inspect("camera-one")
    assert state["status"] == "unavailable"
    assert state["model"] == "UVC G4 Instant"
    assert "validated" in state["error"]
