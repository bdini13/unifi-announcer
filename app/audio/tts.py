"""Native-async TTS connection, canonical caching, and conservative PCM trim."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
import struct
import time
from typing import Any, Callable


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def canonical_cache_key(text: str, *, engine: str, voice: str, rate: str,
                        sample_rate: int, encoder_profile: str) -> str:
    dimensions = {
        "text": normalize_text(text), "engine": engine, "voice": voice,
        "rate": str(rate), "sample_rate": int(sample_rate),
        "encoder_profile": encoder_profile,
    }
    return hashlib.sha256(json.dumps(dimensions, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:24]


def normalized_cache_key(text: str, *, engine: str = "piper", voice: str = "default",
                         rate: str = "1.0", sample_rate: int = 22050,
                         encoder_profile: str = "mp3-mono-64k") -> str:
    """Compatibility name for the now fully dimensional cache key."""
    return canonical_cache_key(text, engine=engine, voice=voice, rate=rate,
                               sample_rate=sample_rate, encoder_profile=encoder_profile)


@dataclass(frozen=True)
class PCMResult:
    pcm: bytes
    sample_rate: int
    sample_width: int
    channels: int
    inference_ms: float


def trim_leading_pcm_silence(pcm: bytes, *, sample_rate: int, sample_width: int,
                             channels: int, enabled: bool, threshold: int = 128,
                             preroll_ms: int = 15) -> tuple[bytes, float]:
    """Trim only leading quiet PCM while retaining 10-20ms context.

    Unsupported sample widths and all-silent inputs are returned unchanged.
    """
    if not enabled or sample_width != 2 or not pcm:
        return pcm, 0.0
    frame_size = sample_width * channels
    frames = len(pcm) // frame_size
    first_loud = None
    for frame in range(frames):
        offset = frame * frame_size
        values = struct.unpack_from("<" + "h" * channels, pcm, offset)
        if any(abs(value) > threshold for value in values):
            first_loud = frame
            break
    if first_loud is None:
        return pcm, 0.0
    keep = int(sample_rate * max(10, min(20, preroll_ms)) / 1000)
    removed_frames = max(0, first_loud - keep)
    return pcm[removed_frames * frame_size:], removed_frames * 1000.0 / sample_rate


class PiperTTS:
    """Lifecycle-owned persistent Wyoming client, serialized until proven safe."""

    def __init__(self, uri: str, *, client_factory: Callable[[str], Any] | None = None,
                 event_adapter: Callable[[Any], tuple[str, dict | None]] | None = None,
                 timeout_seconds: float | None = None) -> None:
        self.uri = self._normalize_uri(uri)
        self._client_factory = client_factory or self._default_factory
        self._event_adapter = event_adapter or self._wyoming_event
        self._client = None
        self._lock = asyncio.Lock()
        self.reconnect_count = 0
        self.timeout_seconds = (float(os.getenv("PIPER_SYNTH_TIMEOUT", "15"))
                                if timeout_seconds is None else timeout_seconds)

    @staticmethod
    def _normalize_uri(uri: str) -> str:
        value = uri.replace("http://", "").replace("https://", "").strip("/")
        return value if value.startswith("tcp://") else f"tcp://{value}"

    @staticmethod
    def _default_factory(uri: str):
        from wyoming.client import AsyncClient
        return AsyncClient.from_uri(uri)

    async def start(self) -> None:
        if self._client is None:
            client = self._client_factory(self.uri)
            self._client = await client.__aenter__()

    async def stop(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            await client.__aexit__(None, None, None)

    async def synthesize_pcm(self, text: str) -> PCMResult:
        async with self._lock:
            for attempt in range(2):
                try:
                    async with asyncio.timeout(self.timeout_seconds):
                        await self.start()
                        return await self._synthesize_once(text)
                except Exception:
                    try:
                        async with asyncio.timeout(self.timeout_seconds):
                            await self.stop()
                    except Exception:
                        self._client = None
                    if attempt:
                        raise
                    self.reconnect_count += 1
            raise RuntimeError("unreachable")

    async def _synthesize_once(self, text: str) -> PCMResult:
        from wyoming.tts import Synthesize
        started = time.perf_counter_ns()
        await self._client.write_event(Synthesize(text=text).event())
        chunks: list[bytes] = []
        metadata = {"rate": 22050, "width": 2, "channels": 1}
        while True:
            event = await self._client.read_event()
            if event is None:
                raise ConnectionError("Wyoming connection closed before audio-stop")
            kind, payload = self._event_adapter(event)
            if payload:
                metadata.update({key: payload[key] for key in metadata if key in payload})
            if kind == "audio-chunk" and payload:
                chunks.append(payload["audio"])
            if kind == "audio-stop":
                break
        return PCMResult(b"".join(chunks), metadata["rate"], metadata["width"],
                         metadata["channels"],
                         (time.perf_counter_ns() - started) / 1_000_000)

    @staticmethod
    def _wyoming_event(event: Any) -> tuple[str, dict | None]:
        from wyoming.audio import AudioChunk, AudioStart, AudioStop
        if AudioStart.is_type(event.type):
            value = AudioStart.from_event(event)
            return "audio-start", {"rate": value.rate, "width": value.width,
                                   "channels": value.channels}
        if AudioChunk.is_type(event.type):
            value = AudioChunk.from_event(event)
            return "audio-chunk", {"audio": value.audio, "rate": value.rate,
                                   "width": value.width, "channels": value.channels}
        if AudioStop.is_type(event.type):
            return "audio-stop", None
        return event.type, None

    @staticmethod
    def mock_connection_benchmark(requests: int) -> dict[str, int]:
        """Deterministic structural benchmark; no network or sound is produced."""
        return {"fresh_connections": requests,
                "persistent_connections": 1 if requests else 0}


class EncodedAudio(bytes):
    """MP3 bytes carrying applicable stage durations."""
    encode_ms: float | None
    tts_ms: float | None
    pcm_ms: float | None

    def __new__(cls, value: bytes, *, encode_ms: float | None = None,
                tts_ms: float | None = None, pcm_ms: float | None = None):
        instance = super().__new__(cls, value)
        instance.encode_ms = encode_ms
        instance.tts_ms = tts_ms
        instance.pcm_ms = pcm_ms
        return instance
