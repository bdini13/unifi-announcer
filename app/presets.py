"""Recoverable Protect preset mutations; no device operations or playback."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import Awaitable, Callable

from app.audio.cache import RingtoneIndex
from app.persistence import atomic_json
from app.playback.dynamic_slots import estimate_mp3_duration_ms
from app.tracks import SERVICE_OWNER, TrackRecord, TrackRegistry, TrackReconciler


class PresetUpdateError(RuntimeError):
    """A preset update did not reach a verified, unambiguous commit."""


class PresetWriter:
    """Serialize callers externally with the shared ringtone upload lock.

    A replacement needs a spare Protect slot. The previous recording remains
    intact until the new identity has been verified and durably registered.
    The journal reconciles interrupted operations on the next preset write.
    Unknown upload outcomes never authorize deleting a newly discovered ID.
    """

    def __init__(self, *, registry: TrackRegistry, index: RingtoneIndex,
                 reconciler: TrackReconciler,
                 list_ringtones: Callable[[], Awaitable[list[dict]]],
                 upload: Callable[[str, bytes], Awaitable[dict]],
                 delete: Callable[[str], Awaitable[bool]], max_bytes: int):
        self.registry, self.index, self.reconciler = registry, index, reconciler
        self.list_ringtones, self.upload, self.delete = list_ringtones, upload, delete
        self.max_bytes = max_bytes
        self.journal = registry.path.with_name("preset_update.json")

    @staticmethod
    def _id(tone: dict) -> str:
        return str(tone.get("id") or tone.get("_id") or "")

    def _write_journal(self, pending: dict | None) -> None:
        atomic_json(self.journal, {"version": 1, "pending": pending})

    def _record(self, name: str, tone: dict, *, uploaded: bool,
                duration_ms: int | None = None) -> TrackRecord:
        old = self.registry.records.get(name.lower())
        record = replace(old) if old else TrackRecord(name.lower(), owner="unknown")
        identity_changed = record.nvr_ringtone_id != self._id(tone)
        if identity_changed:
            record.duration_ms = None
            record.device_slot = record.device_filename = record.device_hash = None
            record.disk_path = None
            record.owner = "unknown"
        record.kind, record.pinned = "preset", True
        record.nvr_ringtone_id = self._id(tone)
        record.nvr_ringtone_name = str(tone["name"])
        if uploaded:
            record.owner, record.duration_ms = SERVICE_OWNER, duration_ms
        return record

    async def _recover(self) -> dict | None:
        try:
            document = json.loads(self.journal.read_text())
        except FileNotFoundError:
            return None
        if not isinstance(document, dict) or document.get("version") != 1:
            raise PresetUpdateError("Invalid preset update journal; review it before retrying")
        pending = document.get("pending")
        if pending is None:
            return None
        if not isinstance(pending, dict) or not isinstance(pending.get("name"), str):
            raise PresetUpdateError("Invalid pending preset update; review it before retrying")
        name = pending["name"]
        snapshot = await self.list_ringtones()
        by_id = {self._id(tone): tone for tone in snapshot}
        old = pending["old_tone"]
        new = pending.get("new_tone")
        old_present = old and self._id(old) in by_id
        if new is None:
            # The request may have succeeded before its response was lost.
            # A name/delta alone cannot establish ownership of the new object.
            unknown = [tone for tone in snapshot
                       if str(tone.get("name", "")).lower() == name.lower()
                       and self._id(tone) not in pending["before_ids"]]
            if unknown:
                self.index.invalidate(name)
                raise PresetUpdateError(
                    f"Upload outcome for '{name}' is unknown; review duplicate ringtone IDs "
                    "before retrying. The previous preset was not deleted."
                )
        elif self._id(new) in by_id and not old_present:
            self.registry.put(self._record(
                name, new, uploaded=True, duration_ms=pending["duration_ms"]), durable=True)
            await self.index.force_refresh()
            if (self.index.get(name) or {}).get("id") != self._id(new):
                raise PresetUpdateError("Recovered preset identity is not uniquely resolvable")
            self._write_journal(None)
            return pending
        elif old_present and self._id(new) in by_id:
            # The old object survived: roll back only our response-verified ID.
            if not await self.delete(self._id(new)):
                raise PresetUpdateError(
                    f"Preset '{name}' replacement cleanup failed; previous recording retained; "
                    "retry the update to reconcile the pending transaction"
                )
            if self._id(new) in {self._id(t) for t in await self.list_ringtones()}:
                raise PresetUpdateError("Replacement deletion was not reflected in Protect inventory")
        elif old and not old_present:
            raise PresetUpdateError("Both preset identities are missing; review the update journal")
        if old_present:
            self.registry.put(TrackRecord.from_dict(pending["old_record"]), durable=True)
        await self.index.force_refresh()
        self._write_journal(None)
        return None

    async def write(self, name: str, mp3: bytes, *, force: bool = False) -> str:
        if not isinstance(mp3, bytes) or not mp3 or len(mp3) > self.max_bytes:
            raise ValueError(f"Preset MP3 must contain 1 to {self.max_bytes} bytes")
        content_hash = hashlib.sha256(mp3).hexdigest()
        recovered = await self._recover()
        if (recovered and recovered["name"].lower() == name.lower()
                and recovered["content_hash"] == content_hash):
            return self._id(recovered["new_tone"])
        snapshot = await self.list_ringtones()
        matches = [tone for tone in snapshot
                   if str(tone.get("name", "")).lower() == name.lower()]
        if len(matches) > 1:
            raise PresetUpdateError(f"Preset '{name}' has duplicate ringtone IDs; reconcile them first")
        old = matches[0] if matches else None
        if old and not self._id(old):
            raise PresetUpdateError("Existing preset has no ringtone ID")
        if old:
            # Persist the caller's decision to keep this logical track before
            # any upload/cancellation boundary. Otherwise startup migration
            # could delete a legacy dynamic recording while replacement is
            # still journaled but uncommitted. Rollback preserves this pin.
            self.registry.put(self._record(name, old, uploaded=False), durable=True)
            if not force:
                await self.index.force_refresh()
                return self._id(old)
        # In particular, a colliding legacy dynamic record is not GC headroom.
        evicted = await self.reconciler.ensure_capacity(
            snapshot, needed=1, protected_ids={self._id(old)} if old else set())
        if evicted:
            snapshot = await self.list_ringtones()
            await self.index.force_refresh()
        old_record = self.registry.records.get(name.lower())
        if old and (old_record is None or old_record.nvr_ringtone_id != self._id(old)):
            old_record = self._record(name, old, uploaded=False)
        pending = {
            "name": name, "old_tone": old,
            "old_record": old_record.to_dict() if old_record else None,
            "new_tone": None, "before_ids": [self._id(tone) for tone in snapshot],
            "duration_ms": estimate_mp3_duration_ms(mp3), "content_hash": content_hash,
        }
        self._write_journal(pending)
        self.index.invalidate(name)
        try:
            created = await self.upload(name, mp3)
            created_id = self._id(created) if isinstance(created, dict) else ""
            if (not created_id or created_id in pending["before_ids"]
                    or str(created.get("name", name)).lower() != name.lower()):
                raise PresetUpdateError("Upload response did not identify a new preset; previous recording retained")
            pending["new_tone"] = {**created, "id": created_id, "name": name}
            self._write_journal(pending)
            snapshot = await self.list_ringtones()
            verified = [tone for tone in snapshot if self._id(tone) == created_id
                        and str(tone.get("name", "")).lower() == name.lower()]
            if len(verified) != 1:
                raise PresetUpdateError("New preset identity was not verified in Protect inventory")
            matching_ids = {self._id(tone) for tone in snapshot
                            if str(tone.get("name", "")).lower() == name.lower()}
            expected_ids = {created_id} | ({self._id(old)} if old else set())
            if matching_ids != expected_ids:
                raise PresetUpdateError("Preset inventory changed concurrently; previous recording retained")
            self.registry.put(self._record(
                name, pending["new_tone"], uploaded=True,
                duration_ms=pending["duration_ms"]), durable=True)
            if old:
                if not await self.delete(self._id(old)):
                    raise PresetUpdateError("Protect rejected deletion of the previous preset")
                if self._id(old) in {self._id(t) for t in await self.list_ringtones()}:
                    raise PresetUpdateError("Previous preset deletion was not reflected in Protect inventory")
            await self.index.force_refresh()
            if (self.index.get(name) or {}).get("id") != created_id:
                raise PresetUpdateError("Updated preset identity is not uniquely resolvable")
            self._write_journal(None)
            return created_id
        except Exception as error:
            try:
                recovered = await self._recover()
            except Exception as recovery_error:
                raise PresetUpdateError(f"{error}; recovery pending: {recovery_error}") from error
            if recovered:
                return self._id(recovered["new_tone"])
            raise
