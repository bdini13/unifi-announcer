"""Owned track registry, reconciliation, and conservative garbage collection."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path
import time
from typing import Awaitable, Callable, Iterable
import asyncio

log = logging.getLogger(__name__)
SERVICE_OWNER = "unifi_announcer"
DEVICE_DELETE_UNPROVEN = "skipped: semantics unproven"


@dataclass
class TrackRecord:
    logical_key: str
    kind: str = "dynamic_tts"
    owner: str = SERVICE_OWNER
    nvr_ringtone_id: str | None = None
    nvr_ringtone_name: str | None = None
    device_slot: int | None = None
    device_filename: str | None = None
    device_hash: str | None = None
    disk_path: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    pinned: bool = False

    @property
    def last_used(self) -> float:  # compatibility with the pre-Phase-12 model
        return self.last_used_at

    @last_used.setter
    def last_used(self, value: float) -> None:
        self.last_used_at = value

    @property
    def backend_state(self) -> str:
        if self.nvr_ringtone_id and (self.device_filename or self.device_hash or self.device_slot is not None):
            return "both"
        if self.nvr_ringtone_id:
            return "nvr"
        if self.device_filename or self.device_hash or self.device_slot is not None:
            return "device"
        return "missing"

    def to_dict(self) -> dict:
        value = asdict(self)
        value["backend_state"] = self.backend_state
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "TrackRecord":
        fields = cls.__dataclass_fields__
        data = {key: item for key, item in value.items() if key in fields}
        # Upgrade records written by the older registry without ever claiming
        # ownership of artifacts whose provenance was not recorded.
        data.setdefault("owner", "unknown")
        if "last_used" in value and "last_used_at" not in data:
            data["last_used_at"] = value["last_used"]
        return cls(**data)


class TrackRegistry:
    def __init__(self, path: str | Path | None = None, *, max_dynamic: int | None = None) -> None:
        self._path = str(path or Path(os.getenv("DATA_DIR", "/data")) / "track_registry.json")
        self.max_dynamic = int(os.getenv("MAX_DYNAMIC_TRACKS", "32")) if max_dynamic is None else max_dynamic
        self.records: dict[str, TrackRecord] = {}
        self._tracks = self.records  # compatibility for status/debug callers

    @property
    def path(self) -> Path:
        return Path(self._path)

    def get(self, key: str) -> TrackRecord | None:
        record = self.records.get(key)
        if record:
            record.last_used_at = time.time()
            record.updated_at = record.last_used_at
        return record

    def put(self, record: TrackRecord) -> None:
        record.updated_at = max(record.updated_at, record.created_at)
        self.records[record.logical_key] = record
        self.persist()

    def remove(self, key: str) -> None:
        self.records.pop(key, None)
        self.persist()

    def load(self) -> None:
        try:
            with self.path.open() as handle:
                raw = json.load(handle)
            self.records.clear()
            self.records.update({key: TrackRecord.from_dict(value) for key, value in raw.items()})
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as exc:
            log.warning("track registry load failed; keeping empty registry: %s", exc)

    def persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps({key: record.to_dict() for key, record in self.records.items()}, indent=2))
            os.replace(temp, self.path)
        except OSError as exc:
            log.warning("track registry persist failed: %s", exc)

    def eviction_candidates(self) -> list[TrackRecord]:
        dynamic = [r for r in self.records.values()
                   if r.owner == SERVICE_OWNER and r.kind == "dynamic_tts" and not r.pinned]
        overflow = max(0, len(dynamic) - self.max_dynamic)
        return sorted(dynamic, key=lambda record: record.last_used_at)[:overflow]

    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        owned = 0
        for record in self.records.values():
            kinds[record.kind] = kinds.get(record.kind, 0) + 1
            owned += record.owner == SERVICE_OWNER
        return {"total": len(self.records), "owned": owned, "by_kind": kinds,
                "max_dynamic": self.max_dynamic}


class TrackReconciler:
    """Compare identities and GC only artifacts explicitly owned by this service."""

    def __init__(self, registry: TrackRegistry,
                 delete_nvr: Callable[[str], Awaitable[bool]] | None = None) -> None:
        self.registry = registry
        self.delete_nvr = delete_nvr
        self._gc_lock = asyncio.Lock()

    def reconcile(self, *, nvr_snapshot: Iterable[dict], speaker_tracks: Iterable[dict]) -> dict:
        nvr_ids = {str(item.get("id") or item.get("_id")) for item in nvr_snapshot
                   if item.get("id") or item.get("_id")}
        device_hashes = {str(item.get("md5") or item.get("hash")) for item in speaker_tracks
                         if item.get("md5") or item.get("hash")}
        device_names = {str(item.get("fileName") or item.get("filename")) for item in speaker_tracks
                        if item.get("fileName") or item.get("filename")}
        report = {}
        for key, record in self.registry.records.items():
            report[key] = {
                "owned": record.owner == SERVICE_OWNER,
                "nvr": "present" if record.nvr_ringtone_id in nvr_ids else
                       ("missing" if record.nvr_ringtone_id else "untracked"),
                "device": "present" if ((record.device_hash and record.device_hash in device_hashes) or
                                            (record.device_filename and record.device_filename in device_names)) else
                          ("missing" if (record.device_hash or record.device_filename or record.device_slot is not None)
                           else "untracked"),
            }
        return report

    async def evict_to_limit(self) -> list[dict]:
        async with self._gc_lock:
            results = []
            for record in self.registry.eviction_candidates():
                result = {"logical_key": record.logical_key, "nvr_delete": "not-applicable",
                          "device_delete": DEVICE_DELETE_UNPROVEN, "disk_delete": "not-applicable"}
                if record.nvr_ringtone_id and self.delete_nvr is not None:
                    deleted = await self.delete_nvr(record.nvr_ringtone_id)
                    result["nvr_delete"] = "deleted" if deleted else "failed"
                    if not deleted:
                        results.append(result)
                        continue
                if record.disk_path:
                    try:
                        Path(record.disk_path).unlink(missing_ok=True)
                        result["disk_delete"] = "deleted"
                    except OSError:
                        result["disk_delete"] = "failed"
                        results.append(result)
                        continue
                # Device flash is deliberately not touched. Its deletion semantics
                # have not been proven and a slot may contain a built-in/user tone.
                self.registry.remove(record.logical_key)
                results.append(result)
            return results

    async def startup(self, *, load_nvr, load_chimes) -> dict:
        nvr_snapshot, chimes = await load_nvr(), await load_chimes()
        speaker_tracks = [track for chime in chimes for track in (chime.get("speakerTrackList") or [])]
        reconciled = self.reconcile(nvr_snapshot=nvr_snapshot, speaker_tracks=speaker_tracks)
        evicted = await self.evict_to_limit()
        return {"reconciled": reconciled, "evicted": evicted}
