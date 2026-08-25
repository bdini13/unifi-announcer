import asyncio
import struct

import pytest

from app.audio.tts import (
    PiperTTS, canonical_cache_key, trim_leading_pcm_silence,
)


def test_cache_key_canonicalizes_text_and_all_audio_dimensions():
    a = canonical_cache_key("  Front   Door ", engine="piper", voice="amy",
                            rate="1.0", sample_rate=22050, encoder_profile="mp3-64k")
    b = canonical_cache_key("front door", engine="piper", voice="amy",
                            rate="1.0", sample_rate=22050, encoder_profile="mp3-64k")
    assert a == b
    assert a != canonical_cache_key("front door", engine="piper", voice="amy",
                                     rate="1.1", sample_rate=22050, encoder_profile="mp3-64k")


def test_trim_leading_silence_keeps_fifteen_ms_preroll():
    rate = 1000
    samples = [0] * 50 + [2000] * 20
    pcm = b"".join(struct.pack("<h", value) for value in samples)
    trimmed, removed_ms = trim_leading_pcm_silence(
        pcm, sample_rate=rate, sample_width=2, channels=1,
        enabled=True, threshold=100, preroll_ms=15,
    )
    assert removed_ms == 35.0
    assert len(trimmed) == 35 * 2
    assert struct.unpack("<h", trimmed[:2])[0] == 0


def test_trim_is_disabled_and_never_removes_all_silence():
    pcm = b"\0\0" * 20
    assert trim_leading_pcm_silence(pcm, sample_rate=1000, sample_width=2,
                                    channels=1, enabled=False)[0] == pcm
    assert trim_leading_pcm_silence(pcm, sample_rate=1000, sample_width=2,
                                    channels=1, enabled=True)[0] == pcm


class FakeSession:
    def __init__(self, outputs, fail=False):
        self.outputs = iter(outputs); self.fail = fail; self.writes = 0; self.closed = 0
    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.closed += 1
    async def write_event(self, event):
        self.writes += 1
        if self.fail: raise ConnectionError("stale")
    async def read_event(self): return next(self.outputs, None)


class Event:
    def __init__(self, type_, payload=None): self.type = type_; self.payload = payload


@pytest.mark.asyncio
async def test_piper_reuses_one_connection_and_serializes_requests():
    session = FakeSession([
        Event("audio-start", {"rate": 1000, "width": 2, "channels": 1}),
        Event("audio-chunk", {"audio": b"a", "rate": 1000, "width": 2, "channels": 1}),
        Event("audio-stop"),
        Event("audio-start", {"rate": 1000, "width": 2, "channels": 1}),
        Event("audio-chunk", {"audio": b"b", "rate": 1000, "width": 2, "channels": 1}),
        Event("audio-stop"),
    ])
    tts = PiperTTS("tcp://piper:10200", client_factory=lambda _: session,
                   event_adapter=_adapter)
    one, two = await asyncio.gather(tts.synthesize_pcm("one"), tts.synthesize_pcm("two"))
    assert one.pcm == b"a" and two.pcm == b"b"
    assert session.writes == 2
    await tts.stop(); assert session.closed == 1


@pytest.mark.asyncio
async def test_piper_reconnects_once_after_stale_connection():
    sessions = iter([FakeSession([], fail=True), FakeSession([
        Event("audio-start", {"rate": 1000, "width": 2, "channels": 1}),
        Event("audio-chunk", {"audio": b"ok", "rate": 1000, "width": 2, "channels": 1}),
        Event("audio-stop"),
    ])])
    tts = PiperTTS("tcp://piper:10200", client_factory=lambda _: next(sessions),
                   event_adapter=_adapter)
    assert (await tts.synthesize_pcm("hello")).pcm == b"ok"
    assert tts.reconnect_count == 1


class HangingSession(FakeSession):
    async def read_event(self):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_piper_timeout_reconnects_once_releases_lock_and_allows_later_request():
    success = FakeSession([
        Event("audio-chunk", {"audio": b"ok", "rate": 1000, "width": 2, "channels": 1}),
        Event("audio-stop"),
    ])
    sessions = iter([HangingSession([]), HangingSession([]), success])
    tts = PiperTTS(
        "tcp://piper:10200", timeout_seconds=0.01,
        client_factory=lambda _: next(sessions), event_adapter=_adapter,
    )

    with pytest.raises(TimeoutError):
        await tts.synthesize_pcm("hang")
    assert tts.reconnect_count == 1
    assert (await tts.synthesize_pcm("later")).pcm == b"ok"


@pytest.mark.asyncio
async def test_piper_timeout_also_bounds_a_hung_connect():
    class HungClient:
        async def __aenter__(self):
            await asyncio.Event().wait()

    tts = PiperTTS("piper:10200", client_factory=lambda uri: HungClient(),
                   timeout_seconds=0.01)

    with pytest.raises(TimeoutError):
        await tts.synthesize_pcm("hello")

    assert tts.reconnect_count == 1


def _adapter(event):
    return event.type, event.payload


def test_mocked_persistent_benchmark_uses_fewer_connections():
    assert PiperTTS.mock_connection_benchmark(10) == {"fresh_connections": 10,
                                                     "persistent_connections": 1}
