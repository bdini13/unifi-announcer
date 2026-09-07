"""Production hardening for experimental Protect camera speaker targets."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Iterable

from app.playback.camera_talkback import CameraTalkbackError


@dataclass(frozen=True)
class ValidatedCameraProfile:
    model: str
    codec: str
    transport: str
    sample_rate: int
    channels: int
    bits_per_sample: int


# Compatibility is evidence-based, not inferred from a broad AAC capability.
# Add entries only after physical validation on the integrated Announcer path.
VALIDATED_CAMERA_PROFILES = {
    ValidatedCameraProfile(
        model="UVC G3 Instant",
        codec="aac",
        transport="serverudp",
        sample_rate=22050,
        channels=1,
        bits_per_sample=16,
    )
}


def camera_model(camera: dict[str, Any]) -> str:
    return str(camera.get("type") or camera.get("modelKey") or "").strip()


def validate_camera_profile(camera: dict[str, Any]) -> ValidatedCameraProfile:
    """Require an exact physically validated camera/model/talkback profile."""
    if str(camera.get("state") or "").upper() != "CONNECTED":
        raise CameraTalkbackError("camera is not connected")
    flags = camera.get("featureFlags")
    if not isinstance(flags, dict) or flags.get("hasSpeaker") is not True:
        raise CameraTalkbackError("camera has no speaker")
    settings = camera.get("talkbackSettings")
    if not isinstance(settings, dict):
        raise CameraTalkbackError("camera is missing talkback settings")

    try:
        sample_rate = int(settings.get("samplingRate") or 0)
        channels = int(settings.get("channels") or 0)
        bits_per_sample = int(settings.get("bitsPerSample") or 0)
    except (TypeError, ValueError):
        raise CameraTalkbackError("camera has invalid talkback settings") from None

    observed = ValidatedCameraProfile(
        model=camera_model(camera),
        codec=str(settings.get("typeFmt") or "").lower(),
        transport=str(settings.get("typeIn") or "").lower(),
        sample_rate=sample_rate,
        channels=channels,
        bits_per_sample=bits_per_sample,
    )
    if observed not in VALIDATED_CAMERA_PROFILES:
        raise CameraTalkbackError(
            "camera model/talkback profile has not been physically validated"
        )
    return observed


def load_validated_groups(
    raw: str,
    *,
    target_names: Iterable[str],
) -> dict[str, list[str]]:
    """Parse GROUPS_CONFIG and reject unknown/ambiguous members fail-closed."""
    try:
        payload = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("GROUPS_CONFIG must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GROUPS_CONFIG must be a JSON object")

    known = {str(name) for name in target_names}
    groups: dict[str, list[str]] = {}
    for raw_name, raw_members in payload.items():
        name = str(raw_name).strip()
        if not name or name == "default" or name in known or name in groups:
            raise RuntimeError(f"duplicate or reserved group name: {name or '<empty>'}")
        if not isinstance(raw_members, list) or not raw_members:
            raise RuntimeError(f"group {name} must contain at least one target")
        members = [str(member).strip() for member in raw_members]
        if any(not member for member in members):
            raise RuntimeError(f"group {name} contains an empty target name")
        if len(set(members)) != len(members):
            raise RuntimeError(f"group {name} contains duplicate target members")
        unknown = [member for member in members if member not in known]
        if unknown:
            raise RuntimeError(
                f"group {name} references unknown target: {unknown[0]}"
            )
        groups[name] = members
    return groups


class _LockedPreparedCameraTalkback:
    """Hold a per-camera preparation lease until playback/session close."""

    def __init__(self, prepared: Any, lock: asyncio.Lock) -> None:
        self._prepared = prepared
        self._lock = lock
        self._released = False

    def _release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._lock.locked():
            self._lock.release()

    async def play(self) -> dict[str, Any]:
        try:
            return await self._prepared.play()
        finally:
            self._release()

    async def close(self) -> None:
        try:
            await self._prepared.close()
        finally:
            self._release()


class HardenedCameraTalkback:
    """Evidence-gated, single-session-per-camera wrapper around talkback."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self._locks: dict[str, asyncio.Lock] = {}

    async def _validated_camera(
        self, camera_id: str
    ) -> tuple[dict[str, Any], ValidatedCameraProfile]:
        camera = await self.delegate._camera(camera_id)
        return camera, validate_camera_profile(camera)

    async def inspect(self, camera_id: str) -> dict[str, Any]:
        try:
            camera, profile = await self._validated_camera(camera_id)
        except CameraTalkbackError as exc:
            model = "camera"
            try:
                raw = await self.delegate._camera(camera_id)
                model = camera_model(raw) or "camera"
            except Exception:
                pass
            return {
                "status": "unavailable",
                "error": str(exc),
                "model": model,
            }
        return {
            "status": "available",
            "name": str(camera.get("name") or "camera"),
            "codec": profile.codec,
            "sample_rate": profile.sample_rate,
            "channels": profile.channels,
            "transport": "private_websocket",
            "model": profile.model,
            "compatibility": "physically_validated",
        }

    async def prepare(
        self,
        camera_id: str,
        mp3: bytes,
        *,
        repeat_times: int = 1,
    ) -> _LockedPreparedCameraTalkback:
        lock = self._locks.setdefault(camera_id, asyncio.Lock())
        await lock.acquire()
        try:
            await self._validated_camera(camera_id)
            prepared = await self.delegate.prepare(
                camera_id,
                mp3,
                repeat_times=repeat_times,
            )
            return _LockedPreparedCameraTalkback(prepared, lock)
        except BaseException:
            if lock.locked():
                lock.release()
            raise

    async def play(
        self,
        camera_id: str,
        mp3: bytes,
        *,
        repeat_times: int = 1,
    ) -> dict[str, Any]:
        prepared = await self.prepare(
            camera_id,
            mp3,
            repeat_times=repeat_times,
        )
        return await prepared.play()
