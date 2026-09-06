import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.playback.camera_talkback import (
    CameraTalkbackError,
    CameraTalkbackProfile,
    ProtectCameraTalkback,
    confine_talkback_url,
    split_adts_frames,
    transcode_mp3_to_adts,
)


def _camera(**overrides):
    camera = {
        "id": "camera-fixture",
        "name": "Family Room",
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


def _adts_frame(payload: bytes) -> bytes:
    length = 7 + len(payload)
    return bytes([
        0xFF,
        0xF1,
        0x5C,
        0x40 | ((length >> 11) & 0x03),
        (length >> 3) & 0xFF,
        ((length & 0x07) << 5) | 0x1F,
        0xFC,
    ]) + payload


def test_camera_profile_accepts_only_verified_connected_aac_speaker():
    profile = CameraTalkbackProfile.from_camera(_camera())
    assert profile.camera_id == "camera-fixture"
    assert profile.sample_rate == 22050
    assert profile.channels == 1
    assert profile.codec == "aac"


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"state": "DISCONNECTED"}, "not connected"),
        ({"featureFlags": {"hasSpeaker": False}}, "has no speaker"),
        ({"talkbackSettings": {"typeFmt": "opus", "typeIn": "serverudp-rtp", "samplingRate": 24000, "bitsPerSample": 16, "channels": 1}}, "unsupported talkback profile"),
        ({"talkbackSettings": None}, "missing talkback settings"),
    ],
)
def test_camera_profile_fails_closed_for_unverified_capabilities(patch, message):
    with pytest.raises(CameraTalkbackError, match=message):
        CameraTalkbackProfile.from_camera(_camera(**patch))


def test_split_adts_frames_returns_complete_frames_and_rejects_truncation():
    first = _adts_frame(b"one")
    second = _adts_frame(b"two-two")
    assert split_adts_frames(first + second) == [first, second]
    with pytest.raises(CameraTalkbackError, match="truncated ADTS"):
        split_adts_frames(first + second[:-1])
    with pytest.raises(CameraTalkbackError, match="invalid ADTS"):
        split_adts_frames(b"not-adts")


def test_split_adts_frames_validates_aac_lc_rate_and_channels():
    frame = _adts_frame(b"one")
    assert split_adts_frames(frame, sample_rate=22050, channels=1) == [frame]
    with pytest.raises(CameraTalkbackError, match="sample rate"):
        split_adts_frames(frame, sample_rate=24000, channels=1)
    with pytest.raises(CameraTalkbackError, match="channel"):
        split_adts_frames(frame, sample_rate=22050, channels=2)
    wrong_profile = bytearray(frame)
    wrong_profile[2] = wrong_profile[2] & 0x3F
    with pytest.raises(CameraTalkbackError, match="AAC-LC"):
        split_adts_frames(bytes(wrong_profile), sample_rate=22050, channels=1)
    multiple_blocks = bytearray(frame)
    multiple_blocks[6] |= 0x01
    with pytest.raises(CameraTalkbackError, match="raw data block"):
        split_adts_frames(bytes(multiple_blocks), sample_rate=22050, channels=1)


def test_talkback_url_is_confined_to_controller_host_and_minted_port():
    assert confine_talkback_url(
        "wss://internal-console:7443/ws/talkback?token=opaque",
        "https://protect.example.test",
    ) == "wss://protect.example.test:7443/ws/talkback?token=opaque"


@pytest.mark.parametrize(
    "url",
    [
        "https://internal/ws/talkback?token=x",
        "wss://user:pass@internal/ws/talkback?token=x",
        "wss://internal/not-talkback?token=x",
        "wss://internal/ws/talkback",
        "wss://internal/ws/talkback?token=x#fragment",
        "wss://internal:443/ws/talkback?token=x",
        "wss://internal:65535/ws/talkback?token=x",
    ],
)
def test_talkback_url_rejects_unsafe_or_malformed_negotiation(url):
    with pytest.raises(CameraTalkbackError, match="invalid talkback URL"):
        confine_talkback_url(url, "https://protect.example.test")


def test_talkback_url_rejects_controller_userinfo():
    with pytest.raises(CameraTalkbackError, match="invalid talkback URL"):
        confine_talkback_url(
            "wss://internal:7443/ws/talkback?token=x",
            "https://user:pass@protect.example.test",
        )


class _Socket:
    def __init__(self):
        self.sent = []

    async def send(self, frame):
        self.sent.append(frame)


