import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.playback.camera_hardening import (
    CameraProtocolProfile,
    HardenedCameraTalkback,
    load_experimental_camera_profiles,
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


def _low_level_profile(**overrides):
    values = {
        "codec": "aac",
        "transport": "serverudp",
        "sample_rate": 22050,
        "channels": 1,
        "bits_per_sample": 16,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _g4_camera(**overrides):
    return _camera(type="UVC G4 Instant", **overrides)


def _experimental_aac_profile():
    return CameraProtocolProfile(
        codec="aac",
        transport="serverudp",
        sample_rate=22050,
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


def test_experimental_profiles_default_to_empty_and_require_exact_opt_in():
    assert load_experimental_camera_profiles("") == frozenset()
    profiles = load_experimental_camera_profiles(
        '[{"codec":"aac","transport":"serverudp","sample_rate":22050,'
        '"channels":1,"bits_per_sample":16}]'
    )
    assert profiles == frozenset({_experimental_aac_profile()})

    profile = validate_camera_profile(
        _g4_camera(), experimental_profiles=profiles
    )
    assert profile.model == "UVC G4 Instant"

    mismatched = _g4_camera(talkbackSettings={
        "typeFmt": "aac",
        "typeIn": "serverudp",
        "samplingRate": 48000,
        "bitsPerSample": 16,
        "channels": 1,
    })
    with pytest.raises(CameraTalkbackError, match="not been physically validated"):
        validate_camera_profile(mismatched, experimental_profiles=profiles)


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "{}",
        "[{}]",
        '[{"codec":"opus","transport":"serverudp-rtp",'
        '"sample_rate":24000,"channels":1,"bits_per_sample":16}]',
        '[{"codec":"aac","transport":"serverudp","sample_rate":22050,'
        '"channels":1,"bits_per_sample":16,"unexpected":true}]',
        '[{"codec":"aac","transport":"serverudp","sample_rate":22050,'
        '"channels":1,"bits_per_sample":16},'
        '{"codec":"aac","transport":"serverudp","sample_rate":22050,'
        '"channels":1,"bits_per_sample":16}]',
    ],
)
def test_experimental_profile_config_rejects_malformed_or_unsupported_entries(raw):
    with pytest.raises(RuntimeError, match="EXPERIMENTAL_CAMERA_PROFILES"):
        load_experimental_camera_profiles(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '[{"codec":"aac","transport":"serverudp","sample_rate":"22050",'
        '"channels":1,"bits_per_sample":16}]',
        '[{"codec":"aac","transport":"serverudp","sample_rate":22050,'
        '"channels":true,"bits_per_sample":16}]',
    ],
)
def test_experimental_profile_config_rejects_coerced_numeric_types(raw):
    with pytest.raises(RuntimeError, match="EXPERIMENTAL_CAMERA_PROFILES"):
        load_experimental_camera_profiles(raw)


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


@pytest.mark.parametrize(
    "field,value",
    [
        ("samplingRate", 22050.0),
        ("channels", True),
        ("bitsPerSample", 16.0),
    ],
)
def test_bootstrap_profile_rejects_type_equivalent_numeric_values(field, value):
    settings = dict(_camera()["talkbackSettings"])
    settings[field] = value

    with pytest.raises(CameraTalkbackError, match="invalid talkback settings"):
        validate_camera_profile(_camera(talkbackSettings=settings))


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
    def __init__(self, **profile_overrides):
        self.closed = False
        self.played = False
        self.profile = _low_level_profile(**profile_overrides)

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
@pytest.mark.parametrize(
    "field,value",
    [
        ("sample_rate", 22050.0),
        ("channels", True),
        ("bits_per_sample", 16.0),
    ],
)
async def test_prepared_session_rejects_type_equivalent_profile_values(
    field, value
):
    prepared = _Prepared(**{field: value})
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


@pytest.mark.asyncio
async def test_inspect_labels_exact_protocol_opt_in_as_experimental_not_validated():
    delegate = SimpleNamespace(_camera=AsyncMock(return_value=_g4_camera()))
    hardened = HardenedCameraTalkback(
        delegate,
        experimental_profiles=frozenset({_experimental_aac_profile()}),
    )

    state = await hardened.inspect("camera-one")

    assert state["status"] == "available"
    assert state["model"] == "UVC G4 Instant"
    assert state["compatibility"] == "experimental_opt_in"


@pytest.mark.asyncio
async def test_validated_g3_label_wins_over_matching_experimental_profile():
    delegate = SimpleNamespace(_camera=AsyncMock(return_value=_camera()))
    hardened = HardenedCameraTalkback(
        delegate,
        experimental_profiles=frozenset({_experimental_aac_profile()}),
    )

    state = await hardened.inspect("camera-one")

    assert state["status"] == "available"
    assert state["compatibility"] == "physically_validated"


@pytest.mark.asyncio
async def test_inspect_normalizes_missing_configured_camera_as_unavailable():
    delegate = SimpleNamespace(
        _camera=AsyncMock(
            side_effect=CameraTalkbackError("configured camera is unavailable")
        ),
    )
    hardened = HardenedCameraTalkback(delegate)
    state = await hardened.inspect("camera-one")
    assert state == {
        "status": "unavailable",
        "error": "configured camera is unavailable",
        "model": "camera",
    }
