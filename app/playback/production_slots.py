"""Production fixed-slot synchronization and content-reuse policy.

Protect can lag behind a direct write, but can also restore canonical bytes.
An old application record cannot distinguish those cases. Resident reuse needs
both local proof and a matching fingerprint in the current Protect inventory.

The strict provisioning/binding implementation remains in ``fixed_slots``.
This subclass adds:
- bounded stale-Protect-inventory acceptance after a successful direct write;
- content-aware selection across the two existing service-owned slots;
- restart-safe application-side content identity with device validation;
- detailed slot-path timing/counter instrumentation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, Iterable

from app.playback.dynamic_slots import (
    DeviceSlotBinding,
    DynamicSlotUnavailable,
    PreparedDynamicSlot,
    SERVICE_OWNER,
    _fingerprint,
    estimate_mp3_duration_ms,
)
from app.playback.fixed_slots import DynamicTtsSlotManager as _FixedDynamicTtsSlotManager

CONTENT_STATE_SCHEMA_VERSION = 1


class DynamicTtsSlotManager(_FixedDynamicTtsSlotManager):
    """Fixed-slot manager with safe, application-authoritative content reuse."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault(
            "device_sync_timeout_s",
            float(os.getenv("TTS_SLOT_SYNC_TIMEOUT", "0.40")),
        )
        kwargs.setdefault(
            "poll_interval_s",
            float(os.getenv("TTS_SLOT_POLL_INTERVAL", "0.10")),
        )
        kwargs.setdefault(
            "device_settle_delay_s",
            float(os.getenv("TTS_SLOT_SETTLE_DELAY", "0.20")),
        )
        super().__init__(*args, **kwargs)
        self.content_state_path = self.data_dir / "dynamic_tts_content_state.json"
        self._content_state: dict[str, Any] = {"bindings": {}}
        self._trusted_content: set[tuple[int, str]] = set()
        self._device_identities: dict[str, str] = {}
        self._device_boot_epochs: dict[str, float] = {}
        self._invalidating_targets: dict[str, int] = {}
        self._busy_targets: dict[int, frozenset[str]] = {}
        self._external_epochs: dict[str, int] = {}
        self._pending_writes: dict[tuple[int, str], tuple[str, int]] = {}
        self._fresh_lease_content: set[tuple[int, str]] = set()
        self.boot_epoch_tolerance_s = float(
            os.getenv("TTS_SLOT_BOOT_EPOCH_TOLERANCE", "5.0")
        )
        if (
            not math.isfinite(self.boot_epoch_tolerance_s)
            or self.boot_epoch_tolerance_s < 0
        ):
            raise ValueError(
                "TTS_SLOT_BOOT_EPOCH_TOLERANCE must be finite and nonnegative"
            )
        self.last_prepare: dict[str, Any] | None = None

    def _observe(self, name: str, value_ms: float) -> None:
        if self.metrics is not None and hasattr(self.metrics, "observe"):
            self.metrics.observe(name, value_ms)

    def note_external_change(self, target_ids: Iterable[str]) -> None:
        """Immediately revoke reuse, including work already preparing a slot.

        Event delivery must not wait for a playback lease: a controller rewrite
        can happen during that lease. Generations prevent an in-flight prepare
        from committing trust again after receiving the event.
        """
        for chime_id in target_ids:
            self._external_epochs[chime_id] = self._external_epochs.get(chime_id, 0) + 1
            for number in self.slots:
                self._trusted_content.discard((number, chime_id))
                self._fresh_lease_content.discard((number, chime_id))

    def observe_inventory(self, chime_id: str, tracks: Any) -> None:
        """Accept expected write feedback without revoking the current lease.

        An inventory event covers the whole Chime. Every owned binding must
        retain its exact slot and filename. Content must agree for pending or
        trusted bindings; unknown unused content has already lost its proof.
        One conflicting or missing binding revokes this target immediately.
        Matching feedback never grants trust that an earlier event revoked.
        """
        if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
            self.note_external_change([chime_id])
            return
        for number, slot in self.slots.items():
            binding = slot.bindings.get(chime_id)
            if binding is None:
                continue
            key = (number, chime_id)
            check_content = key in self._pending_writes or key in self._trusted_content
            expected = self._pending_writes.get(
                key, (binding.current_md5, binding.current_size)
            )
            try:
                track = self._reported_binding_track(tracks, binding)
                matches = (
                    track is not None
                    and self._reported_filename(track) == binding.filename
                    and (
                        not check_content
                        or (
                            expected[0] is not None
                            and expected[1] is not None
                            and _fingerprint(track) == expected
                        )
                    )
                )
            except (DynamicSlotUnavailable, TypeError, ValueError, OverflowError):
                matches = False
            if not matches:
                self.note_external_change([chime_id])
                return

    def validate_prepared(self, lease: PreparedDynamicSlot, chime_id: str) -> None:
        if lease.content_epochs.get(chime_id) != self._external_epochs.get(chime_id, 0):
            raise DynamicSlotUnavailable("Protect changed ringtone state during announcement preparation; retry after synchronization")

    def verify_owned_play(self, ringtone_id: str, chime_id: str, chime: dict) -> bool:
        """Validate our direct-write exception to canonical preset preflight."""
        slots = [slot for slot in self.slots.values() if slot.protect_ringtone_id == ringtone_id]
        if not slots:
            return False
        if len(slots) != 1 or not self.ready:
            raise DynamicSlotUnavailable("owned ringtone is not ready")
        slot = slots[0]
        binding = slot.bindings.get(chime_id)
        if (
            binding is None
            or slot.logical_slot not in self._busy
            or chime_id not in self._busy_targets.get(slot.logical_slot, frozenset())
            or (slot.logical_slot, chime_id) not in self._trusted_content
        ):
            raise DynamicSlotUnavailable("owned ringtone has no current prepared content proof")
        track = self._reported_binding_track(chime.get("speakerTrackList") or [], binding)
        if track is None or self._reported_filename(track) != binding.filename:
            raise DynamicSlotUnavailable("owned ringtone is absent or changed in Protect inventory")
        if (slot.logical_slot, chime_id) in self._fresh_lease_content:
            if _fingerprint(track) != (binding.current_md5, binding.current_size):
                self.note_external_change([chime_id])
                raise DynamicSlotUnavailable("owned ringtone content changed after fresh preparation")
        return True

    def _empty_content_state(self) -> dict[str, Any]:
        return {
            "schema_version": CONTENT_STATE_SCHEMA_VERSION,
            "installation_id": self.installation_id,
            "bindings": {},
        }

    def _load_content_state(self) -> None:
        self._content_state = self._empty_content_state()
        if not self.content_state_path.exists():
            return
        try:
            raw = json.loads(self.content_state_path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("content-state must be an object")
            if type(raw.get("schema_version")) is not int or raw["schema_version"] != CONTENT_STATE_SCHEMA_VERSION:
                raise ValueError("unsupported content-state schema")
            if raw.get("installation_id") != self.installation_id:
                raise ValueError("content-state installation identity mismatch")
            bindings = raw.get("bindings")
            if not isinstance(bindings, dict):
                raise ValueError("content-state bindings must be an object")
            for number, per_chime in bindings.items():
                if number not in {"1", "2"} or not isinstance(per_chime, dict):
                    raise ValueError("invalid content-state slot")
                for chime_id, entry in per_chime.items():
                    if not chime_id or not self._valid_content_entry(entry):
                        raise ValueError("invalid content-state binding")
            self._content_state = raw
        except (OSError, ValueError, TypeError, OverflowError):
            # This file is only an optimization proof. Corruption must never
            # disable playback; discard the fast-path record and rewrite safely.
            self._metric("tts_slot_content_state_resets")
            self._content_state = self._empty_content_state()

    @classmethod
    def _valid_content_entry(cls, entry: Any) -> bool:
        """Validate optimization records before they reach the write path."""
        if not isinstance(entry, dict):
            return False
        md5 = entry.get("source_md5")
        size = entry.get("source_size")
        device_slot = entry.get("device_slot")
        generation = entry.get("write_generation")
        filename = entry.get("filename")
        if (
            not isinstance(md5, str)
            or len(md5) != 32
            or any(char not in "0123456789abcdef" for char in md5)
            or type(size) is not int or size < 0
            or type(device_slot) is not int or device_slot < 1
            or type(generation) is not int or generation < 0
            or not isinstance(filename, str) or not filename.endswith(".mp3")
            or entry.get("content_key") != cls._content_key(md5, size)
        ):
            return False
        identity = entry.get("device_identity")
        if identity is not None and not isinstance(identity, str):
            return False
        for key in ("device_boot_epoch", "written_at", "last_used_at"):
            value = entry.get(key)
            if value is None and key == "device_boot_epoch":
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return False
        return True

    def _persist_content_state(self) -> None:
        from app.persistence import atomic_json
        self._content_state["schema_version"] = CONTENT_STATE_SCHEMA_VERSION
        self._content_state["installation_id"] = self.installation_id
        atomic_json(self.content_state_path, self._content_state)

    def _state_entry(self, number: int, chime_id: str) -> dict[str, Any] | None:
        slots = self._content_state.get("bindings") or {}
        slot = slots.get(str(number))
        if not isinstance(slot, dict):
            return None
        entry = slot.get(chime_id)
        return entry if isinstance(entry, dict) else None

    def _set_state_entry(
        self, number: int, chime_id: str, entry: dict[str, Any]
    ) -> None:
        bindings = self._content_state.setdefault("bindings", {})
        slot = bindings.setdefault(str(number), {})
        slot[chime_id] = entry

    def _invalidate_content_proof(
        self,
        number: int,
        chime_id: str,
        binding: DeviceSlotBinding,
    ) -> None:
        """Persistently revoke old content identity before a physical write.

        This is deliberately write-ahead. If the process crashes, or a later
        target in a group fails, restart cannot trust the bytes that existed
        before this overwrite attempt. The next request safely rewrites them.
        """
        self._trusted_content.discard((number, chime_id))
        bindings = self._content_state.setdefault("bindings", {})
        slot = bindings.get(str(number))
        if isinstance(slot, dict):
            slot.pop(chime_id, None)
            if not slot:
                bindings.pop(str(number), None)
        binding.current_md5 = None
        binding.current_size = None
        binding.verified_at = time.time()
        self._persist_registry()
        self._persist_content_state()

    def _clear_target_content_locked(self, targets: set[str]) -> int:
        """Clear target content proof while the slot condition is held."""
        invalidated = 0
        for number, slot in self.slots.items():
            for chime_id, binding in slot.bindings.items():
                if chime_id not in targets:
                    continue
                if (
                    (number, chime_id) in self._trusted_content
                    or self._state_entry(number, chime_id) is not None
                    or binding.current_md5 is not None
                    or binding.current_size is not None
                ):
                    invalidated += 1
                self._trusted_content.discard((number, chime_id))
                bindings = self._content_state.setdefault("bindings", {})
                persisted_slot = bindings.get(str(number))
                if isinstance(persisted_slot, dict):
                    persisted_slot.pop(chime_id, None)
                    if not persisted_slot:
                        bindings.pop(str(number), None)
                binding.current_md5 = None
                binding.current_size = None
                binding.verified_at = time.time()

        self._persist_registry()
        self._persist_content_state()
        if invalidated:
            self._metric("tts_slot_content_lifecycle_invalidations", invalidated)
        return invalidated

    @asynccontextmanager
    async def target_lifecycle_guard(
        self, target_ids: Iterable[str], *, reason: str
    ):
        """Invalidate content and block new target leases through an action."""
        targets = {str(target_id) for target_id in target_ids if target_id}
        if not targets:
            yield 0
            return

        async with self._condition:
            for chime_id in targets:
                self._invalidating_targets[chime_id] = (
                    self._invalidating_targets.get(chime_id, 0) + 1
                )
            try:
                while any(
                    number in self._busy
                    and bool(
                        targets
                        & set(
                            self._busy_targets.get(
                                number, frozenset(slot.bindings)
                            )
                        )
                    )
                    for number, slot in self.slots.items()
                ):
                    await self._condition.wait()
                yield self._clear_target_content_locked(targets)
            finally:
                for chime_id in targets:
                    remaining = self._invalidating_targets.get(chime_id, 1) - 1
                    if remaining > 0:
                        self._invalidating_targets[chime_id] = remaining
                    else:
                        self._invalidating_targets.pop(chime_id, None)
                self._condition.notify_all()

    async def invalidate_target_content(
        self, target_ids: Iterable[str], *, reason: str
    ) -> int:
        """Durably revoke reusable content after a target lifecycle break."""
        async with self.target_lifecycle_guard(target_ids, reason=reason) as count:
            return count

    @staticmethod
    def _content_key(md5: str, size: int) -> str:
        return f"{md5}:{size}"

    @staticmethod
    def _device_identity(chime_id: str, info: dict[str, Any]) -> str | None:
        identity: dict[str, Any] = {"chime_id": chime_id}
        for key in (
            "mac",
            "macAddress",
            "serial",
            "serialNumber",
            "deviceId",
            "device_id",
            "id",
        ):
            value = info.get(key)
            if value:
                identity[key] = value
        firmware = (
            info.get("version")
            or info.get("firmware")
            or info.get("firmwareVersion")
        )
        if firmware:
            identity["firmware"] = firmware
        # A chime UUID plus firmware is not enough to distinguish replacement
        # hardware. Require at least one hardware/device identity field.
        if len(identity) <= (2 if firmware else 1):
            return None
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _boot_epoch(info: dict[str, Any], *, observed_at: float | None = None) -> float | None:
        """Estimate the current hardware boot epoch from device uptime."""
        raw_uptime = info.get("uptime")
        if raw_uptime is None:
            return None
        try:
            uptime = float(raw_uptime)
        except (TypeError, ValueError):
            return None
        if uptime < 0:
            return None
        return (time.time() if observed_at is None else observed_at) - uptime

    def _same_boot(self, expected: Any, observed: float | None) -> bool:
        try:
            persisted = float(expected)
        except (TypeError, ValueError):
            return False
        return observed is not None and abs(persisted - observed) <= self.boot_epoch_tolerance_s

    async def _refresh_target_boot_epochs(self, targets: list[Any]) -> None:
        """Invalidate reusable bytes when a target's hardware boot changes."""
        invalid = set()
        observed: dict[str, float] = {}
        for target in targets:
            chime_id = target.desc.chime_id
            try:
                info = await target.direct_client.info()
            except Exception:
                invalid.add(chime_id)
                continue
            epoch = self._boot_epoch(info)
            previous = self._device_boot_epochs.get(chime_id)
            if epoch is None or (
                previous is not None and not self._same_boot(previous, epoch)
            ):
                invalid.add(chime_id)
            if epoch is not None:
                observed[chime_id] = epoch

        if invalid:
            await self.invalidate_target_content(invalid, reason="boot_epoch_changed")
        self._device_boot_epochs.update(observed)

    def _entry_matches(
        self,
        entry: dict[str, Any] | None,
        *,
        md5: str,
        size: int,
        binding: DeviceSlotBinding,
    ) -> bool:
        if not entry:
            return False
        return (
            entry.get("source_md5") == md5
            and entry.get("source_size") == size
            and entry.get("device_slot") == binding.device_slot
            and entry.get("filename") == binding.filename
            and binding.current_md5 == md5
            and binding.current_size == size
        )

    def _slot_matches_trusted_content(
        self,
        number: int,
        target_ids: list[str],
        *,
        md5: str,
        size: int,
    ) -> bool:
        slot = self.slots[number]
        for chime_id in target_ids:
            binding = slot.bindings.get(chime_id)
            if binding is None or (number, chime_id) not in self._trusted_content:
                return False
            if not self._entry_matches(
                self._state_entry(number, chime_id),
                md5=md5,
                size=size,
                binding=binding,
            ):
                return False
        return True

    async def _restore_startup_state(self) -> None:
        """Restore optional content proof while parent readiness remains false."""
        self._trusted_content.clear()
        self._device_identities.clear()
        self._device_boot_epochs.clear()
        self._load_content_state()
        # The strict parent startup already proved each persisted slot binding.
        # A persisted content assignment is trusted across restart only when the
        # same physical device identity is observed and registry/content records
        # agree exactly. Otherwise the next request safely rewrites the slot.
        for target in self._targets.values():
            chime_id = target.desc.chime_id
            try:
                info = await target.direct_client.info()
            except Exception:
                self._metric("tts_slot_content_restart_invalidations")
                continue
            identity = self._device_identity(chime_id, info)
            boot_epoch = self._boot_epoch(info)
            if identity is None or boot_epoch is None:
                self._metric("tts_slot_content_restart_invalidations")
                continue
            self._device_identities[chime_id] = identity
            self._device_boot_epochs[chime_id] = boot_epoch
            for number, slot in self.slots.items():
                binding = slot.bindings.get(chime_id)
                entry = self._state_entry(number, chime_id)
                if entry is None:
                    continue
                try:
                    persisted_size = int(entry.get("source_size") or 0)
                except (TypeError, ValueError):
                    self._metric("tts_slot_content_restart_invalidations")
                    continue
                if (
                    binding is not None
                    and entry.get("device_identity") == identity
                    and self._same_boot(entry.get("device_boot_epoch"), boot_epoch)
                    and self._entry_matches(
                        entry,
                        md5=str(entry.get("source_md5") or ""),
                        size=persisted_size,
                        binding=binding,
                    )
                ):
                    self._trusted_content.add((number, chime_id))
                    self._metric("tts_slot_content_restart_validations")
                else:
                    self._metric("tts_slot_content_restart_invalidations")

    async def _acquire_slot_number_for_content(
        self,
        *,
        md5: str,
        size: int,
        target_ids: list[str],
    ) -> tuple[int, bool]:
        async with self._condition:
            while True:
                if any(
                    self._invalidating_targets.get(chime_id, 0) > 0
                    for chime_id in target_ids
                ):
                    await self._condition.wait()
                    continue
                free = [
                    number
                    for number in sorted(self.slots)
                    if number not in self._busy
                ]
                if free:
                    matches = [
                        number
                        for number in free
                        if self._slot_matches_trusted_content(
                            number, target_ids, md5=md5, size=size
                        )
                    ]
                    if matches:
                        number = min(
                            matches,
                            key=lambda candidate: self.slots[candidate].updated_at,
                        )
                        content_match = True
                    else:
                        order = [
                            self._next_slot,
                            1 if self._next_slot == 2 else 2,
                        ]
                        rank = {candidate: index for index, candidate in enumerate(order)}
                        number = min(
                            free,
                            key=lambda candidate: (
                                self.slots[candidate].updated_at,
                                rank.get(candidate, len(rank)),
                            ),
                        )
                        content_match = False
                    self._busy.add(number)
                    self._busy_targets[number] = frozenset(target_ids)
                    self._next_slot = 1 if number == 2 else 2
                    return number, content_match
                await self._condition.wait()

    async def prepare(
        self, mp3: bytes, targets: Iterable[Any]
    ) -> PreparedDynamicSlot:
        if not self.ready:
            raise DynamicSlotUnavailable(
                self.last_error or "dynamic TTS slots are not ready"
            )
        target_list = [target for target in targets if target is not None]
        if not target_list:
            raise DynamicSlotUnavailable("no dynamic TTS targets")

        await self._refresh_target_boot_epochs(target_list)

        prepare_started = perf_counter()
        md5 = hashlib.md5(mp3).hexdigest()
        size = len(mp3)
        target_ids = [target.desc.chime_id for target in target_list]

        acquire_started = perf_counter()
        number, selection_hit = await self._acquire_slot_number_for_content(
            md5=md5, size=size, target_ids=target_ids
        )
        self._fresh_lease_content.difference_update(
            key for key in tuple(self._fresh_lease_content) if key[0] == number
        )
        content_epochs = {chime_id: self._external_epochs.get(chime_id, 0) for chime_id in target_ids}
        acquire_ms = (perf_counter() - acquire_started) * 1000.0
        self._observe("slot_acquire_ms", acquire_ms)

        timings = {
            "slot_acquire_ms": acquire_ms,
            "slot_preflight_ms": 0.0,
            "slot_direct_upload_ms": 0.0,
            "slot_sync_ms": 0.0,
            "slot_settle_ms": 0.0,
        }
        overwrites = 0
        skips = 0
        pending_generations: dict[str, int] = {}

        try:
            slot = self.slots[number]
            for target in target_list:
                chime_id = target.desc.chime_id
                binding = slot.bindings.get(chime_id)
                if binding is None:
                    raise DynamicSlotUnavailable(
                        f"slot {number}: no proven binding for {target.desc.name}"
                    )

                preflight_started = perf_counter()
                track = await self._preflight_binding(slot, binding)
                if track is None:
                    raise DynamicSlotUnavailable("owned ringtone is absent from Protect device inventory; refusing possible default-tone fallback")
                preflight_ms = (perf_counter() - preflight_started) * 1000.0
                timings["slot_preflight_ms"] += preflight_ms
                self._observe("slot_preflight_ms", preflight_ms)

                entry = self._state_entry(number, chime_id)
                trusted_match = (
                    (number, chime_id) in self._trusted_content
                    and self._entry_matches(
                        entry, md5=md5, size=size, binding=binding
                    )
                    and _fingerprint(track) == (md5, size)
                )
                if trusted_match:
                    self._fresh_lease_content.add((number, chime_id))
                    skips += 1
                    self._metric("tts_slot_overwrite_skips")
                    continue

                previous_generation = int((entry or {}).get("write_generation") or 0)
                self._invalidate_content_proof(number, chime_id, binding)
                self._pending_writes[(number, chime_id)] = (md5, size)

                upload_started = perf_counter()
                await target.direct_client.overwrite_owned_slot(
                    slot=binding.device_slot,
                    filename=binding.filename,
                    mp3_bytes=mp3,
                    owner=SERVICE_OWNER,
                    builtin=False,
                    experiment_enabled=True,
                )
                direct_upload_ms = (perf_counter() - upload_started) * 1000.0
                timings["slot_direct_upload_ms"] += direct_upload_ms
                self._observe("slot_direct_upload_ms", direct_upload_ms)

                sync_ms, settle_ms, fresh_content = await self._wait_for_device_sync(
                    binding, expected_md5=md5, expected_size=size
                )
                if fresh_content:
                    self._fresh_lease_content.add((number, chime_id))
                timings["slot_sync_ms"] += sync_ms
                timings["slot_settle_ms"] += settle_ms

                pending_generations[chime_id] = previous_generation + 1
                overwrites += 1
                self._metric("tts_slot_overwrites")

            # Commit application-authoritative content identity only after every
            # requested target completed successfully. A partial failure leaves
            # registry/state conservative and forces a later safe rewrite.
            if any(content_epochs[chime_id] != self._external_epochs.get(chime_id, 0) for chime_id in target_ids):
                raise DynamicSlotUnavailable("Protect changed ringtone state during announcement preparation; retry after synchronization")
            now = time.time()
            for target in target_list:
                chime_id = target.desc.chime_id
                binding = slot.bindings[chime_id]
                old = self._state_entry(number, chime_id) or {}
                binding.current_md5 = md5
                binding.current_size = size
                binding.verified_at = now
                entry = {
                    "content_key": self._content_key(md5, size),
                    "source_md5": md5,
                    "source_size": size,
                    "device_slot": binding.device_slot,
                    "filename": binding.filename,
                    "device_identity": self._device_identities.get(chime_id),
                    "device_boot_epoch": self._device_boot_epochs.get(chime_id),
                    "write_generation": pending_generations.get(
                        chime_id, int(old.get("write_generation") or 0)
                    ),
                    "written_at": (
                        now if chime_id in pending_generations
                        else old.get("written_at", now)
                    ),
                    "last_used_at": now,
                }
                self._set_state_entry(number, chime_id, entry)
                self._trusted_content.add((number, chime_id))

            slot.updated_at = now
            self._persist_registry()
            self._persist_content_state()

            if overwrites == 0:
                self._metric("tts_slot_content_hits")
            else:
                self._metric("tts_slot_content_misses")
                if skips:
                    self._metric("tts_slot_content_partial_hits")

            prepare_ms = (perf_counter() - prepare_started) * 1000.0
            self._observe("slot_prepare_ms", prepare_ms)
            self.last_prepare = {
                **timings,
                "slot_prepare_ms": prepare_ms,
                "logical_slot": number,
                "target_count": len(target_list),
                "selection_content_match": selection_hit,
                "content_hit": overwrites == 0,
                "overwrites": overwrites,
                "overwrite_skips": skips,
                "content_md5_prefix": md5[:12],
                "content_size": size,
            }
            return PreparedDynamicSlot(
                manager=self,
                logical_slot=number,
                ringtone_id=slot.protect_ringtone_id,
                duration_ms=estimate_mp3_duration_ms(mp3),
                content_md5=md5,
                content_epochs=content_epochs,
            )
        except asyncio.CancelledError:
            await self.release_now(number)
            raise
        except Exception:
            await self.release_now(number)
            raise
        finally:
            for chime_id in target_ids:
                self._pending_writes.pop((number, chime_id), None)

    async def shutdown(self) -> None:
        await super().shutdown()
        self._busy_targets.clear()
        self._fresh_lease_content.clear()

    async def release_now(self, number: int) -> None:
        async with self._condition:
            self._busy.discard(number)
            self._busy_targets.pop(number, None)
            self._fresh_lease_content.difference_update(
                key for key in tuple(self._fresh_lease_content) if key[0] == number
            )
            self._condition.notify_all()

    @staticmethod
    def _reported_filename(track: dict[str, Any]) -> str:
        raw = (
            track.get("fileName")
            or track.get("filename")
            or track.get("name")
            or ""
        )
        filename = str(raw)
        if filename and not filename.endswith(".mp3"):
            filename = f"{filename}.mp3"
        return filename

    async def _settle(self) -> float:
        if not self.device_settle_delay_s:
            return 0.0
        started = perf_counter()
        await asyncio.sleep(self.device_settle_delay_s)
        elapsed = (perf_counter() - started) * 1000.0
        self._observe("slot_settle_ms", elapsed)
        return elapsed

    async def _wait_for_device_sync(
        self,
        binding: DeviceSlotBinding,
        *,
        expected_md5: str,
        expected_size: int,
    ) -> tuple[float, float, bool]:
        """Prefer fresh Protect evidence; tolerate only exact-owned stale metadata."""
        started = perf_counter()
        deadline = asyncio.get_running_loop().time() + self.device_sync_timeout_s
        stale_owned_track_seen = False

        while True:
            chime = await self.get_chime(binding.chime_id)
            tracks = chime.get("speakerTrackList") or []
            track = self._reported_binding_track(tracks, binding)

            if track is not None:
                filename = self._reported_filename(track)
                if not filename:
                    stale_owned_track_seen = False
                elif filename != binding.filename:
                    sync_ms = (perf_counter() - started) * 1000.0
                    self._observe("slot_sync_ms", sync_ms)
                    self._metric("tts_slot_sync_ownership_drift")
                    raise DynamicSlotUnavailable(
                        f"chime {binding.chime_id}: TTS slot ownership proof no longer matches"
                    )
                elif _fingerprint(track) == (expected_md5, expected_size):
                    sync_ms = (perf_counter() - started) * 1000.0
                    self._observe("slot_sync_ms", sync_ms)
                    self._metric("tts_slot_sync_successes")
                    settle_ms = await self._settle()
                    return sync_ms, settle_ms, True
                else:
                    stale_owned_track_seen = True
            else:
                stale_owned_track_seen = False

            if asyncio.get_running_loop().time() >= deadline:
                sync_ms = (perf_counter() - started) * 1000.0
                self._observe("slot_sync_ms", sync_ms)
                if stale_owned_track_seen:
                    self._metric("tts_slot_sync_stale_inventory_accepts")
                    settle_ms = await self._settle()
                    return sync_ms, settle_ms, False
                self._metric("tts_slot_sync_timeouts")
                raise DynamicSlotUnavailable(
                    f"chime {binding.chime_id}: overwritten TTS slot did not synchronize"
                )

            await asyncio.sleep(self.poll_interval_s)

    def status(self) -> dict[str, Any]:
        payload = super().status()
        assignments: dict[str, Any] = {}
        for number, slot in sorted(self.slots.items()):
            per_chime = {}
            for chime_id, binding in slot.bindings.items():
                entry = self._state_entry(number, chime_id)
                if not entry:
                    continue
                per_chime[chime_id] = {
                    "device_slot": binding.device_slot,
                    "filename": binding.filename,
                    "content_key_prefix": str(entry.get("content_key") or "")[:12],
                    "source_size": entry.get("source_size"),
                    "write_generation": entry.get("write_generation"),
                    "written_at": entry.get("written_at"),
                    "last_used_at": entry.get("last_used_at"),
                    "trusted": (number, chime_id) in self._trusted_content,
                }
            if per_chime:
                assignments[str(number)] = per_chime
        payload["content_reuse"] = {
            "trusted_bindings": len(self._trusted_content),
            "assignments": assignments,
            "last_prepare": self.last_prepare,
        }
        return payload
