"""Preset mutations exercise real persistence/index/GC with an inert controller."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.audio.cache import RingtoneIndex
from app.presets import PresetUpdateError, PresetWriter
from app.playback.fixed_slots import DynamicTtsSlotManager
from app.tracks import RingtoneCapacityError, TrackRecord, TrackReconciler, TrackRegistry


class Controller:
    def __init__(self):
        self.tones = [{"id": "old", "name": "alert"}]
        self.calls = []
        self.upload_error = None
        self.failed_deletes = set()
        self.delete_then_raise = None
        self.omit_upload_id = False
        self.upload_count = 0

    async def list(self):
        # Deliberately place the old same-name identity last: name lookup is
        # not valid evidence for identifying a newly uploaded recording.
        return [dict(tone) for tone in reversed(self.tones)]

    async def upload(self, name, mp3):
        self.calls.append(("upload", name))
        if self.upload_error:
            raise self.upload_error
        self.upload_count += 1
        created = {"id": f"new-{self.upload_count}", "name": name}
        self.tones.append(created)
        return {} if self.omit_upload_id else created

    async def delete(self, identity):
        self.calls.append(("delete", identity))
        if identity in self.failed_deletes:
            return False
        self.tones = [tone for tone in self.tones if tone["id"] != identity]
        if identity == "old" and self.delete_then_raise:
            raise self.delete_then_raise
        return True


@pytest.fixture
def preset_writer(tmp_path):
    controller = Controller()
    registry = TrackRegistry(tmp_path / "tracks.json")
    registry.put(TrackRecord("alert", "preset", nvr_ringtone_id="old", duration_ms=1000))
    index = RingtoneIndex(controller.list)
    reconciler = TrackReconciler(registry, controller.delete, max_total=6)
    writer = PresetWriter(registry=registry, index=index, reconciler=reconciler,
                          list_ringtones=controller.list, upload=controller.upload,
                          delete=controller.delete, max_bytes=1024)
    return writer, controller


def remaining(controller):
    return {tone["id"] for tone in controller.tones}


@pytest.mark.asyncio
async def test_failed_upload_preserves_previous_recording(preset_writer):
    writer, controller = preset_writer
    controller.upload_error = OSError("upload unavailable")
    with pytest.raises(OSError, match="upload unavailable"):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old"}
    assert writer.registry.records["alert"].nvr_ringtone_id == "old"
    assert controller.calls == [("upload", "alert")]
    assert json.loads(writer.journal.read_text())["pending"] is None


@pytest.mark.asyncio
async def test_rejected_old_delete_rolls_back_exact_new_identity(preset_writer):
    writer, controller = preset_writer
    controller.failed_deletes.add("old")
    with pytest.raises(PresetUpdateError, match="rejected deletion"):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old"}
    assert writer.registry.records["alert"].nvr_ringtone_id == "old"
    assert writer.index.get("alert")["id"] == "old"
    assert controller.calls == [("upload", "alert"), ("delete", "old"), ("delete", "new-1")]


@pytest.mark.asyncio
async def test_rollback_failure_keeps_journal_and_rejects_ambiguous_playback(preset_writer):
    writer, controller = preset_writer
    controller.failed_deletes.update({"old", "new-1"})
    with pytest.raises(PresetUpdateError, match="recovery pending"):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old", "new-1"}
    assert json.loads(writer.journal.read_text())["pending"]["new_tone"]["id"] == "new-1"
    await writer.index.force_refresh()
    with pytest.raises(RuntimeError, match="ambiguous"):
        writer.index.get("alert")
    controller.failed_deletes.clear()
    assert await writer.write("alert", b"new audio", force=True) == "new-2"
    assert remaining(controller) == {"new-2"}


@pytest.mark.asyncio
async def test_success_commits_exact_new_id_before_retiring_old(preset_writer):
    writer, controller = preset_writer
    original_delete = writer.delete

    async def observed_delete(identity):
        if identity == "old":
            saved = json.loads(writer.registry.path.read_text())
            assert saved["alert"]["nvr_ringtone_id"] == "new-1"
        return await original_delete(identity)

    writer.delete = observed_delete
    assert await writer.write("alert", b"new audio", force=True) == "new-1"
    assert remaining(controller) == {"new-1"}
    assert writer.index.get("alert")["id"] == "new-1"
    record = writer.registry.records["alert"]
    assert record.kind == "preset" and record.pinned
    assert record.duration_ms != 1000  # Never retain the previous recording's proof.


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_legacy_dynamic_saved_as_preset_survives_capacity_sweep(preset_writer, force):
    writer, controller = preset_writer
    record = writer.registry.records["alert"]
    record.kind = "dynamic_tts"
    record.pinned = False
    identity = await writer.write("alert", b"new audio", force=force)
    saved = writer.registry.records["alert"]
    assert saved.kind == "preset" and saved.pinned
    writer.reconciler.max_total = 1
    with pytest.raises(RingtoneCapacityError):
        await writer.reconciler.ensure_capacity(await controller.list())
    assert remaining(controller) == {identity}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel_upload", "reject_delete"])
async def test_interrupted_legacy_conversion_survives_real_startup_migration(preset_writer, failure):
    writer, controller = preset_writer
    writer.registry.records["alert"].kind = "dynamic_tts"
    controller.tones[0].update(md5="a" * 32, size=100)
    if failure == "cancel_upload":
        controller.upload_error = asyncio.CancelledError()
        expected = asyncio.CancelledError
    else:
        controller.failed_deletes.add("old")
        expected = PresetUpdateError
    with pytest.raises(expected):
        await writer.write("alert", b"new audio", force=True)

    # Model a process restart with an exact legacy physical match. The real
    # migration would overwrite/delete this record if classification reverted.
    restarted = TrackRegistry(writer.registry.path)
    restarted.load()
    overwrite = AsyncMock()
    physical = SimpleNamespace(desc=SimpleNamespace(chime_id="chime"),
                               direct_client=SimpleNamespace(overwrite_owned_slot=overwrite))
    manager = SimpleNamespace(
        list_ringtones=controller.list, slots={}, _bootstrap_audio={1: b"silence"},
        _targets={"chime": physical},
        get_chime=AsyncMock(return_value={"speakerTrackList": [{
            "track_no": 5, "fileName": "legacy.mp3", "md5": "a" * 32, "size": 100,
        }]}), delete_ringtone=controller.delete, _metric=lambda *args: None,
        refresh_index=writer.index.force_refresh,
    )
    await DynamicTtsSlotManager._migrate_legacy(manager, restarted)
    assert remaining(controller) == {"old"}
    assert restarted.records["alert"].kind == "preset"
    assert restarted.records["alert"].pinned
    overwrite.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_unknown_identity_is_pinned_without_claiming_ownership(preset_writer):
    writer, controller = preset_writer
    writer.registry.records.clear()
    assert await writer.write("alert", b"different audio") == "old"
    saved = writer.registry.records["alert"]
    assert saved.owner == "unknown" and saved.kind == "preset" and saved.pinned
    assert saved.duration_ms is None
    assert controller.calls == []


@pytest.mark.asyncio
async def test_full_capacity_preserves_legacy_record_being_replaced(preset_writer):
    writer, controller = preset_writer
    writer.registry.records["alert"].kind = "dynamic_tts"
    writer.reconciler.max_total = 1
    with pytest.raises(RingtoneCapacityError):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old"}
    assert controller.calls == []


@pytest.mark.asyncio
async def test_insufficient_capacity_does_not_partially_delete_other_dynamic_records(preset_writer):
    writer, controller = preset_writer
    controller.tones.extend([{"id": "dynamic", "name": "dynamic"}, {"id": "other", "name": "other"}])
    writer.registry.put(TrackRecord("dynamic", "dynamic_tts", nvr_ringtone_id="dynamic"))
    writer.reconciler.max_total = 2
    with pytest.raises(RingtoneCapacityError):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old", "dynamic", "other"}
    assert controller.calls == []


@pytest.mark.asyncio
async def test_preexisting_duplicate_names_require_explicit_reconciliation(preset_writer):
    writer, controller = preset_writer
    controller.tones.append({"id": "other", "name": "ALERT"})
    with pytest.raises(PresetUpdateError, match="duplicate"):
        await writer.write("alert", b"new audio", force=True)
    assert controller.calls == []
    await writer.index.load()
    with pytest.raises(RuntimeError, match="ambiguous"):
        await writer.index.resolve_or_refresh("alert")


@pytest.mark.asyncio
async def test_lost_upload_identity_never_claims_or_deletes_by_name_delta(preset_writer):
    writer, controller = preset_writer
    controller.omit_upload_id = True
    with pytest.raises(PresetUpdateError, match="outcome.*unknown"):
        await writer.write("alert", b"new audio", force=True)
    with pytest.raises(PresetUpdateError, match="outcome.*unknown"):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old", "new-1"}
    assert controller.calls == [("upload", "alert")]
    assert writer.registry.records["alert"].nvr_ringtone_id == "old"


@pytest.mark.asyncio
async def test_lost_delete_response_reconciles_completed_replacement(preset_writer):
    writer, controller = preset_writer
    controller.delete_then_raise = OSError("response lost")
    assert await writer.write("alert", b"new audio", force=True) == "new-1"
    assert remaining(controller) == {"new-1"}
    assert writer.registry.records["alert"].nvr_ringtone_id == "new-1"


@pytest.mark.asyncio
async def test_cancelled_after_old_delete_recovers_without_uploading_again(preset_writer):
    writer, controller = preset_writer
    controller.delete_then_raise = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"new-1"}
    # A new writer models a process restart; durable journal drives recovery.
    restarted = PresetWriter(registry=writer.registry, index=writer.index,
                             reconciler=writer.reconciler, list_ringtones=controller.list,
                             upload=controller.upload, delete=controller.delete, max_bytes=1024)
    assert await restarted.write("alert", b"new audio", force=True) == "new-1"
    assert controller.upload_count == 1
    assert json.loads(writer.journal.read_text())["pending"] is None


@pytest.mark.asyncio
async def test_cancelled_before_commit_rolls_back_on_next_write(preset_writer):
    writer, controller = preset_writer
    reads = 0

    async def interrupted_inventory():
        nonlocal reads
        reads += 1
        if reads == 2:
            raise asyncio.CancelledError()
        return await controller.list()

    writer.list_ringtones = interrupted_inventory
    with pytest.raises(asyncio.CancelledError):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old", "new-1"}
    assert writer.registry.records["alert"].nvr_ringtone_id == "old"
    assert await writer.write("alert", b"new audio", force=False) == "old"
    assert remaining(controller) == {"old"}
    assert controller.upload_count == 1


@pytest.mark.asyncio
async def test_registry_commit_failure_rolls_back_without_retiring_old(preset_writer, monkeypatch):
    writer, controller = preset_writer
    from app import persistence
    original = persistence.atomic_json

    def fail_new_commit(path, payload):
        if payload.get("alert", {}).get("nvr_ringtone_id") == "new-1":
            raise OSError("registry commit failed")
        return original(path, payload)

    monkeypatch.setattr(persistence, "atomic_json", fail_new_commit)
    with pytest.raises(OSError, match="registry commit failed"):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old"}
    assert ("delete", "old") not in controller.calls
    assert writer.registry.records["alert"].nvr_ringtone_id == "old"


@pytest.mark.asyncio
async def test_new_preset_registers_only_verified_uploaded_identity(preset_writer):
    writer, controller = preset_writer
    assert await writer.write("new-alert", b"new audio") == "new-1"
    assert remaining(controller) == {"old", "new-1"}
    record = writer.registry.records["new-alert"]
    assert record.owner == "unifi_announcer" and record.kind == "preset" and record.pinned
    assert record.nvr_ringtone_id == "new-1"
    assert controller.calls == [("upload", "new-alert")]


@pytest.mark.asyncio
async def test_persistence_failure_before_upload_is_non_destructive(preset_writer, monkeypatch):
    writer, controller = preset_writer

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("app.presets.atomic_json", fail)
    with pytest.raises(OSError, match="disk full"):
        await writer.write("alert", b"new audio", force=True)
    assert remaining(controller) == {"old"}
    assert controller.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("audio", [b"", b"x" * 1025])
async def test_invalid_size_fails_before_any_remote_mutation(preset_writer, audio):
    writer, controller = preset_writer
    with pytest.raises(ValueError, match="MP3"):
        await writer.write("alert", audio, force=True)
    assert controller.calls == []


@pytest.mark.asyncio
async def test_public_preset_operation_uses_recoverable_writer(main_module, monkeypatch, preset_writer):
    writer, controller = preset_writer
    monkeypatch.setattr(main_module, "ringtone_index", writer.index)
    monkeypatch.setattr(main_module, "track_registry", writer.registry)
    monkeypatch.setattr(main_module, "track_reconciler", writer.reconciler)
    monkeypatch.setattr(main_module.protect_backends.ringtone, "list_ringtones", controller.list)
    monkeypatch.setattr(main_module.chime_client, "upload_ringtone", controller.upload)
    monkeypatch.setattr(main_module.protect, "delete_ringtone", controller.delete)
    assert await main_module.create_or_update_preset("alert", b"new audio", force=True) == "new-1"
    assert remaining(controller) == {"new-1"}