class _Connection:
    def __init__(self, socket):
        self.socket = socket
        self.exited = False

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *_args):
        self.exited = True
        return None


@pytest.mark.asyncio
async def test_camera_playback_revalidates_capability_and_paces_complete_frames():
    first = _adts_frame(b"one")
    second = _adts_frame(b"two")
    response = httpx.Response(
        200,
        json={"url": "wss://internal-console:7443/ws/talkback?token=opaque"},
        request=httpx.Request("GET", "https://protect.example.test/negotiate"),
    )
    protect = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": [_camera()]}),
        _do=AsyncMock(return_value=response),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    socket = _Socket()
    connector = AsyncMock(return_value=_Connection(socket))
    sleeps = []

    async def sleep(value):
        sleeps.append(value)

    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(return_value=first + second),
        connector=connector,
        sleep=sleep,
        arm_delay=0.4,
        drain_delay=0.5,
    )

    result = await client.play("camera-fixture", b"mp3", repeat_times=2)

    protect.bootstrap.assert_awaited_once()
    protect._do.assert_awaited_once_with(
        "GET", "/proxy/protect/api/ws/talkback", params={"camera": "camera-fixture"}
    )
    assert socket.sent == [first, second, first, second]
    assert sleeps == [0.4, 1024 / 22050, 1024 / 22050, 1024 / 22050, 1024 / 22050, 0.5]
    assert result == {
        "played": True,
        "target_type": "camera",
        "codec": "aac",
        "sample_rate": 22050,
        "frames": 4,
        "repeat_times": 2,
        "volume_control": "device",
    }
    kwargs = connector.await_args.kwargs
    assert kwargs["origin"] == "https://protect.example.test"
    assert kwargs["extra_headers"] == {"Cookie": "TOKEN=redacted"}
    assert "opaque" not in repr(result)


@pytest.mark.asyncio
async def test_camera_playback_wraps_transport_errors_without_signed_url():
    response = httpx.Response(
        200,
        json={"url": "wss://internal-console:7443/ws/talkback?token=super-secret"},
        request=httpx.Request("GET", "https://protect.example.test/negotiate"),
    )
    protect = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": [_camera()]}),
        _do=AsyncMock(return_value=response),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    connector = AsyncMock(side_effect=RuntimeError("failed wss://host?token=super-secret"))
    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(return_value=_adts_frame(b"one")),
        connector=connector,
        sleep=AsyncMock(),
    )

    with pytest.raises(CameraTalkbackError) as raised:
        await client.play("camera-fixture", b"mp3")
    assert str(raised.value) == "camera talkback transport failed"
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_camera_playback_normalizes_non_object_negotiation_payload():
    response = httpx.Response(
        200,
        json=["not-an-object"],
        request=httpx.Request("GET", "https://protect.example.test/negotiate"),
    )
    protect = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": [_camera()]}),
        _do=AsyncMock(return_value=response),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(return_value=_adts_frame(b"one")),
        connector=AsyncMock(),
        sleep=AsyncMock(),
    )

    with pytest.raises(CameraTalkbackError, match="negotiation response"):
        await client.play("camera-fixture", b"mp3")


@pytest.mark.asyncio
async def test_camera_playback_rejects_missing_configured_camera_before_negotiation():
    protect = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": []}),
        _do=AsyncMock(),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(),
        connector=AsyncMock(),
        sleep=AsyncMock(),
    )

    with pytest.raises(CameraTalkbackError, match="configured camera is unavailable"):
        await client.play("camera-fixture", b"mp3")
    protect._do.assert_not_awaited()


@pytest.mark.asyncio
async def test_camera_playback_cancellation_closes_socket_without_replay():
    response = httpx.Response(
        200,
        json={"url": "wss://internal-console:7443/ws/talkback?token=opaque"},
        request=httpx.Request("GET", "https://protect.example.test/negotiate"),
    )
    protect = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": [_camera()]}),
        _do=AsyncMock(return_value=response),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    socket = _Socket()
    connection = _Connection(socket)
    sleeping = asyncio.Event()

    async def blocked_sleep(_value):
        sleeping.set()
        await asyncio.Event().wait()

    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(return_value=_adts_frame(b"one")),
        connector=AsyncMock(return_value=connection),
        sleep=blocked_sleep,
    )
    task = asyncio.create_task(client.play("camera-fixture", b"mp3"))
    await asyncio.wait_for(sleeping.wait(), timeout=0.2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert connection.exited is True
    assert socket.sent == []
    assert protect._do.await_count == 1


@pytest.mark.asyncio
async def test_camera_playback_session_has_a_total_timeout():
    response = httpx.Response(
        200,
        json={"url": "wss://internal-console:7443/ws/talkback?token=opaque"},
        request=httpx.Request("GET", "https://protect.example.test/negotiate"),
    )
    protect = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": [_camera()]}),
        _do=AsyncMock(return_value=response),
        session_cookie_header=lambda: "TOKEN=redacted",
    )

    async def blocked_sleep(_value):
        await asyncio.Event().wait()

    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(return_value=_adts_frame(b"one")),
        connector=AsyncMock(return_value=_Connection(_Socket())),
        sleep=blocked_sleep,
        arm_delay=0,
        drain_delay=0,
        session_timeout=0.1,
    )

    with pytest.raises(CameraTalkbackError, match="operation timed out"):
        await client.play("camera-fixture", b"mp3")


