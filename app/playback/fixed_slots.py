"""Production-safe fixed dynamic TTS slot provisioning.

The production manager deliberately proves physical Smart Chime slot ownership
by observing one controlled Protect staging operation. It never assumes Protect
preserves the source MP3 hash/size on device flash.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Awaitable, Callable, Iterable

from app.playback.dynamic_slots import (
    SERVICE_OWNER,
    SLOT_COUNT,
    DeviceSlotBinding,
    DynamicSlotUnavailable,
    DynamicTtsSlot,
    DynamicTtsSlotManager as _BaseDynamicTtsSlotManager,
    _fingerprint,
    _ringtone_id,
)


class DynamicTtsSlotManager(_BaseDynamicTtsSlotManager):
    """Two-slot manager using controlled before/after device evidence.

    A slot is bound only when staging one known service-owned Protect ringtone
    causes exactly one unambiguous physical ``speakerTrackList`` delta. Zero or
    multiple candidates fail closed. Legacy beta.2 cleanup runs only after both
    new fixed slots are fully proven.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.binding_diagnostics: dict[str, dict[str, Any]] = {}
        self.migration_error: str | None = None

    async def startup(
        self,
        targets: Iterable[Any],
        *,
        bootstrap_audio_factory: Callable[[int], Awaitable[bytes]],
        legacy_registry: Any | None = None,
    ) -> dict[str, Any]:
        try:
            self.installation_id = self._load_or_create_identity()
            self._load_registry()
            self._targets = {
                target.desc.chime_id: target for target in targets if target is not None
            }
            if not self._targets:
                raise DynamicSlotUnavailable("no configured Smart Chime targets")

            # Prove direct-write capability before creating or staging anything.
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
            self.ready = True
            self.last_error = None

            # Migration is deliberately after both fixed slots are proven. A
            # migration defect must not destroy a working fixed-slot binding.
            if legacy_registry is not None:
                try:
                    await self._migrate_legacy(legacy_registry)
                    self.migration_error = None
                except Exception as exc:  # pragma: no cover - defensive live boundary
                    self.migration_error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            self.ready = False
            self.last_error = f"{type(exc).__name__}: {exc}"
        return self.status()

    async def _track_snapshot(self, chime_id: str) -> list[dict[str, Any]]:
        chime = await self.get_chime(chime_id)
        return [dict(track) for track in (chime.get("speakerTrackList") or [])]

    @staticmethod
    def _track_signature(track: dict[str, Any]) -> tuple[Any, ...]:
        """Stable non-secret fields useful for physical slot delta comparison."""
        md5, size = _fingerprint(track)
        return (
            md5,
            size,
            track.get("fileName") or track.get("filename"),
            track.get("id") or track.get("_id"),
            track.get("ringtoneId") or track.get("speakerTrackId"),
            track.get("name"),
        )

    @classmethod
    def _delta_candidate(
        cls, before: list[dict[str, Any]], after: list[dict[str, Any]]
    ) -> tuple[int, dict[str, Any]] | None:
        """Return one unambiguous changed/inserted physical slot, else None."""
        before_sig = [cls._track_signature(track) for track in before]
        after_sig = [cls._track_signature(track) for track in after]

        if len(after_sig) == len(before_sig):
            changed = [
                index for index, (old, new) in enumerate(zip(before_sig, after_sig), 1)
                if old != new
            ]
            if len(changed) == 1:
                index = changed[0]
                return index, after[index - 1]
            return None

        if len(after_sig) == len(before_sig) + 1:
            candidates = []
            for zero_index in range(len(after_sig)):
                if after_sig[:zero_index] + after_sig[zero_index + 1:] == before_sig:
                    candidates.append(zero_index)
            if len(candidates) == 1:
                zero_index = candidates[0]
                return zero_index + 1, after[zero_index]
        return None

    @classmethod
    def _summary(cls, tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitized diagnostics; never return credentials or arbitrary payloads."""
        result = []
        for index, track in enumerate(tracks, 1):
            md5, size = _fingerprint(track)
            result.append({
                "slot": index,
                "md5": md5,
                "size": size,
                "filename": track.get("fileName") or track.get("filename"),
                "id": track.get("id") or track.get("_id"),
                "ringtone_id": track.get("ringtoneId") or track.get("speakerTrackId"),
                "name": track.get("name"),
            })
        return result

    async def _discover_binding_from_delta(
        self,
        slot: DynamicTtsSlot,
        chime_id: str,
        before: list[dict[str, Any]],
    ) -> DeviceSlotBinding:
        deadline = self._loop_time() + self.provisioning_timeout_s
        last_after = before
        while True:
            after = await self._track_snapshot(chime_id)
            last_after = after
            candidate = self._delta_candidate(before, after)
            if candidate is not None:
                device_slot, track = candidate
                md5, size = _fingerprint(track)
                filename = track.get("fileName") or track.get("filename")
                if md5 is not None and size is not None and filename:
                    binding = DeviceSlotBinding(
                        chime_id=chime_id,
                        device_slot=device_slot,
                        filename=str(filename),
                        # These are intentionally the DEVICE-observed values,
                        # not the source MP3 values. Protect may transform audio.
                        provisioning_md5=md5,
                        provisioning_size=size,
                        current_md5=md5,
                        current_size=size,
                    )
                    self.binding_diagnostics[chime_id] = {
                        "logical_slot": slot.logical_slot,
                        "result": "proven",
                        "device_slot": device_slot,
                        "before_count": len(before),
                        "after_count": len(after),
                    }
                    return binding
            if self._loop_time() >= deadline:
                self.binding_diagnostics[chime_id] = {
                    "logical_slot": slot.logical_slot,
                    "result": "ambiguous",
                    "before": self._summary(before),
                    "after": self._summary(last_after),
                }
                raise DynamicSlotUnavailable(
                    f"slot {slot.logical_slot}: controlled staging did not produce exactly one "
                    f"provable physical track delta for chime {chime_id}"
                )
            await self._sleep_poll()

    @staticmethod
    def _loop_time() -> float:
        import asyncio

        return asyncio.get_running_loop().time()

    async def _sleep_poll(self) -> None:
        import asyncio

        await asyncio.sleep(self.poll_interval_s)

    async def _stage_and_bind(
        self,
        slot: DynamicTtsSlot,
        before_by_chime: dict[str, list[dict[str, Any]]],
        only_missing: bool = False,
    ) -> None:
        # Volume 1 is intentional. The bootstrap audio is silent, while a
        # non-zero play request forces the real Protect staging/playback path.
        for chime_id in self._targets:
            if only_missing and chime_id in slot.bindings:
                continue
            await self.play_ringtone(
                slot.protect_ringtone_id, volume=1, repeat_times=1, chime_id=chime_id
            )
        for chime_id in self._targets:
            if only_missing and chime_id in slot.bindings:
                continue
            slot.bindings[chime_id] = await self._discover_binding_from_delta(
                slot, chime_id, before_by_chime[chime_id]
            )
        slot.updated_at = time.time()
        self._persist_registry()

    async def _ensure_slot(self, number: int) -> DynamicTtsSlot:
        bootstrap = self._bootstrap_audio[number]
        bootstrap_md5 = hashlib.md5(bootstrap).hexdigest()
        bootstrap_size = len(bootstrap)
        name = self._slot_name(number)
        tones = await self.list_ringtones()
        by_id = {_ringtone_id(tone): tone for tone in tones if _ringtone_id(tone)}
        named = [tone for tone in tones if str(tone.get("name", "")) == name]
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
                raise DynamicSlotUnavailable(
                    f"slot {number}: persisted name does not match installation"
                )
            missing = [chime_id for chime_id in self._targets if chime_id not in existing.bindings]
            if missing:
                before = {chime_id: await self._track_snapshot(chime_id) for chime_id in missing}
                await self._stage_and_bind(existing, before, only_missing=True)
            return existing

        if named:
            # A matching service-looking name without local registry ownership
            # proof is not sufficient to claim a physical flash slot.
            raise DynamicSlotUnavailable(
                f"slot {number}: Protect already contains {name!r} but local ownership proof is absent"
            )

        before = {
            chime_id: await self._track_snapshot(chime_id)
            for chime_id in self._targets
        }

        # Fixed-slot provisioning does not invoke beta.2 dynamic eviction. If
        # Protect itself rejects capacity, fail closed and retain legacy proof.
        await self.upload_ringtone(name, bootstrap)
        await self.refresh_index()
        created = await self.resolve_ringtone(name)
        if not created or not _ringtone_id(created):
            raise DynamicSlotUnavailable(
                f"slot {number}: Protect upload succeeded but identity is unresolved"
            )
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
        await self._stage_and_bind(slot, before)
        return slot

    async def _migrate_legacy(self, registry: Any) -> None:
        """Conservatively clean proven beta.2 dynamic tracks after slot readiness.

        An NVR identity is deleted only after every configured device copy was
        unambiguously matched and safely overwritten. Unproven entries retain
        their NVR identity and become ``legacy_orphan`` records for review.
        """
        tones = await self.list_ringtones()
        by_id = {_ringtone_id(tone): tone for tone in tones if _ringtone_id(tone)}
        protected_ids = {slot.protect_ringtone_id for slot in self.slots.values()}
        orphan_count = 0

        for key, record in list(getattr(registry, "records", {}).items()):
            if (
                getattr(record, "owner", None) != SERVICE_OWNER
                or getattr(record, "kind", None) != "dynamic_tts"
            ):
                continue
            rid = getattr(record, "nvr_ringtone_id", None)
            if rid in protected_ids:
                continue
            tone = by_id.get(rid) if rid else None
            tone_md5, tone_size = _fingerprint(tone or {})
            device_cleanup_complete = tone_md5 is not None and tone_size is not None

            if device_cleanup_complete:
                cleanup_audio = self._bootstrap_audio[1]
                for target in self._targets.values():
                    chime = await self.get_chime(target.desc.chime_id)
                    tracks = chime.get("speakerTrackList") or []
                    matches = [
                        (index, track)
                        for index, track in enumerate(tracks, 1)
                        if _fingerprint(track) == (tone_md5, tone_size)
                    ]
                    if len(matches) != 1:
                        device_cleanup_complete = False
                        continue
                    index, track = matches[0]
                    filename = track.get("fileName") or track.get("filename")
                    if not filename:
                        device_cleanup_complete = False
                        continue
                    try:
                        await target.direct_client.overwrite_owned_slot(
                            slot=index,
                            filename=str(filename),
                            mp3_bytes=cleanup_audio,
                            owner=SERVICE_OWNER,
                            builtin=False,
                            experiment_enabled=True,
                        )
                        self._metric("legacy_dynamic_slots_silenced")
                    except Exception:
                        device_cleanup_complete = False

            if device_cleanup_complete and rid:
                deleted = await self.delete_ringtone(rid)
                if deleted:
                    self._metric("legacy_dynamic_nvr_deleted")
                    registry.remove(key)
                    continue

            record.kind = "legacy_orphan"
            registry.put(record)
            orphan_count += 1

        self.legacy_orphans = orphan_count
        if tones:
            await self.refresh_index()

    def status(self) -> dict[str, Any]:
        payload = super().status()
        payload["binding_diagnostics"] = self.binding_diagnostics
        payload["migration_error"] = self.migration_error
        return payload
