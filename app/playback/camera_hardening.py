"""Production hardening for experimental Protect camera speaker targets."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, cast, Iterable

from app.playback.camera_talkback import CameraTalkbackError


@dataclass(frozen=True)
class CameraProtocolProfile:
    """Exact wire profile that may be enabled only through explicit opt-in."""

    codec: str
    transport: str
    sample_rate: int
    channels: int
    bits_per_sample: int


@dataclass(frozen=True)
class ValidatedCameraProfile:
    model: str
    codec: str
    transport: str
    sample_rate: int
    channels: int
    bits_per_sample: int

    @property
    def protocol_profile(self) -> CameraProtocolProfile:
        return CameraProtocolProfile(
            codec=self.codec,
            transport=self.transport,
            sample_rate=self.sample_rate,
            channels=self.channels,
            bits_per_sample=self.bits_per_sample,
        )


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

_EXPERIMENTAL_PROFILE_KEYS = {
    "codec",
    "transport",
    "sample_rate",
    "channels",
    "bits_per_sample",
}
_ADTS_SAMPLE_RATES = {
    7350, 8000, 11025, 12000, 16000, 22050,
    24000, 32000, 44100, 48000, 64000, 88200, 96000,
}


def load_experimental_camera_profiles(raw: str) -> frozenset[CameraProtocolProfile]:
    """Parse an exact, empty-by-default protocol opt-in allowlist."""
    if not str(raw or "").strip():
        return frozenset()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("EXPERIMENTAL_CAMERA_PROFILES must be a JSON list") from exc
    if not isinstance(payload, list):
        raise RuntimeError("EXPERIMENTAL_CAMERA_PROFILES must be a JSON list")

    profiles: set[CameraProtocolProfile] = set()
    for entry in payload:
        if not isinstance(entry, dict) or set(entry) != _EXPERIMENTAL_PROFILE_KEYS:
            raise RuntimeError(
                "EXPERIMENTAL_CAMERA_PROFILES entries require exactly codec, "
                "transport, sample_rate, channels, and bits_per_sample"
            )
        if (
            not isinstance(entry["codec"], str)
            or not isinstance(entry["transport"], str)
            or any(
                type(entry[key]) is not int
                for key in ("sample_rate", "channels", "bits_per_sample")
            )
        ):
            raise RuntimeError(
                "EXPERIMENTAL_CAMERA_PROFILES contains invalid value types"
            )
        try:
            profile = CameraProtocolProfile(
                codec=str(entry["codec"]).strip().lower(),
                transport=str(entry["transport"]).strip().lower(),
                sample_rate=int(entry["sample_rate"]),
                channels=int(entry["channels"]),
                bits_per_sample=int(entry["bits_per_sample"]),
            )
        except (TypeError, ValueError):
            raise RuntimeError(
                "EXPERIMENTAL_CAMERA_PROFILES contains invalid values"
            ) from None
        if (
            profile.codec != "aac"
            or profile.transport != "serverudp"
            or profile.sample_rate not in _ADTS_SAMPLE_RATES
            or profile.channels != 1
            or profile.bits_per_sample != 16
        ):
            raise RuntimeError(
                "EXPERIMENTAL_CAMERA_PROFILES contains an unsupported profile"
            )
        if profile in profiles:
            raise RuntimeError(
                "EXPERIMENTAL_CAMERA_PROFILES contains a duplicate profile"
            )
        profiles.add(profile)
    return frozenset(profiles)


def camera_model(camera: dict[str, Any]) -> str:
    return str(camera.get("type") or camera.get("modelKey") or "").strip()


def validate_camera_profile(
    camera: dict[str, Any],
    *,
    experimental_profiles: frozenset[CameraProtocolProfile] = frozenset(),
) -> ValidatedCameraProfile:
    """Require validated model evidence or an exact experimental opt-in."""
    if str(camera.get("state") or "").upper() != "CONNECTED":
        raise CameraTalkbackError("camera is not connected")
    flags = camera.get("featureFlags")
    if not isinstance(flags, dict) or flags.get("hasSpeaker") is not True:
        raise CameraTalkbackError("camera has no speaker")
    settings = camera.get("talkbackSettings")
    if not isinstance(settings, dict):
        raise CameraTalkbackError("camera is missing talkback settings")

    sample_rate = settings.get("samplingRate")
    channels = settings.get("channels")
    bits_per_sample = settings.get("bitsPerSample")
    if any(
        type(value) is not int
        for value in (sample_rate, channels, bits_per_sample)
    ):
        raise CameraTalkbackError("camera has invalid talkback settings") from None
    sample_rate = cast(int, sample_rate)
    channels = cast(int, channels)
    bits_per_sample = cast(int, bits_per_sample)

    observed = ValidatedCameraProfile(
        model=camera_model(camera),
        codec=str(settings.get("typeFmt") or "").lower(),
        transport=str(settings.get("typeIn") or "").lower(),
        sample_rate=sample_rate,
        channels=channels,
        bits_per_sample=bits_per_sample,
    )
    if (
        observed not in VALIDATED_CAMERA_PROFILES
        and observed.protocol_profile not in experimental_profiles
    ):
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

    def __init__(
        self,
        delegate: Any,
        *,
        experimental_profiles: frozenset[CameraProtocolProfile] = frozenset(),
    ) -> None:
        self.delegate = delegate
        self.experimental_profiles = experimental_profiles
        self._locks: dict[str, asyncio.Lock] = {}

    async def _validated_camera(
        self, camera_id: str
    ) -> tuple[dict[str, Any], ValidatedCameraProfile]:
        camera = await self.delegate._camera(camera_id)
        return camera, validate_camera_profile(
            camera,
            experimental_profiles=self.experimental_profiles,
        )

    async def inspect(self, camera_id: str) -> dict[str, Any]:
        try:
            camera = await self.delegate._camera(camera_id)
        except CameraTalkbackError as exc:
            return {
                "status": "unavailable",
                "error": str(exc),
                "model": "camera",
            }
        try:
            profile = validate_camera_profile(
                camera,
                experimental_profiles=self.experimental_profiles,
            )
        except CameraTalkbackError as exc:
            return {
                "status": "unavailable",
                "error": str(exc),
                "model": camera_model(camera) or "camera",
            }
        return {
            "status": "available",
            "name": str(camera.get("name") or "camera"),
            "codec": profile.codec,
            "sample_rate": profile.sample_rate,
            "channels": profile.channels,
            "transport": "private_websocket",
            "model": profile.model,
            "compatibility": (
                "physically_validated"
                if profile in VALIDATED_CAMERA_PROFILES
                else "experimental_opt_in"
            ),
        }

    @staticmethod
    def _prepared_profile_matches(
        prepared: Any,
        expected: ValidatedCameraProfile,
    ) -> bool:
        """Confirm the low-level session was actually built for the approved profile."""
        profile = getattr(prepared, "profile", None)
        if profile is None:
            return False
        sample_rate = getattr(profile, "sample_rate", None)
        channels = getattr(profile, "channels", None)
        bits_per_sample = getattr(profile, "bits_per_sample", None)
        if any(
            type(value) is not int
            for value in (sample_rate, channels, bits_per_sample)
        ):
            return False
        return (
            str(getattr(profile, "codec", "")).lower() == expected.codec
            and str(getattr(profile, "transport", "")).lower() == expected.transport
            and sample_rate == expected.sample_rate
            and channels == expected.channels
            and bits_per_sample == expected.bits_per_sample
        )

    async def prepare(
        self,
        camera_id: str,
        mp3: bytes,
        *,
        repeat_times: int = 1,
    ) -> _LockedPreparedCameraTalkback:
        lock = self._locks.setdefault(camera_id, asyncio.Lock())
        await lock.acquire()
        prepared = None
        try:
            _, expected = await self._validated_camera(camera_id)
            prepared = await self.delegate.prepare(
                camera_id,
                mp3,
                repeat_times=repeat_times,
            )
            if not self._prepared_profile_matches(prepared, expected):
                await prepared.close()
                raise CameraTalkbackError(
                    "prepared camera talkback profile changed before playback"
                )
            _, current = await self._validated_camera(camera_id)
            if current != expected:
                await prepared.close()
                raise CameraTalkbackError(
                    "camera model/talkback profile changed during preparation"
                )
            return _LockedPreparedCameraTalkback(prepared, lock)
        except BaseException:
            if prepared is not None and not getattr(prepared, "closed", False):
                try:
                    await prepared.close()
                except Exception:
                    pass
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
