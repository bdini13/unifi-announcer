"""Fixed, service-owned dynamic TTS slots for Smart Chime playback.

The public playback invariant is intentionally simple: arbitrary TTS may consume
exactly two persistent Protect ringtone identities per UniFi Announcer
installation. Message audio is overwritten into the already-proven physical
Smart Chime slots; new speech never creates a new Protect ringtone object.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Awaitable, Callable, Iterable
import uuid

SERVICE_OWNER = "unifi_announcer"
SLOT_COUNT = 2
SCHEMA_VERSION = 1


class DynamicSlotError(RuntimeError):
    """Base error for fixed-slot provisioning or playback."""


class DynamicSlotUnavailable(DynamicSlotError):
    """Dynamic TTS cannot safely use the configured chime(s)."""


@dataclass
class DeviceSlotBinding:
    chime_id: str
    device_slot: int
    filename: str
    provisioning_md5: str
    provisioning_size: int
    current_md5: str | None = None
    current_size: int | None = None
    verified_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DeviceSlotBinding":
        return cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})

    def accepts_track(self, track: dict[str, Any]) -> bool:
        md5, size = _fingerprint(track)
        accepted = {(self.provisioning_md5, self.provisioning_size)}
        if self.current_md5 is not None and self.current_size is not None:
            accepted.add((self.current_md5, self.current_size))
        return (md5, size) in accepted


@dataclass
class DynamicTtsSlot:
    logical_slot: int
    protect_name: str
    protect_ringtone_id: str
    bootstrap_md5: str
    bootstrap_size: int
    bindings: dict[str, DeviceSlotBinding] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DynamicTtsSlot":
        bindings = {
            key: DeviceSlotBinding.from_dict(item)
            for key, item in (value.get("bindings") or {}).items()
        }
        data = {k: value[k] for k in cls.__dataclass_fields__ if k in value and k != "bindings"}
        return cls(**data, bindings=bindings)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["bindings"] = {key: asdict(binding) for key, binding in self.bindings.items()}
        return value


@dataclass
class PreparedDynamicSlot:
    manager: "DynamicTtsSlotManager"
    logical_slot: int
    ringtone_id: str
    duration_ms: int
    content_md5: str
    _released: bool = False

    async def refresh_ringtone_id(self) -> str:
        self.ringtone_id = await self.manager.refresh_ringtone_id(self.logical_slot)
        return self.ringtone_id

    def release_after(self, repeat_times: int) -> None:
        if self._released:
            return
        self._released = True
        self.manager.release_after(self.logical_slot, self.duration_ms, repeat_times)

    async def release_now(self) -> None:
        if self._released:
            return
        self._released = True
        await self.manager.release_now(self.logical_slot)


class DynamicTtsSlotManager:
    """Provision, prove, overwrite and lease the two dynamic TTS slots."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        list_ringtones: Callable[[], Awaitable[list[dict[str, Any]]]],
        upload_ringtone: Callable[[str, bytes], Awaitable[dict[str, Any]]],
        delete_ringtone: Callable[[str], Awaitable[bool]],
        resolve_ringtone: Callable[[str], Awaitable[dict[str, Any] | None]],
        refresh_index: Callable[[], Awaitable[Any]],
        get_chime: Callable[[str], Awaitable[dict[str, Any]]],
        play_ringtone: Callable[..., Awaitable[dict[str, Any]]],
        ensure_capacity: Callable[[Iterable[dict[str, Any]], int], Awaitable[Any]] | None = None,
        metrics: Any | None = None,
        reuse_margin_ms: int = 1250,
        minimum_guard_ms: int = 1750,
        provisioning_timeout_s: float = 15.0,
        poll_interval_s: float = 0.5,
        device_sync_timeout_s: float = 10.0,
        device_settle_delay_s: float = 0.75,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.identity_path = self.data_dir / "installation.json"
        self.registry_path = self.data_dir / "dynamic_tts_slots.json"
        self.list_ringtones = list_ringtones
        self.upload_ringtone = upload_ringtone
        self.delete_ringtone = delete_ringtone
        self.resolve_ringtone = resolve_ringtone
        self.refresh_index = refresh_index
        self.get_chime = get_chime
        self.play_ringtone = play_ringtone
        self.ensure_capacity = ensure_capacity
        self.metrics = metrics
        self.reuse_margin_ms = max(0, int(reuse_margin_ms))
        self.minimum_guard_ms = max(0, int(minimum_guard_ms))
        self.provisioning_timeout_s = max(1.0, float(provisioning_timeout_s))
        self.poll_interval_s = max(0.05, float(poll_interval_s))
        self.device_sync_timeout_s = max(0.1, float(device_sync_timeout_s))
        self.device_settle_delay_s = max(0.0, float(device_settle_delay_s))
        self.installation_id = ""
        self.slots: dict[int, DynamicTtsSlot] = {}
        self.ready = False
        self.last_error: str | None = None
        self.legacy_orphans = 0
        self._condition = asyncio.Condition()
        self._busy: set[int] = set()
        self._next_slot = 1
        self._release_tasks: set[asyncio.Task] = set()
        self._targets: dict[str, Any] = {}
        self._bootstrap_audio: dict[int, bytes] = {}

    @property
    def installation_suffix(self) -> str:
        return self.installation_id.replace("-", "")[:8]

    @staticmethod
    def is_slot_name(name: str | None) -> bool:
        return bool(name and name.upper().startswith("UA-TTS-"))

    def _metric(self, name: str, amount: int = 1) -> None:
        if self.metrics is not None and hasattr(self.metrics, "inc"):
            self.metrics.inc(name, amount)

    def _load_or_create_identity(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.identity_path.exists():
            try:
                raw = json.loads(self.identity_path.read_text())
                value = str(raw["installation_id"])
                uuid.UUID(value)
                return value
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise DynamicSlotUnavailable(
                    "installation identity is corrupt; refusing to generate replacement slot names"
                ) from exc
        value = str(uuid.uuid4())
        _atomic_json(self.identity_path, {
            "schema_version": SCHEMA_VERSION,
            "installation_id": value,
        })
        return value

    def _load_registry(self) -> None:
        if not self.registry_path.exists():
            self.slots = {}
            return
        try:
            raw = json.loads(self.registry_path.read_text())
            if int(raw.get("schema_version", 0)) != SCHEMA_VERSION:
                raise ValueError("unsupported dynamic slot registry schema")
            if raw.get("installation_id") != self.installation_id:
                raise ValueError("dynamic slot registry installation identity mismatch")
            self.slots = {
                int(key): DynamicTtsSlot.from_dict(value)
                for key, value in (raw.get("slots") or {}).items()
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise DynamicSlotUnavailable(
                "dynamic TTS slot registry is invalid; refusing unsafe reprovisioning"
            ) from exc

    def _persist_registry(self) -> None:
        _atomic_json(self.registry_path, {
            "schema_version": SCHEMA_VERSION,
            "installation_id": self.installation_id,
            "slots": {str(key): slot.to_dict() for key, slot in self.slots.items()},
        })

    async def startup(
        self,
        targets: Iterable[Any],
        *,
        bootstrap_audio_factory: Callable[[int], Awaitable[bytes]],
        legacy_registry: Any | None = None,
    ) -> dict[str, Any]:
        """Load identity, provision exactly two slots, reconcile and migrate legacy TTS."""
        self.installation_id = self._load_or_create_identity()
        self._load_registry()
        self._targets = {target.desc.chime_id: target for target in targets if target is not None}
        if not self._targets:
            self.ready = False
            self.last_error = "no configured Smart Chime targets"
            return self.status()
        try:
            # Prove direct write capability before allocating new Protect identities.
            for target in self._targets.values():
                if getattr(target, "direct_client", None) is None:
                    raise DynamicSlotUnavailable(
                        f"{target.desc.name}: direct device client unavailable"
                    )
                await target.direct_client.info()
            for number in range(1, SLOT_COUNT + 1):
                self._bootstrap_audio[number] = await bootstrap_audio_factory(number)
                await self._ensure_slot(number)
            await self._validate_all_bindings()
            if legacy_registry is not None:
                await self._migrate_legacy(legacy_registry)
            self.ready = True
            self.last_error = None
        except Exception as exc:
            self.ready = False
            self.last_error = f"{type(exc).__name__}: {exc}"
        return self.status()

    async def shutdown(self) -> None:
        for task in tuple(self._release_tasks):
            task.cancel()
        if self._release_tasks:
            await asyncio.gather(*self._release_tasks, return_exceptions=True)
        self._release_tasks.clear()
        async with self._condition:
            self._busy.clear()
            self._condition.notify_all()

    def _slot_name(self, number: int) -> str:
        return f"UA-TTS-{number}-{self.installation_suffix}"

    def _slot_filename(self, number: int) -> str:
        return f"ua_tts_{number}_{self.installation_suffix}.mp3"

    async def _ensure_slot(self, number: int) -> DynamicTtsSlot:
        bootstrap = self._bootstrap_audio[number]
        bootstrap_md5 = hashlib.md5(bootstrap).hexdigest()
        bootstrap_size = len(bootstrap)
        name = self._slot_name(number)
        tones = await self.list_ringtones()
        by_id = {_ringtone_id(t): t for t in tones if _ringtone_id(t)}
        named = [t for t in tones if str(t.get("name", "")) == name]
        existing = self.slots.get(number)

        if existing is not None:
            tone = by_id.get(existing.protect_ringtone_id)
            if tone is None:
                exact = [item for item in named if _ringtone_id(item)]
                if len(exact) != 1:
                    raise DynamicSlotUnavailable(
                        f"slot {number}: registered Protect ringtone is missing or ambiguous"
                    )
                existing.protect_ringtone_id = _ringtone_id(exact[0])
            if existing.protect_name != name:
                raise DynamicSlotUnavailable(f"slot {number}: persisted name does not match installation")
            return existing

        if named:
            # An exact service-looking name without our registry proof is not enough ownership evidence.
            raise DynamicSlotUnavailable(
                f"slot {number}: Protect already contains {name!r} but local ownership proof is absent"
            )

        if self.ensure_capacity is not None:
            await self.ensure_capacity(tones, 1)
        await self.upload_ringtone(name, bootstrap)
        await self.refresh_index()
        created = await self.resolve_ringtone(name)
        if not created or not _ringtone_id(created):
            raise DynamicSlotUnavailable(f"slot {number}: Protect upload succeeded but identity is unresolved")
        slot = DynamicTtsSlot(
            logical_slot=number,
            protect_name=name,
            protect_ringtone_id=_ringtone_id(created),
            bootstrap_md5=bootstrap_md5,
            bootstrap_size=bootstrap_size,
        )
        self.slots[number] = slot
        self._persist_registry()
        self._metric("tts_slot_provisioned")

        # Playing the silent bootstrap forces Protect to stage the ringtone to each chime.
        for chime_id in self._targets:
            await self.play_ringtone(
                slot.protect_ringtone_id, volume=0, repeat_times=1, chime_id=chime_id
            )
        for chime_id in self._targets:
            slot.bindings[chime_id] = await self._discover_binding(slot, chime_id)
        slot.updated_at = time.time()
        self._persist_registry()
        return slot

    async def _discover_binding(self, slot: DynamicTtsSlot, chime_id: str) -> DeviceSlotBinding:
        deadline = asyncio.get_running_loop().time() + self.provisioning_timeout_s
        while True:
            chime = await self.get_chime(chime_id)
            tracks = chime.get("speakerTrackList") or []
            matches = []
            for index, track in enumerate(tracks, 1):
                md5, size = _fingerprint(track)
                if md5 == slot.bootstrap_md5 and size == slot.bootstrap_size:
                    matches.append((index, track))
            if len(matches) == 1:
                device_slot, track = matches[0]
                filename = str(track.get("fileName") or track.get("filename") or self._slot_filename(slot.logical_slot))
                if not filename.endswith(".mp3"):
                    filename = self._slot_filename(slot.logical_slot)
                return DeviceSlotBinding(
                    chime_id=chime_id,
                    device_slot=device_slot,
                    filename=filename,
                    provisioning_md5=slot.bootstrap_md5,
                    provisioning_size=slot.bootstrap_size,
                    current_md5=slot.bootstrap_md5,
                    current_size=slot.bootstrap_size,
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise DynamicSlotUnavailable(
                    f"slot {slot.logical_slot}: could not prove physical binding for chime {chime_id}"
                )
            await asyncio.sleep(self.poll_interval_s)

    async def _validate_all_bindings(self) -> None:
        expected_slots = set(range(1, SLOT_COUNT + 1))
        if set(self.slots) != expected_slots:
            raise DynamicSlotUnavailable("exactly logical slots 1 and 2 must be provisioned")

        ringtone_ids = [self.slots[number].protect_ringtone_id for number in expected_slots]
        if any(not ringtone_id.strip() for ringtone_id in ringtone_ids) or len(
            set(ringtone_ids)
        ) != SLOT_COUNT:
            raise DynamicSlotUnavailable(
                "logical slots 1 and 2 must have distinct nonempty Protect IDs"
            )

        for chime_id in self._targets:
            physical_slots: set[int] = set()
            for number in range(1, SLOT_COUNT + 1):
                slot = self.slots[number]
                binding = slot.bindings.get(chime_id)
                if binding is None:
                    binding = await self._discover_binding(slot, chime_id)
                    slot.bindings[chime_id] = binding
                else:
                    await self._preflight_binding(slot, binding)
                if binding.device_slot in physical_slots:
                    raise DynamicSlotUnavailable(
                        f"chime {chime_id}: logical slots must use distinct physical slots"
                    )
                physical_slots.add(binding.device_slot)
        self._persist_registry()

    async def _preflight_binding(
        self, slot: DynamicTtsSlot, binding: DeviceSlotBinding
    ) -> dict[str, Any] | None:
        chime = await self.get_chime(binding.chime_id)
        tracks = chime.get("speakerTrackList") or []
        if binding.device_slot < 1 or not binding.filename.endswith(".mp3"):
            raise DynamicSlotUnavailable(
                f"chime {binding.chime_id}: invalid persisted TTS slot binding"
            )

        # Protect may omit custom slots or leave fingerprints stale after a
        # direct overwrite. Missing metadata therefore retains an already-proven
        # persisted mapping. When the physical position is reported, either its
        # exact filename must still match or its exact provisioning fingerprint
        # must prove that Protect renamed the same service-owned slot.
        numbered = [
            track
            for track in tracks
            if int(track.get("track_no") or track.get("trackNo") or 0)
            == binding.device_slot
        ]
        if len(numbered) > 1:
            raise DynamicSlotUnavailable(
                f"chime {binding.chime_id}: physical TTS slot is ambiguous"
            )
        track = numbered[0] if numbered else (
            tracks[binding.device_slot - 1]
            if binding.device_slot <= len(tracks)
            else None
        )
        if track is not None:
            raw_filename = (
                track.get("fileName") or track.get("filename") or track.get("name") or ""
            )
            filename = str(raw_filename)
            if filename and not filename.endswith(".mp3"):
                filename = f"{filename}.mp3"
            if filename != binding.filename:
                if filename and (
                    binding.accepts_track(track)
                    or _fingerprint(track) == (slot.bootstrap_md5, slot.bootstrap_size)
                ):
                    binding.filename = filename
                else:
                    raise DynamicSlotUnavailable(
                        f"chime {binding.chime_id}: TTS slot ownership proof no longer matches"
                    )
        binding.verified_at = time.time()
        return track

    async def _acquire_slot_number(self) -> int:
        async with self._condition:
            while True:
                order = [self._next_slot, 1 if self._next_slot == 2 else 2]
                for number in order:
                    if number not in self._busy:
                        self._busy.add(number)
                        self._next_slot = 1 if number == 2 else 2
                        return number
                await self._condition.wait()

    async def prepare(self, mp3: bytes, targets: Iterable[Any]) -> PreparedDynamicSlot:
        if not self.ready:
            raise DynamicSlotUnavailable(self.last_error or "dynamic TTS slots are not ready")
        target_list = [target for target in targets if target is not None]
        if not target_list:
            raise DynamicSlotUnavailable("no dynamic TTS targets")
        number = await self._acquire_slot_number()
        try:
            slot = self.slots[number]
            md5 = hashlib.md5(mp3).hexdigest()
            size = len(mp3)
            for target in target_list:
                chime_id = target.desc.chime_id
                binding = slot.bindings.get(chime_id)
                if binding is None:
                    raise DynamicSlotUnavailable(
                        f"slot {number}: no proven binding for {target.desc.name}"
                    )
                physical_track = await self._preflight_binding(slot, binding)
                if (
                    binding.current_md5 == md5
                    and binding.current_size == size
                    and physical_track is not None
                    and _fingerprint(physical_track) == (md5, size)
                ):
                    self._metric("tts_slot_overwrite_skips")
                    continue
                await target.direct_client.overwrite_owned_slot(
                    slot=binding.device_slot,
                    filename=binding.filename,
                    mp3_bytes=mp3,
                    owner=SERVICE_OWNER,
                    builtin=False,
                    experiment_enabled=True,
                )
                await self._wait_for_device_sync(
                    binding, expected_md5=md5, expected_size=size
                )
                binding.current_md5 = md5
                binding.current_size = size
                binding.verified_at = time.time()
                self._metric("tts_slot_overwrites")
            slot.updated_at = time.time()
            self._persist_registry()
            return PreparedDynamicSlot(
                manager=self,
                logical_slot=number,
                ringtone_id=slot.protect_ringtone_id,
                duration_ms=estimate_mp3_duration_ms(mp3),
                content_md5=md5,
            )
        except Exception:
            await self.release_now(number)
            raise

    async def _wait_for_device_sync(
        self,
        binding: DeviceSlotBinding,
        *,
        expected_md5: str,
        expected_size: int,
    ) -> None:
        """Wait until Protect reports the overwritten bytes on the physical slot."""
        deadline = asyncio.get_running_loop().time() + self.device_sync_timeout_s
        while True:
            chime = await self.get_chime(binding.chime_id)
            tracks = chime.get("speakerTrackList") or []
            numbered = [
                track
                for track in tracks
                if int(track.get("track_no") or track.get("trackNo") or 0)
                == binding.device_slot
            ]
            track = numbered[0] if len(numbered) == 1 else (
                tracks[binding.device_slot - 1]
                if not numbered and binding.device_slot <= len(tracks)
                else None
            )
            if track is not None and _fingerprint(track) == (expected_md5, expected_size):
                if self.device_settle_delay_s:
                    await asyncio.sleep(self.device_settle_delay_s)
                self._metric("tts_slot_sync_successes")
                return
            if asyncio.get_running_loop().time() >= deadline:
                self._metric("tts_slot_sync_timeouts")
                raise DynamicSlotUnavailable(
                    f"chime {binding.chime_id}: overwritten TTS slot did not synchronize"
                )
            await asyncio.sleep(self.poll_interval_s)

    async def refresh_ringtone_id(self, number: int) -> str:
        slot = self.slots[number]
        tones = await self.list_ringtones()
        exact = [tone for tone in tones if str(tone.get("name", "")) == slot.protect_name]
        if len(exact) != 1 or not _ringtone_id(exact[0]):
            raise DynamicSlotUnavailable(
                f"slot {number}: persistent Protect identity is missing or ambiguous"
            )
        slot.protect_ringtone_id = _ringtone_id(exact[0])
        slot.updated_at = time.time()
        self._persist_registry()
        return slot.protect_ringtone_id

    def release_after(self, number: int, duration_ms: int, repeat_times: int) -> None:
        guard_ms = max(
            self.minimum_guard_ms,
            max(1, repeat_times) * max(0, duration_ms) + self.reuse_margin_ms,
        )
        task = asyncio.create_task(self._release_later(number, guard_ms / 1000.0))
        self._release_tasks.add(task)
        task.add_done_callback(self._release_tasks.discard)

    async def _release_later(self, number: int, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
        finally:
            await self.release_now(number)

    async def release_now(self, number: int) -> None:
        async with self._condition:
            self._busy.discard(number)
            self._condition.notify_all()

    async def _migrate_legacy(self, registry: Any) -> None:
        """Delete proven old NVR dynamic identities and preserve unresolved device evidence.

        Physical legacy files are only overwritten with tiny bootstrap audio when
        an exact NVR fingerprint maps to exactly one device track. Anything else
        is retained as a legacy orphan rather than guessed at.
        """
        tones = await self.list_ringtones()
        by_id = {_ringtone_id(tone): tone for tone in tones if _ringtone_id(tone)}
        protected_ids = {slot.protect_ringtone_id for slot in self.slots.values()}
        orphan_count = 0
        for key, record in list(getattr(registry, "records", {}).items()):
            if getattr(record, "owner", None) != SERVICE_OWNER or getattr(record, "kind", None) != "dynamic_tts":
                continue
            rid = getattr(record, "nvr_ringtone_id", None)
            if rid in protected_ids:
                continue
            tone = by_id.get(rid) if rid else None
            device_cleanup_complete = True
            tone_md5, tone_size = _fingerprint(tone or {})
            if tone_md5 is not None and tone_size is not None:
                cleanup_audio = self._bootstrap_audio[1]
                for target in self._targets.values():
                    chime = await self.get_chime(target.desc.chime_id)
                    tracks = chime.get("speakerTrackList") or []
                    matches = [
                        index for index, track in enumerate(tracks, 1)
                        if _fingerprint(track) == (tone_md5, tone_size)
                    ]
                    if len(matches) != 1:
                        device_cleanup_complete = False
                        continue
                    try:
                        await target.direct_client.overwrite_owned_slot(
                            slot=matches[0],
                            filename=f"ua_legacy_{self.installation_suffix}.mp3",
                            mp3_bytes=cleanup_audio,
                            owner=SERVICE_OWNER,
                            builtin=False,
                            experiment_enabled=True,
                        )
                        self._metric("legacy_dynamic_slots_silenced")
                    except Exception:
                        device_cleanup_complete = False
            else:
                device_cleanup_complete = False

            nvr_deleted = True
            if rid:
                nvr_deleted = await self.delete_ringtone(rid)
                if nvr_deleted:
                    self._metric("legacy_dynamic_nvr_deleted")
            if nvr_deleted and device_cleanup_complete:
                registry.remove(key)
            else:
                record.nvr_ringtone_id = None if nvr_deleted else rid
                record.kind = "legacy_orphan"
                registry.put(record)
                orphan_count += 1
        self.legacy_orphans = orphan_count
        if tones:
            await self.refresh_index()

    def status(self) -> dict[str, Any]:
        return {
            "mode": "two_slot_overwrite",
            "ready": self.ready,
            "installation": self.installation_suffix or None,
            "slot_count": SLOT_COUNT,
            "busy_slots": sorted(self._busy),
            "legacy_orphans": self.legacy_orphans,
            "last_error": self.last_error,
            "slots": {
                str(number): {
                    "protect_name": slot.protect_name,
                    "protect_ringtone_id": slot.protect_ringtone_id,
                    "bindings": {
                        chime_id: {
                            "device_slot": binding.device_slot,
                            "filename": binding.filename,
                            "verified_at": binding.verified_at,
                        }
                        for chime_id, binding in slot.bindings.items()
                    },
                }
                for number, slot in sorted(self.slots.items())
            },
        }


def _ringtone_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("_id") or "")


def _fingerprint(item: dict[str, Any]) -> tuple[str | None, int | None]:
    md5 = item.get("md5") or item.get("hash")
    raw_size = item.get("size") if item.get("size") is not None else item.get("fileSize")
    try:
        size = int(raw_size) if raw_size is not None else None
    except (TypeError, ValueError):
        size = None
    return (str(md5) if md5 else None, size)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(temp, path)


def estimate_mp3_duration_ms(data: bytes) -> int:
    """Estimate MP3 duration by walking Layer III frames; safe fallback is size-based.

    The parser is deliberately small and tolerant because the reuse guard only
    needs a conservative duration estimate, not media metadata fidelity.
    """
    if not data:
        return 0
    pos = 0
    if data.startswith(b"ID3") and len(data) >= 10:
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        pos = min(len(data), 10 + size)
    total_samples = 0
    sample_rate_seen = 0
    frames = 0
    bitrate_v1_l3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
    bitrate_v2_l3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
    rates = {0: [44100, 22050, 11025], 1: [48000, 24000, 12000], 2: [32000, 16000, 8000]}
    while pos + 4 <= len(data):
        header = int.from_bytes(data[pos:pos + 4], "big")
        if (header & 0xFFE00000) != 0xFFE00000:
            pos += 1
            continue
        version_bits = (header >> 19) & 0x3
        layer_bits = (header >> 17) & 0x3
        bitrate_index = (header >> 12) & 0xF
        rate_index = (header >> 10) & 0x3
        padding = (header >> 9) & 0x1
        if version_bits == 1 or layer_bits != 1 or rate_index == 3:
            pos += 1
            continue
        version_index = 0 if version_bits == 3 else (1 if version_bits == 2 else 2)
        sample_rate = rates.get(rate_index, [0, 0, 0])[version_index]
        bitrates = bitrate_v1_l3 if version_bits == 3 else bitrate_v2_l3
        bitrate = bitrates[bitrate_index] * 1000
        if not sample_rate or not bitrate:
            pos += 1
            continue
        samples = 1152 if version_bits == 3 else 576
        frame_len = ((144 if version_bits == 3 else 72) * bitrate // sample_rate) + padding
        if frame_len <= 4 or pos + frame_len > len(data):
            break
        total_samples += samples
        sample_rate_seen = sample_rate
        frames += 1
        pos += frame_len
    if frames and sample_rate_seen:
        return max(1, int(total_samples * 1000 / sample_rate_seen))
    # Conservative fallback: assume no more than 32kbps so guard time errs long.
    return max(1, int(len(data) * 8 * 1000 / 32_000))
