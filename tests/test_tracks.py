import json

import pytest

from app.tracks import SERVICE_OWNER, TrackRecord, TrackRegistry, TrackReconciler


def test_track_record_round_trip_has_all_identities(tmp_path):
    record = TrackRecord(
        logical_key="door-open", kind="dynamic_tts", owner=SERVICE_OWNER,
        nvr_ringtone_id="n1", nvr_ringtone_name="ua-door-open",
        device_slot=3, device_filename="3.mp3", device_hash="abc",
        disk_path=str(tmp_path / "door.mp3"), created_at=1.0,
        updated_at=2.0, last_used_at=3.0, pinned=False,
    )
    assert TrackRecord.from_dict(record.to_dict()) == record


def test_reconcile_marks_missing_without_claiming_unknown(tmp_path):
    registry = TrackRegistry(tmp_path / "registry.json")
    owned = TrackRecord("owned", owner=SERVICE_OWNER, nvr_ringtone_id="gone", device_hash="gone")
    foreign = TrackRecord("foreign", owner="user", nvr_ringtone_id="user-id")
    registry.put(owned); registry.put(foreign)
    report = TrackReconciler(registry).reconcile(
        nvr_snapshot=[{"id": "builtin", "name": "Built In", "isDefault": True}],
        speaker_tracks=[{"md5": "other", "fileName": "0.mp3"}],
    )
    assert report["owned"]["nvr"] == "missing"
    assert report["owned"]["device"] == "missing"
    assert report["foreign"]["owned"] is False
    assert "builtin" not in registry.records


@pytest.mark.asyncio
async def test_gc_deletes_only_owned_nvr_and_disk_never_device(tmp_path):
    disk = tmp_path / "old.mp3"; disk.write_bytes(b"mp3")
    registry = TrackRegistry(tmp_path / "registry.json", max_dynamic=1)
    oldest = TrackRecord("old", owner=SERVICE_OWNER, nvr_ringtone_id="owned-id",
                         device_slot=2, device_filename="2.mp3", disk_path=str(disk),
                         last_used_at=1.0)
    newest = TrackRecord("new", owner=SERVICE_OWNER, nvr_ringtone_id="new-id", last_used_at=2.0)
    foreign = TrackRecord("foreign", owner="user", nvr_ringtone_id="foreign-id", last_used_at=0.0)
    for record in (oldest, newest, foreign): registry.put(record)
    deleted = []
    report = await TrackReconciler(registry, delete_nvr=lambda rid: _record(deleted, rid)).evict_to_limit()
    assert deleted == ["owned-id"]
    assert not disk.exists()
    assert "old" not in registry.records
    assert "foreign" in registry.records
    assert report[0]["device_delete"] == "skipped: semantics unproven"


async def _record(items, value):
    items.append(value)
    return True


@pytest.mark.asyncio
async def test_startup_reconcile_loads_snapshots_and_enforces_cap(tmp_path):
    registry = TrackRegistry(tmp_path / "registry.json", max_dynamic=0)
    registry.put(TrackRecord("owned", owner=SERVICE_OWNER, nvr_ringtone_id="n1"))
    deleted = []
    reconciler = TrackReconciler(registry, delete_nvr=lambda rid: _record(deleted, rid))
    report = await reconciler.startup(
        load_nvr=lambda: _value([{"id": "n1", "name": "ua-owned"}]),
        load_chimes=lambda: _value([{"speakerTrackList": []}]),
    )
    assert report["reconciled"]["owned"]["nvr"] == "present"
    assert deleted == ["n1"]


@pytest.mark.asyncio
async def test_pinned_ab_owned_slots_survive_startup_reconciliation(tmp_path):
    path = tmp_path / "registry.json"
    registry = TrackRegistry(path, max_dynamic=0)
    for suffix, ringtone_id, slot, filename, digest in (
        ("a", "nvr-a", 6, "slot-a.mp3", "hash-a"),
        ("b", "nvr-b", 7, "slot-b.mp3", "hash-b"),
    ):
        registry.put(TrackRecord(
            f"ua-tts-slot-{suffix}",
            kind="dynamic_slot_experiment",
            owner=SERVICE_OWNER,
            nvr_ringtone_id=ringtone_id,
            device_slot=slot,
            device_filename=filename,
            device_hash=digest,
            pinned=True,
        ))

    restored = TrackRegistry(path, max_dynamic=0)
    restored.load()
    report = await TrackReconciler(restored).startup(
        load_nvr=lambda: _value([
            {"id": "nvr-a", "name": "ua-tts-slot-a"},
            {"id": "nvr-b", "name": "ua-tts-slot-b"},
        ]),
        load_chimes=lambda: _value([{"speakerTrackList": [
            {"fileName": "slot-a.mp3", "md5": "hash-a"},
            {"fileName": "slot-b.mp3", "md5": "hash-b"},
        ]}]),
    )

    assert report["evicted"] == []
    assert set(restored.records) == {"ua-tts-slot-a", "ua-tts-slot-b"}
    assert all(item["nvr"] == "present" and item["device"] == "present"
               for item in report["reconciled"].values())
    assert all(record.pinned for record in restored.records.values())


async def _value(value):
    return value


def test_pinned_owned_track_is_not_evictable(tmp_path):
    registry = TrackRegistry(tmp_path / "registry.json", max_dynamic=0)
    registry.put(TrackRecord("pinned", owner=SERVICE_OWNER, pinned=True))
    assert registry.eviction_candidates() == []


def test_registry_persists_owner_and_timestamps(tmp_path):
    path = tmp_path / "registry.json"
    registry = TrackRegistry(path); registry.put(TrackRecord("x", owner=SERVICE_OWNER, created_at=4))
    restored = TrackRegistry(path); restored.load()
    assert restored.records["x"].owner == SERVICE_OWNER
    assert json.loads(path.read_text())["x"]["created_at"] == 4


@pytest.mark.asyncio
async def test_gc_runs_are_serialized(tmp_path):
    import asyncio

    registry = TrackRegistry(tmp_path / "registry.json", max_dynamic=0)
    registry.put(TrackRecord("one", nvr_ringtone_id="n1"))
    active = 0
    peak = 0

    async def delete(_):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return True

    reconciler = TrackReconciler(registry, delete_nvr=delete)
    await asyncio.gather(reconciler.evict_to_limit(), reconciler.evict_to_limit())

    assert peak == 1
