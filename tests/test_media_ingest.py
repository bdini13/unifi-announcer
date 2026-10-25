"""Regression coverage for bounded binary-media ingestion."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.audio.media_ingest import (
    AudioMediaNormalizer,
    InvalidMedia,
    MediaLimits,
    MediaTooLarge,
    UnsupportedMediaType,
)
from app.routes.media import MediaIngress
from app.dispatcher import AnnouncementDispatcher, DispatchResult


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_input_bytes": 0},
        {"max_output_bytes": 0},
        {"max_duration_seconds": 0},
        {"max_duration_seconds": float("nan")},
        {"max_duration_seconds": float("inf")},
        {"max_duration_seconds": "30"},
        {"normalize_timeout_seconds": 0},
        {"normalize_timeout_seconds": float("nan")},
        {"normalize_timeout_seconds": True},
        {"normalize_concurrency": 0},
        {"normalize_concurrency": True},
        {"max_pending_requests": 0},
        {"max_pending_requests": 1.5},
    ],
)
def test_media_limits_fail_closed_on_invalid_configuration(kwargs):
    with pytest.raises(ValueError, match="must be a positive"):
        MediaLimits(**kwargs)


@pytest.mark.asyncio
async def test_media_normalizer_rejects_unsupported_type_before_decode():
    normalizer = AudioMediaNormalizer(MediaLimits(max_input_bytes=32))

    with pytest.raises(UnsupportedMediaType):
        await normalizer.normalize(b"payload", "application/octet-stream")


@pytest.mark.asyncio
async def test_media_normalizer_rejects_oversized_input_before_decode():
    normalizer = AudioMediaNormalizer(MediaLimits(max_input_bytes=4))

    with pytest.raises(MediaTooLarge):
        await normalizer.normalize(b"12345", "audio/mpeg")


@pytest.mark.asyncio
async def test_media_normalizer_rejects_audio_over_duration_limit():
    normalizer = AudioMediaNormalizer(
        MediaLimits(max_input_bytes=32, max_duration_seconds=2.0)
    )

    async def fake_run(*command: str) -> bytes:
        assert command[0] == "ffprobe"
        return (
            b'{"streams":[{"codec_type":"audio","duration":"2.5"}],'
            b'"format":{"duration":"2.5"}}'
        )

    normalizer._run = fake_run  # type: ignore[method-assign]

    with pytest.raises(InvalidMedia, match="duration exceeds"):
        await normalizer.normalize(b"source", "audio/wav")


@pytest.mark.asyncio
async def test_media_normalizer_pins_demuxer_and_converts_to_bounded_mp3():
    normalizer = AudioMediaNormalizer(
        MediaLimits(max_input_bytes=32, max_output_bytes=32, max_duration_seconds=5)
    )
    calls: list[tuple[str, ...]] = []

    async def fake_run(*command: str) -> bytes:
        calls.append(command)
        if command[0] == "ffprobe":
            return (
                b'{"streams":[{"codec_type":"audio","duration":"1.5"}],'
                b'"format":{"duration":"1.5"}}'
            )
        assert command[0] == "ffmpeg"
        return b"normalized-mp3"

    normalizer._run = fake_run  # type: ignore[method-assign]

    result = await normalizer.normalize(b"source", "audio/wav; codecs=pcm")

    assert bytes(result) == b"normalized-mp3"
    assert len(calls) == 2
    ffprobe, ffmpeg = calls
    assert ffprobe[ffprobe.index("-f") + 1] == "wav"
    assert ffmpeg[ffmpeg.index("-f") + 1] == "wav"
    assert ("-ac", "1") == ffmpeg[ffmpeg.index("-ac"):ffmpeg.index("-ac") + 2]
    assert ("-ar", "22050") == ffmpeg[ffmpeg.index("-ar"):ffmpeg.index("-ar") + 2]
    assert ("-map_metadata", "-1") == ffmpeg[
        ffmpeg.index("-map_metadata"):ffmpeg.index("-map_metadata") + 2
    ]
    assert ("-t", "5") == ffmpeg[ffmpeg.index("-t"):ffmpeg.index("-t") + 2]
    assert "libmp3lame" in ffmpeg


class _BlockingProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.killed = False
        self.communicate_calls = 0
        self.started = asyncio.Event()

    async def communicate(self):
        self.communicate_calls += 1
        if self.killed:
            return b"", b""
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


@pytest.mark.asyncio
async def test_media_decoder_is_killed_and_reaped_when_request_is_cancelled():
    normalizer = AudioMediaNormalizer(MediaLimits(normalize_timeout_seconds=30))
    process = _BlockingProcess()

    with patch(
        "app.audio.media_ingest.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    ):
        task = asyncio.create_task(normalizer._run("ffprobe", "input"))
        await process.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert process.killed is True
    assert process.communicate_calls == 2


class _FakeNormalizer:
    def __init__(self, *, limit: int = 64) -> None:
        self.limits = MediaLimits(max_input_bytes=limit)
        self.calls: list[tuple[bytes, str]] = []

    async def normalize(self, payload: bytes, media_type: str) -> bytes:
        self.calls.append((payload, media_type))
        await asyncio.sleep(0)
        return b"normalized:" + payload


class _FakeDispatcher:
    def __init__(self) -> None:
        self.synthesize = None
        self.commands = []
        self.audios = []

    async def dispatch(self, command):
        self.commands.append(command)
        await asyncio.sleep(0)
        audio = await self.synthesize(command.text)
        self.audios.append(audio)
        return SimpleNamespace(
            disposition="played",
            response=lambda: {
                "disposition": "played",
                "targets": 1,
                "test_audio": audio.decode(),
            },
        )


def _media_app(normalizer: _FakeNormalizer, *, configured: bool = True, dispatcher=None):
    from starlette.applications import Starlette
    from starlette.routing import Route

    dispatcher = dispatcher or _FakeDispatcher()
    core = SimpleNamespace(
        APP_API_KEY="test-key",
        _api_key_is_configured=lambda: configured,
        dispatcher=dispatcher,
        log=Mock(),
    )
    ingress = MediaIngress(core, normalizer=normalizer)

    async def delegate(_text: str) -> bytes:
        raise AssertionError("binary media dispatch must not invoke TTS")

    dispatcher.synthesize = ingress.wrap_synthesize(delegate)
    app = Starlette(
        routes=[Route("/media/announce", ingress.endpoint, methods=["POST"])]
    )
    app.state.media_ingress = ingress
    return app, dispatcher


@pytest.mark.asyncio
async def test_media_route_uses_canonical_dispatcher_with_task_local_audio():
    normalizer = _FakeNormalizer()
    app, dispatcher = _media_app(normalizer)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/media/announce?target=kitchen&repeat_times=2&priority=40",
            content=b"source-audio",
            headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
        )

    assert response.status_code == 200
    assert normalizer.calls == [(b"source-audio", "audio/wav")]
    assert dispatcher.audios == [b"normalized:source-audio"]
    command = dispatcher.commands[0]
    assert command.action == "announce"
    assert command.target == "kitchen"
    assert command.repeat_times == 2
    assert command.priority == 40
    assert command.source == "media_api"
    assert response.json()["media"] == {
        "input_content_type": "audio/wav",
        "normalized_content_type": "audio/mpeg",
        "input_bytes": len(b"source-audio"),
        "normalized_bytes": len(b"normalized:source-audio"),
    }


@pytest.mark.asyncio
async def test_media_payloads_remain_task_local_under_concurrency():
    normalizer = _FakeNormalizer()
    app, dispatcher = _media_app(normalizer)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first, second = await asyncio.gather(
            client.post(
                "/media/announce?target=one",
                content=b"alpha",
                headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
            ),
            client.post(
                "/media/announce?target=two",
                content=b"beta",
                headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
            ),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert {first.json()["test_audio"], second.json()["test_audio"]} == {
        "normalized:alpha",
        "normalized:beta",
    }
    assert set(dispatcher.audios) == {b"normalized:alpha", b"normalized:beta"}


@pytest.mark.asyncio
async def test_media_route_fails_closed_without_api_key():
    app, _dispatcher = _media_app(_FakeNormalizer())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/media/announce",
            content=b"source",
            headers={"Content-Type": "audio/mpeg"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_media_route_rejects_oversized_body_while_streaming():
    app, dispatcher = _media_app(_FakeNormalizer(limit=4))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/media/announce",
            content=b"12345",
            headers={"X-API-Key": "test-key", "Content-Type": "audio/mpeg"},
        )

    assert response.status_code == 413
    assert dispatcher.commands == []


@pytest.mark.parametrize("quiet, expected_status", [(True, 202), (False, 400)])
@pytest.mark.asyncio
async def test_media_policy_or_unknown_target_stops_before_decoding(quiet, expected_status):
    normalizer = _FakeNormalizer()
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(), chime=SimpleNamespace(), ringtone_index=SimpleNamespace(),
        synthesize=AsyncMock(), slug=lambda text: text, resolve_preset=AsyncMock(),
        resolve_targets=lambda target: [], profile=lambda values: values, quiet=lambda: quiet,
        metrics=Mock(), volume_default=50, repeat_default=1,
    )
    app, _ = _media_app(normalizer, dispatcher=dispatcher)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/media/announce?target=unknown", content=b"source",
            headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
        )
    assert response.status_code == expected_status
    assert normalizer.calls == []
    if quiet:
        assert response.json()["media"]["normalized_bytes"] == 0
        assert response.json()["media"]["normalized_content_type"] is None


@pytest.mark.parametrize("disposition", ["deduped", "dropped"])
@pytest.mark.asyncio
async def test_media_preparation_is_lazy_when_dispatcher_declines(disposition):
    """Compatible with the reliability branch's pre-preparation admission gate."""
    normalizer = _FakeNormalizer()
    dispatcher = SimpleNamespace(dispatch=AsyncMock(
        return_value=DispatchResult("announce", disposition)
    ))
    app, _ = _media_app(normalizer, dispatcher=dispatcher)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/media/announce", content=b"source",
            headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
        )
    assert response.json()["disposition"] == disposition
    assert response.json()["media"]["normalized_bytes"] == 0
    assert normalizer.calls == []


