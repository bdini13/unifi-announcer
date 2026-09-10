"""Regression coverage for bounded binary-media ingestion."""
from __future__ import annotations

import asyncio
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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_input_bytes": 0},
        {"max_output_bytes": 0},
        {"max_duration_seconds": 0},
        {"max_duration_seconds": float("nan")},
        {"max_duration_seconds": float("inf")},
        {"normalize_timeout_seconds": 0},
        {"normalize_timeout_seconds": float("nan")},
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


class _FakeNormalizer:
    def __init__(self, *, limit: int = 64) -> None:
        self.limits = SimpleNamespace(max_input_bytes=limit)
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
