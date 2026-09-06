"""Fail-closed Protect camera talkback playback.

The controller-minted talkback WebSocket is undocumented. This module supports
only the physically verified AAC/ADTS profile and never logs or returns signed
session URLs, cookies, camera addresses, or authentication material.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import ssl
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import websockets


class CameraTalkbackError(RuntimeError):
    """Camera talkback is unavailable or failed without exposing secrets."""


@dataclass(frozen=True)
class CameraTalkbackProfile:
    camera_id: str
    name: str
    sample_rate: int
    channels: int
    bits_per_sample: int
    codec: str = "aac"
    transport: str = "serverudp"

    @classmethod
    def from_camera(cls, camera: dict[str, Any]) -> "CameraTalkbackProfile":
        camera_id = str(camera.get("id") or "").strip()
        if not camera_id:
            raise CameraTalkbackError("camera identity is missing")
        if str(camera.get("state") or "").upper() != "CONNECTED":
            raise CameraTalkbackError("camera is not connected")
        flags = camera.get("featureFlags")
        if not isinstance(flags, dict) or flags.get("hasSpeaker") is not True:
            raise CameraTalkbackError("camera has no speaker")
        settings = camera.get("talkbackSettings")
        if not isinstance(settings, dict):
            raise CameraTalkbackError("camera is missing talkback settings")

        codec = str(settings.get("typeFmt") or "").lower()
        transport = str(settings.get("typeIn") or "").lower()
        sample_rate = settings.get("samplingRate")
        channels = settings.get("channels")
        bits = settings.get("bitsPerSample")
        adts_rates = {
            7350, 8000, 11025, 12000, 16000, 22050,
            24000, 32000, 44100, 48000, 64000, 88200, 96000,
        }
        if (
            codec != "aac"
            or transport != "serverudp"
            or sample_rate not in adts_rates
            or channels != 1
            or bits != 16
        ):
            raise CameraTalkbackError("camera has an unsupported talkback profile")
        return cls(
            camera_id=camera_id,
            name=str(camera.get("name") or "camera"),
            sample_rate=int(sample_rate),
            channels=int(channels),
            bits_per_sample=int(bits),
            codec=codec,
            transport=transport,
        )


def split_adts_frames(
    data: bytes,
    *,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> list[bytes]:
    """Split and validate a complete AAC-LC ADTS stream."""
    if not data:
        raise CameraTalkbackError("invalid ADTS stream")
    sample_rates = (
        96000, 88200, 64000, 48000, 44100, 32000, 24000,
        22050, 16000, 12000, 11025, 8000, 7350,
    )
    frames: list[bytes] = []
    offset = 0
    while offset < len(data):
        remaining = len(data) - offset
        if remaining < 7 or data[offset] != 0xFF or data[offset + 1] & 0xF6 != 0xF0:
            raise CameraTalkbackError("invalid ADTS stream")
        profile = (data[offset + 2] >> 6) & 0x03
        frequency_index = (data[offset + 2] >> 2) & 0x0F
        channel_config = (
            ((data[offset + 2] & 0x01) << 2)
            | ((data[offset + 3] >> 6) & 0x03)
        )
        if profile != 1:
            raise CameraTalkbackError("ADTS output is not AAC-LC")
        if frequency_index >= len(sample_rates):
            raise CameraTalkbackError("ADTS output has an invalid sample rate")
        if sample_rate is not None and sample_rates[frequency_index] != sample_rate:
            raise CameraTalkbackError("ADTS output sample rate does not match camera")
        if channels is not None and channel_config != channels:
            raise CameraTalkbackError("ADTS output channel count does not match camera")
        if data[offset + 6] & 0x03:
            raise CameraTalkbackError("ADTS frame has multiple raw data blocks")
        header_length = 7 if data[offset + 1] & 0x01 else 9
        frame_length = (
            ((data[offset + 3] & 0x03) << 11)
            | (data[offset + 4] << 3)
            | ((data[offset + 5] & 0xE0) >> 5)
        )
        if frame_length < header_length:
            raise CameraTalkbackError("invalid ADTS frame length")
        end = offset + frame_length
        if end > len(data):
            raise CameraTalkbackError("truncated ADTS frame")
        frames.append(data[offset:end])
        offset = end
    return frames


def confine_talkback_url(minted_url: str | None, controller_url: str) -> str:
    """Keep a controller-minted path/token but force the configured controller host."""
    if not isinstance(minted_url, str):
        raise CameraTalkbackError("invalid talkback URL returned by controller")
    try:
        minted = urlsplit(minted_url)
        controller = urlsplit(controller_url)
        expected_scheme = "wss" if controller.scheme == "https" else "ws"
        if (
            minted.scheme != expected_scheme
            or not minted.hostname
            or minted.username is not None
            or minted.password is not None
            or minted.path != "/ws/talkback"
            or not minted.query
            or minted.fragment
            or not controller.hostname
            or controller.scheme not in {"http", "https"}
            or controller.username is not None
            or controller.password is not None
            or minted.port != 7443
        ):
            raise ValueError
        port = minted.port
    except (TypeError, ValueError):
        raise CameraTalkbackError("invalid talkback URL returned by controller") from None

    host = controller.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((expected_scheme, netloc, minted.path, minted.query, ""))


async def transcode_mp3_to_adts(
    mp3: bytes,
    *,
    sample_rate: int,
    channels: int,
    timeout_seconds: float = 15.0,
    max_input_bytes: int = 1024 * 1024,
    max_output_bytes: int = 4 * 1024 * 1024,
    process_factory: Callable[..., Awaitable[Any]] = asyncio.create_subprocess_exec,
) -> bytes:
    """Convert MP3 to AAC-LC ADTS with live output and process bounds."""
    if not mp3 or len(mp3) > max_input_bytes:
        raise CameraTalkbackError("camera talkback audio input is empty or too large")

    process = None
    feeder: asyncio.Task | None = None
    try:
        process = await process_factory(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "mp3", "-i", "pipe:0", "-vn",
            "-c:a", "aac", "-profile:a", "aac_low",
            "-ar", str(sample_rate), "-ac", str(channels),
            "-f", "adts", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if process.stdin is None or process.stdout is None:
            raise CameraTalkbackError("camera talkback audio conversion failed")

        async def feed_input() -> None:
            try:
                process.stdin.write(mp3)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        feeder = asyncio.create_task(feed_input())
        output = bytearray()
        async with asyncio.timeout(timeout_seconds):
            while True:
                chunk = await process.stdout.read(65536)
                if not chunk:
                    break
                if len(output) + len(chunk) > max_output_bytes:
                    raise CameraTalkbackError(
                        "camera talkback encoded audio is empty or too large"
                    )
                output.extend(chunk)
            await feeder
            return_code = await process.wait()
        if return_code != 0 or not output:
            raise CameraTalkbackError("camera talkback audio conversion failed")
        return bytes(output)
    except asyncio.CancelledError:
        raise
    except CameraTalkbackError:
        raise
    except (OSError, TimeoutError):
        raise CameraTalkbackError("camera talkback audio conversion failed") from None
    finally:
        if feeder is not None and not feeder.done():
            feeder.cancel()
            await asyncio.gather(feeder, return_exceptions=True)
        if process is not None and process.stdin is not None:
            process.stdin.close()
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


class PreparedCameraTalkback:
    """One pre-opened, armed, single-use camera talkback session."""

    def __init__(
        self,
        *,
        connection: Any,
        websocket: Any,
        profile: CameraTalkbackProfile,
        frames: list[bytes],
        repeat_times: int,
        sleep: Callable[[float], Awaitable[None]],
        drain_delay: float,
        deadline: float,
    ) -> None:
        self.connection = connection
        self.websocket = websocket
        self.profile = profile
        self.frames = frames
        self.repeat_times = repeat_times
        self.sleep = sleep
        self.drain_delay = drain_delay
        self.deadline = deadline
        self.used = False
        self.closed = False

    async def play(self) -> dict[str, Any]:
        if self.used:
            raise CameraTalkbackError("camera talkback session is single-use")
        self.used = True
        sent = 0
        try:
            remaining = self.deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise CameraTalkbackError("camera talkback operation timed out")
            async with asyncio.timeout(remaining):
                frame_period = 1024 / self.profile.sample_rate
                for _ in range(self.repeat_times):
                    for frame in self.frames:
                        await self.websocket.send(frame)
                        sent += 1
                        await self.sleep(frame_period)
                await self.sleep(self.drain_delay)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise CameraTalkbackError("camera talkback operation timed out") from None
        except CameraTalkbackError:
            raise
        except Exception:
            raise CameraTalkbackError("camera talkback transport failed") from None
        finally:
            await self.close()
        return {
            "played": True,
            "target_type": "camera",
            "codec": self.profile.codec,
            "sample_rate": self.profile.sample_rate,
            "frames": sent,
            "repeat_times": self.repeat_times,
            "volume_control": "device",
        }

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.connection.__aexit__(None, None, None)
        except Exception:
            pass


class ProtectCameraTalkback:
    """Revalidate, negotiate, encode, pace, and close one camera talkback session."""

    def __init__(
        self,
        *,
        protect: Any,
        controller_url: str,
        verify_ssl: bool,
        transcode: Callable[..., Awaitable[bytes]] = transcode_mp3_to_adts,
        connector: Callable[..., Any] = websockets.connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        arm_delay: float = 0.4,
        drain_delay: float = 0.5,
        session_timeout: float = 30.0,
        scheduling_margin: float = 0.02,
    ) -> None:
        self.protect = protect
        self.controller_url = controller_url
        self.verify_ssl = verify_ssl
        self.transcode = transcode
        self.connector = connector
        self.sleep = sleep
        self.arm_delay = arm_delay
        self.drain_delay = drain_delay
        self.session_timeout = session_timeout
        self.scheduling_margin = scheduling_margin

    async def inspect(self, camera_id: str) -> dict[str, Any]:
        """Return sanitized capability state for one explicitly configured camera."""
        camera = await self._camera(camera_id)
        try:
            profile = CameraTalkbackProfile.from_camera(camera)
        except CameraTalkbackError as exc:
            return {
                "status": "unavailable",
                "error": str(exc),
                "name": str(camera.get("name") or "camera"),
            }
        return {
            "status": "available",
            "name": profile.name,
            "codec": profile.codec,
            "sample_rate": profile.sample_rate,
            "channels": profile.channels,
            "transport": "private_websocket",
            "model": str(camera.get("type") or camera.get("modelKey") or "camera"),
        }

    async def play(
        self,
        camera_id: str,
        mp3: bytes,
        *,
        repeat_times: int = 1,
    ) -> dict[str, Any]:
        prepared = await self.prepare(camera_id, mp3, repeat_times=repeat_times)
        return await prepared.play()

    async def prepare(
        self,
        camera_id: str,
        mp3: bytes,
        *,
        repeat_times: int = 1,
    ) -> PreparedCameraTalkback:
        """Revalidate and arm a session without sending an audio frame."""
        deadline = asyncio.get_running_loop().time() + self.session_timeout
        try:
            async with asyncio.timeout(self.session_timeout):
                return await self._prepare(
                    camera_id, mp3, repeat_times=repeat_times, deadline=deadline
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise CameraTalkbackError("camera talkback operation timed out") from None

    async def _prepare(
        self,
        camera_id: str,
        mp3: bytes,
        *,
        repeat_times: int,
        deadline: float,
    ) -> PreparedCameraTalkback:
        if not 1 <= repeat_times <= 6:
            raise CameraTalkbackError("camera talkback repeat_times must be 1..6")
        camera = await self._camera(camera_id)
        profile = CameraTalkbackProfile.from_camera(camera)
        encoded = await self.transcode(
            mp3, sample_rate=profile.sample_rate, channels=profile.channels
        )
        frames = split_adts_frames(
            encoded,
            sample_rate=profile.sample_rate,
            channels=profile.channels,
        )
        transport_duration = (
            self.arm_delay
            + self.drain_delay
            + (len(frames) * repeat_times * 1024 / profile.sample_rate)
        )
        remaining = deadline - asyncio.get_running_loop().time()
        if transport_duration + self.scheduling_margin >= remaining:
            raise CameraTalkbackError("camera talkback duration exceeds session budget")

        response = await self.protect._do(
            "GET",
            "/proxy/protect/api/ws/talkback",
            params={"camera": camera_id},
        )
        if response.status_code != 200:
            raise CameraTalkbackError("camera talkback negotiation failed")
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = None
        if not isinstance(payload, dict):
            raise CameraTalkbackError("invalid camera talkback negotiation response")
        url = confine_talkback_url(payload.get("url"), self.controller_url)
        cookie = self.protect.session_cookie_header()
        if inspect.isawaitable(cookie):
            cookie = await cookie
        if not isinstance(cookie, str) or not cookie:
            raise CameraTalkbackError("camera talkback session authentication is unavailable")

        ssl_context = ssl.create_default_context()
        if not self.verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        headers_key = (
            "additional_headers"
            if int(websockets.__version__.split(".")[0]) >= 14
            else "extra_headers"
        )
        origin_parts = urlsplit(self.controller_url)
        origin = urlunsplit((origin_parts.scheme, origin_parts.netloc, "", "", ""))
        kwargs = {
            "ssl": ssl_context,
            "open_timeout": min(10.0, self.session_timeout),
            "compression": None,
            "origin": origin,
            headers_key: {"Cookie": cookie},
        }

        connection = None
        try:
            connection = self.connector(url, **kwargs)
            if inspect.isawaitable(connection) and not hasattr(
                connection, "__aenter__"
            ):
                connection = await connection
            websocket = await connection.__aenter__()
            prepared = PreparedCameraTalkback(
                connection=connection,
                websocket=websocket,
                profile=profile,
                frames=frames,
                repeat_times=repeat_times,
                sleep=self.sleep,
                drain_delay=self.drain_delay,
                deadline=deadline,
            )
            try:
                await self.sleep(self.arm_delay)
            except BaseException:
                await prepared.close()
                raise
            return prepared
        except asyncio.CancelledError:
            raise
        except CameraTalkbackError:
            raise
        except Exception:
            if connection is not None and hasattr(connection, "__aexit__"):
                try:
                    await connection.__aexit__(None, None, None)
                except Exception:
                    pass
            raise CameraTalkbackError("camera talkback transport failed") from None

    async def _camera(self, camera_id: str) -> dict[str, Any]:
        bootstrap = await self.protect.bootstrap()
        cameras = bootstrap.get("cameras") if isinstance(bootstrap, dict) else None
        if not isinstance(cameras, list):
            raise CameraTalkbackError("Protect bootstrap camera inventory is unavailable")
        camera = next(
            (
                item
                for item in cameras
                if isinstance(item, dict) and str(item.get("id") or "") == camera_id
            ),
            None,
        )
        if camera is None:
            raise CameraTalkbackError("configured camera is unavailable")
        return camera
