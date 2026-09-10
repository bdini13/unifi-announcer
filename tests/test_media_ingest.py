"""Regression coverage for bounded binary-media ingestion."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

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
async def test_media_normalizer_converts_valid_audio_to_bounded_mp3():
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
    ffmpeg = calls[1]
    assert ("-ac", "1") == ffmpeg[ffmpeg.index("-ac"):ffmpeg.index("-ac") + 2]
    assert ("-ar", "22050") == ffmpeg[ffmpeg.index("-ar"):ffmpeg.index("-ar") + 2]
    assert "libmp3lame" in ffmpeg


class _FakeNormalizer:
    def __init__(self, *, limit: int = 64) -> None:
        self.limits = SimpleNamespace(max_input_bytes=limit)
        self.calls: list[tuple[bytes, str]] = []

    async def normalize(self, payload: bytes, media_type: str) -> bytes:
        self.calls.append((payload, media_type))
        return b"normalized"


class _FakeDispatcher:
    def __init__(self) -> None:
        self.synthesize = None
        self.command = None
        self.audio = None

    async def dispatch(self, command):
        self.command = command
        self.audio = await self.synthesize(command.text)
        return SimpleNamespace(
            disposition="played",
            response=lambda: {"disposition": "played", "targets": 1},
        )


def _media_app(normalizer: _FakeNormalizer, *, configured: bool = True):
    from starlette.applications import Starlette
    from starlette.routing import Route

    dispatcher = _FakeDispatcher()
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
    return Starlette(
        routes=[Route("/media/announce", ingress.endpoint, methods=["POST"])]
    ), dispatcher


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
    assert dispatcher.audio == b"normalized"
    assert dispatcher.command.action == "announce"
    assert dispatcher.command.target == "kitchen"
    assert dispatcher.command.repeat_times == 2
    assert dispatcher.command.priority == 40
    assert dispatcher.command.source == "media_api"
    assert response.json()["media"] == {
        "input_content_type": "audio/wav",
        "normalized_content_type": "audio/mpeg",
        "input_bytes": len(b"source-audio"),
        "normalized_bytes": len(b"normalized"),
    }


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
    assert dispatcher.command is None
