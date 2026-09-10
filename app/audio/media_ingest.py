"""Bounded binary-audio validation and normalization for media ingestion."""
from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.audio.tts import EncodedAudio


SUPPORTED_MEDIA_TYPES = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
    "audio/x-wav": ".wav",
}


class MediaIngestError(ValueError):
    """Base error for rejected media input."""


class UnsupportedMediaType(MediaIngestError):
    """The declared MIME type is outside the bounded audio contract."""


class MediaTooLarge(MediaIngestError):
    """The media payload exceeds an input or normalized-output limit."""


class InvalidMedia(MediaIngestError):
    """The payload is not decodable bounded audio."""


@dataclass(frozen=True)
class MediaLimits:
    """Limits applied before media reaches a Protect playback backend."""

    max_input_bytes: int = 4 * 1024 * 1024
    max_output_bytes: int = 1024 * 1024
    max_duration_seconds: float = 30.0
    normalize_timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "MediaLimits":
        return cls(
            max_input_bytes=int(os.getenv("MEDIA_MAX_INPUT_BYTES", str(4 * 1024 * 1024))),
            max_output_bytes=int(os.getenv("MAX_MP3_BYTES", str(1024 * 1024))),
            max_duration_seconds=float(os.getenv("MEDIA_MAX_DURATION_SECONDS", "30")),
            normalize_timeout_seconds=float(
                os.getenv("MEDIA_NORMALIZE_TIMEOUT_SECONDS", "15")
            ),
        )


def canonical_media_type(value: str) -> str:
    """Return a parameter-free lower-case MIME type."""
    return value.partition(";")[0].strip().lower()


class AudioMediaNormalizer:
    """Normalize common bounded audio inputs to the production MP3 contract."""

    def __init__(self, limits: MediaLimits | None = None) -> None:
        self.limits = limits or MediaLimits.from_env()

    async def normalize(self, payload: bytes, media_type: str) -> EncodedAudio:
        canonical = canonical_media_type(media_type)
        suffix = SUPPORTED_MEDIA_TYPES.get(canonical)
        if suffix is None:
            raise UnsupportedMediaType(f"unsupported audio content type: {canonical or 'missing'}")
        if not payload:
            raise InvalidMedia("media payload cannot be empty")
        if len(payload) > self.limits.max_input_bytes:
            raise MediaTooLarge(
                f"media payload exceeds {self.limits.max_input_bytes} byte input limit"
            )

        descriptor, raw_path = tempfile.mkstemp(prefix="ua-media-", suffix=suffix)
        os.close(descriptor)
        path = Path(raw_path)
        try:
            await asyncio.to_thread(path.write_bytes, payload)
            duration = await self._probe_duration(path)
            if duration <= 0 or not math.isfinite(duration):
                raise InvalidMedia("media duration is invalid")
            if duration > self.limits.max_duration_seconds:
                raise InvalidMedia(
                    "media duration exceeds "
                    f"{self.limits.max_duration_seconds:g} second limit"
                )

            started = time.perf_counter_ns()
            normalized = await self._run(
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "22050",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "64k",
                "-f",
                "mp3",
                "pipe:1",
            )
            encode_ms = (time.perf_counter_ns() - started) / 1_000_000
            if not normalized:
                raise InvalidMedia("media normalization produced no audio")
            if len(normalized) > self.limits.max_output_bytes:
                raise MediaTooLarge(
                    "normalized media exceeds "
                    f"{self.limits.max_output_bytes} byte output limit"
                )
            return EncodedAudio(normalized, encode_ms=encode_ms)
        finally:
            await asyncio.to_thread(path.unlink, missing_ok=True)

    async def _probe_duration(self, path: Path) -> float:
        output = await self._run(
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type,duration:format=duration",
            "-of",
            "json",
            str(path),
        )
        try:
            document = json.loads(output.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidMedia("media probe returned invalid metadata") from exc

        streams = document.get("streams") if isinstance(document, dict) else None
        if not isinstance(streams, list) or not any(
            isinstance(stream, dict) and stream.get("codec_type") == "audio"
            for stream in streams
        ):
            raise InvalidMedia("media payload does not contain an audio stream")

        candidates = []
        format_block = document.get("format") if isinstance(document, dict) else None
        if isinstance(format_block, dict):
            candidates.append(format_block.get("duration"))
        candidates.extend(
            stream.get("duration") for stream in streams if isinstance(stream, dict)
        )
        for candidate in candidates:
            try:
                duration = float(candidate)
            except (TypeError, ValueError):
                continue
            if math.isfinite(duration):
                return duration
        raise InvalidMedia("media duration could not be determined")

    async def _run(self, *command: str) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise InvalidMedia("ffmpeg media tools are unavailable") from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.limits.normalize_timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise InvalidMedia("media normalization timed out") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
            summary = detail[-1][:160] if detail else "decoder rejected input"
            raise InvalidMedia(f"media could not be decoded: {summary}")
        return stdout