@pytest.mark.asyncio
async def test_media_decoder_and_pending_requests_are_bounded_and_cancelled_slots_reused():
    class BlockingNormalizer(_FakeNormalizer):
        def __init__(self):
            super().__init__()
            self.limits = MediaLimits(normalize_concurrency=1, max_pending_requests=2)
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.active = 0
            self.peak = 0

        async def normalize(self, payload, media_type):
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.started.set()
            try:
                await self.release.wait()
                return await super().normalize(payload, media_type)
            finally:
                self.active -= 1

    normalizer = BlockingNormalizer()
    app, _ = _media_app(normalizer)
    ingress = app.state.media_ingress
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        async def post():
            return await client.post(
                "/media/announce", content=b"source",
                headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
            )

        first = asyncio.create_task(post())
        await asyncio.wait_for(normalizer.started.wait(), 1)
        second = asyncio.create_task(post())

        async def wait_for_second_request():
            while ingress._pending_requests < 2:
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_second_request(), 1)
        full = await post()
        assert full.status_code == 429
        assert normalizer.active == normalizer.peak == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        normalizer.release.set()
        assert (await second).status_code == 200
        assert (await post()).status_code == 200
    assert ingress._pending_requests == 0
    assert normalizer.active == 0
    assert normalizer.peak == 1


@pytest.mark.asyncio
async def test_media_request_cancellation_kills_decoder_and_releases_capacity():
    normalizer = AudioMediaNormalizer()
    process = _BlockingProcess()
    app, _ = _media_app(normalizer)
    with patch(
        "app.audio.media_ingest.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            request_task = asyncio.create_task(client.post(
                "/media/announce", content=b"source",
                headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
            ))
            await asyncio.wait_for(process.started.wait(), 1)
            request_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request_task
    assert process.killed
    assert process.communicate_calls == 2
    assert app.state.media_ingress._pending_requests == 0


@pytest.mark.asyncio
async def test_media_preparation_deadline_cancels_work_and_releases_capacity():
    class SlowNormalizer(_FakeNormalizer):
        def __init__(self):
            super().__init__()
            self.limits = MediaLimits(normalize_timeout_seconds=0.01)
            self.cancelled = False

        async def normalize(self, payload, media_type):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    normalizer = SlowNormalizer()
    app, _ = _media_app(normalizer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/media/announce", content=b"source",
            headers={"X-API-Key": "test-key", "Content-Type": "audio/wav"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "media preparation timed out"
    assert normalizer.cancelled
    assert app.state.media_ingress._pending_requests == 0
