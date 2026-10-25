"""Silent, network-free smoke check for the codecs in the built runtime image.

Run from the repository root with ``python -m scripts.smoke_media_codec``, or
feed this file to the image's Python stdin. Requires actual ffprobe and ffmpeg.
"""
from __future__ import annotations

import asyncio
import io
import json
import tempfile
import wave
from pathlib import Path

from app.audio.media_ingest import AudioMediaNormalizer


async def main() -> None:
    source = io.BytesIO()
    with wave.open(source, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\0\0\0\0" * 11025)

    normalizer = AudioMediaNormalizer()
    mp3 = await normalizer.normalize(source.getvalue(), "audio/wav")
    with tempfile.TemporaryDirectory(prefix="ua-codec-smoke-") as folder:
        destination = Path(folder) / "normalized.mp3"
        destination.write_bytes(mp3)
        output = await normalizer._run(
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
            "-of", "json", str(destination),
        )
    metadata = json.loads(output)
    stream = metadata["streams"][0]
    assert stream["codec_name"] == "mp3", stream
    assert int(stream["sample_rate"]) == 22050, stream
    assert stream["channels"] == 1, stream
    assert 0.20 <= float(metadata["format"]["duration"]) <= 0.5, metadata
    assert 0 < len(mp3) <= normalizer.limits.max_output_bytes
    print(f"Codec smoke passed: silent WAV -> mono 22050 Hz MP3 ({len(mp3)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