@pytest.mark.asyncio
async def test_total_timeout_includes_bootstrap_and_rejects_oversized_duration():
    async def blocked_bootstrap():
        await asyncio.Event().wait()

    protect = SimpleNamespace(
        bootstrap=blocked_bootstrap,
        _do=AsyncMock(),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(),
        connector=AsyncMock(),
        sleep=AsyncMock(),
        session_timeout=0.01,
    )
    with pytest.raises(CameraTalkbackError, match="operation timed out"):
        await client.play("camera-fixture", b"mp3")
    protect._do.assert_not_awaited()

    many_frames = _adts_frame(b"x") * 100
    ready = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": [_camera()]}),
        _do=AsyncMock(),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    client = ProtectCameraTalkback(
        protect=ready,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=AsyncMock(return_value=many_frames),
        connector=AsyncMock(),
        sleep=AsyncMock(),
        session_timeout=1.0,
    )
    with pytest.raises(CameraTalkbackError, match="duration exceeds"):
        await client.play("camera-fixture", b"mp3")
    ready._do.assert_not_awaited()


@pytest.mark.asyncio
async def test_duration_admission_uses_remaining_deadline_before_negotiation():
    async def slow_transcode(*_args, **_kwargs):
        await asyncio.sleep(0.08)
        return _adts_frame(b"x") * 4

    protect = SimpleNamespace(
        bootstrap=AsyncMock(return_value={"cameras": [_camera()]}),
        _do=AsyncMock(),
        session_cookie_header=lambda: "TOKEN=redacted",
    )
    client = ProtectCameraTalkback(
        protect=protect,
        controller_url="https://protect.example.test",
        verify_ssl=False,
        transcode=slow_transcode,
        connector=AsyncMock(),
        sleep=AsyncMock(),
        arm_delay=0,
        drain_delay=0,
        session_timeout=0.2,
    )

    with pytest.raises(CameraTalkbackError, match="duration exceeds"):
        await client.play("camera-fixture", b"mp3")
    protect._do.assert_not_awaited()


class _ProcessInput:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data += data

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


class _ProcessOutput:
    def __init__(self, chunks=None, blocked=None):
        self.chunks = list(chunks or [])
        self.blocked = blocked

    async def read(self, _size):
        if self.blocked is not None:
            self.blocked.set()
            await asyncio.Event().wait()
        return self.chunks.pop(0) if self.chunks else b""


class _Process:
    def __init__(self, chunks=None, blocked=None):
        self.stdin = _ProcessInput()
        self.stdout = _ProcessOutput(chunks, blocked)
        self.returncode = None
        self.killed = False
        self.waited = False

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


@pytest.mark.asyncio
async def test_transcode_streams_output_and_kills_process_at_bound():
    process = _Process(chunks=[b"1234", b"5678"])

    async def factory(*_args, **_kwargs):
        return process

    with pytest.raises(CameraTalkbackError, match="too large"):
        await transcode_mp3_to_adts(
            b"mp3",
            sample_rate=22050,
            channels=1,
            max_output_bytes=6,
            process_factory=factory,
        )

    assert process.killed is True
    assert process.waited is True
    assert process.stdin.closed is True


@pytest.mark.asyncio
async def test_transcode_cancellation_kills_and_reaps_process():
    entered = asyncio.Event()
    process = _Process(blocked=entered)

    async def factory(*_args, **_kwargs):
        return process

    task = asyncio.create_task(transcode_mp3_to_adts(
        b"mp3",
        sample_rate=22050,
        channels=1,
        process_factory=factory,
    ))
    await asyncio.wait_for(entered.wait(), timeout=0.2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed is True
    assert process.waited is True
