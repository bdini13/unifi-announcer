import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.playback.fixed_slots import DynamicTtsSlotManager


class DeltaWorld:
    def __init__(self, mode="replace"):
        self.mode = mode
        self.ringtones = []
        self.uploads = 0
        self.deletes = 0
        self.play_calls = []
        self.tracks = [
            {"md5": f"base-{number}", "size": 90 + number,
             "fileName": f"base-{number}.mp3"}
            for number in range(1, 8)
        ]

    async def list_ringtones(self):
        return [dict(item) for item in self.ringtones]

    async def upload(self, name, data):
        self.uploads += 1
        tone = {
            "id": f"ring-{self.uploads}",
            "name": name,
            # Protect-side fingerprint intentionally matches the SOURCE only.
            "md5": hashlib.md5(data).hexdigest(),
            "size": len(data),
        }
        self.ringtones.append(tone)
        return dict(tone)

    async def delete(self, ringtone_id):
        self.deletes += 1
        before = len(self.ringtones)
        self.ringtones = [tone for tone in self.ringtones if tone["id"] != ringtone_id]
        return len(self.ringtones) != before

    async def resolve(self, name):
        return next((dict(tone) for tone in self.ringtones if tone["name"] == name), None)

    async def refresh(self):
        return None

    async def get_chime(self, _chime_id):
        return {"speakerTrackList": [dict(track) for track in self.tracks]}

    async def play(self, ringtone_id, *, volume, repeat_times, chime_id):
        self.play_calls.append((ringtone_id, volume, repeat_times, chime_id))
        number = int(ringtone_id.split("-")[-1])
        transformed = {
            "md5": f"device-transcoded-{number}",
            "size": 200 + number,
            "fileName": f"device-slot-{number}.mp3",
        }
        if self.mode == "replace":
            self.tracks[number - 1] = transformed
        elif self.mode == "insert":
            self.tracks.append(transformed)
        elif self.mode == "multiple":
            self.tracks[0] = transformed
            self.tracks[1] = {
                "md5": f"also-changed-{number}",
                "size": 900 + number,
                "fileName": f"also-{number}.mp3",
            }
        elif self.mode == "none":
            pass
        else:  # pragma: no cover
            raise AssertionError(self.mode)
        return {"played": True}


class Direct:
    def __init__(self, world):
        self.world = world

    async def info(self):
        return {"version": "v1.7.20", "featureFlags": {"supportCustomRingtone": True}}

    async def overwrite_owned_slot(self, *, slot, filename, mp3_bytes, **_kwargs):
        self.world.tracks[slot - 1] = {
            "md5": hashlib.md5(mp3_bytes).hexdigest(),
            "size": len(mp3_bytes),
            "fileName": filename,
        }
        return {"uploaded": True, "slot": slot}


def target(world):
    return SimpleNamespace(
        desc=SimpleNamespace(chime_id="chime-1", name="default"),
        direct_client=Direct(world),
    )


def manager(tmp_path, world):
    result = DynamicTtsSlotManager(
        data_dir=tmp_path,
        list_ringtones=world.list_ringtones,
        upload_ringtone=world.upload,
        delete_ringtone=world.delete,
        resolve_ringtone=world.resolve,
        refresh_index=world.refresh,
        get_chime=world.get_chime,
        play_ringtone=world.play,
        minimum_guard_ms=1,
        reuse_margin_ms=0,
        provisioning_timeout_s=0.05,
        poll_interval_s=0.005,
    )

    # Exercise the real polling/deadline logic without waiting for hardware.
    elapsed = 0.0
    async def poll():
        nonlocal elapsed
        elapsed += result.poll_interval_s
        await asyncio.sleep(0)
    result._loop_time = lambda: elapsed
    result._sleep_poll = poll
    return result


async def bootstrap(number):
    return (f"source-bootstrap-{number}".encode()) * 12


@pytest.mark.asyncio
async def test_transcoded_same_count_track_delta_proves_binding(tmp_path):
    world = DeltaWorld(mode="replace")
    mgr = manager(tmp_path, world)

    status = await mgr.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is True, status
    assert world.uploads == 2
    assert all(call[1] == 1 for call in world.play_calls)
    assert mgr.slots[1].bindings["chime-1"].device_slot == 1
    assert mgr.slots[2].bindings["chime-1"].device_slot == 2
    # Device evidence is the transformed fingerprint, not the source MP3 hash.
    assert mgr.slots[1].bindings["chime-1"].provisioning_md5 == "device-transcoded-1"


@pytest.mark.asyncio
async def test_single_inserted_track_delta_proves_binding(tmp_path):
    world = DeltaWorld(mode="insert")
    # Each slot appends one physical track; sequence alignment must identify it.
    mgr = manager(tmp_path, world)

    status = await mgr.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is True
    assert mgr.slots[1].bindings["chime-1"].device_slot == 8
    assert mgr.slots[2].bindings["chime-1"].device_slot == 9


@pytest.mark.asyncio
async def test_zero_track_delta_fails_closed_without_guessing_slots(tmp_path):
    world = DeltaWorld(mode="none")
    mgr = manager(tmp_path, world)

    status = await mgr.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is False
    assert "exactly one provable physical track delta" in status["last_error"]
    assert status["binding_diagnostics"]["chime-1"]["result"] == "ambiguous"
    assert world.uploads == 1


@pytest.mark.asyncio
async def test_multiple_track_delta_fails_closed_without_guessing_slots(tmp_path):
    world = DeltaWorld(mode="multiple")
    mgr = manager(tmp_path, world)

    status = await mgr.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is False
    assert "exactly one provable physical track delta" in status["last_error"]
    assert world.uploads == 1


@pytest.mark.asyncio
async def test_existing_partial_slot_is_retried_without_duplicate_identity(tmp_path):
    world = DeltaWorld(mode="none")
    first = manager(tmp_path, world)
    first_status = await first.startup([target(world)], bootstrap_audio_factory=bootstrap)
    assert first_status["ready"] is False
    assert world.uploads == 1

    world.mode = "replace"
    second = manager(tmp_path, world)
    second_status = await second.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert second_status["ready"] is True
    assert world.uploads == 2  # slot 1 reused; only slot 2 was created
    assert len([r for r in world.ringtones if r["name"].startswith("UA-TTS-1-")]) == 1
    assert second.slots[1].bindings["chime-1"].device_slot == 1


@pytest.mark.asyncio
async def test_failed_slot_proof_does_not_run_legacy_migration(tmp_path):
    world = DeltaWorld(mode="none")
    mgr = manager(tmp_path, world)
    events = []

    class Registry:
        records = {"legacy": SimpleNamespace(
            owner="unifi_announcer",
            kind="dynamic_tts",
            nvr_ringtone_id="legacy-ring",
        )}

        def put(self, _record):
            events.append("put")

        def remove(self, _key):
            events.append("remove")

    status = await mgr.startup(
        [target(world)],
        bootstrap_audio_factory=bootstrap,
        legacy_registry=Registry(),
    )

    assert status["ready"] is False
    assert events == []
    assert world.deletes == 0


@pytest.mark.asyncio
async def test_persisted_mapping_survives_omitted_track_metadata(tmp_path):
    world = DeltaWorld(mode="replace")
    first = manager(tmp_path, world)
    assert (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    expected = {
        number: (slot.bindings["chime-1"].device_slot,
                 slot.bindings["chime-1"].filename)
        for number, slot in first.slots.items()
    }

    world.tracks = []
    second = manager(tmp_path, world)
    status = await second.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is True, status
    assert {
        number: (slot.bindings["chime-1"].device_slot,
                 slot.bindings["chime-1"].filename)
        for number, slot in second.slots.items()
    } == expected
    assert world.uploads == 2


@pytest.mark.asyncio
async def test_persisted_mapping_refreshes_filename_from_exact_provisioning_proof(tmp_path):
    world = DeltaWorld(mode="replace")
    mgr = manager(tmp_path, world)
    assert (await mgr.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    binding = mgr.slots[1].bindings["chime-1"]
    track = world.tracks[binding.device_slot - 1]
    track.pop("fileName")
    track["name"] = "protect-rotated-owned-name"
    track["md5"] = mgr.slots[1].bootstrap_md5
    track["size"] = mgr.slots[1].bootstrap_size

    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is True, status
    assert restarted.slots[1].bindings["chime-1"].filename == (
        "protect-rotated-owned-name.mp3"
    )


@pytest.mark.asyncio
async def test_persisted_mapping_rejects_positive_filename_drift(tmp_path):
    world = DeltaWorld(mode="replace")
    mgr = manager(tmp_path, world)
    assert (await mgr.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    binding = mgr.slots[1].bindings["chime-1"]
    binding.device_slot = 6
    binding.filename = world.tracks[5]["fileName"]
    mgr._persist_registry()
    world.tracks[5]["fileName"] = "foreign-owned-track.mp3"

    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is False
    assert "ownership proof" in status["last_error"]


@pytest.mark.asyncio
async def test_persisted_mapping_rejects_reported_slot_without_filename(tmp_path):
    world = DeltaWorld(mode="replace")
    mgr = manager(tmp_path, world)
    assert (await mgr.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    binding = mgr.slots[1].bindings["chime-1"]
    world.tracks[binding.device_slot - 1].pop("fileName")

    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is False
    assert "ownership proof" in status["last_error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_response", ["staging", "inventory"])
async def test_interrupted_staging_recovers_from_durable_positive_evidence(tmp_path, lost_response):
    world = DeltaWorld()
    play = world.play

    async def identified_play(ringtone_id, **kwargs):
        result = await play(ringtone_id, **kwargs)
        world.tracks[int(ringtone_id.split("-")[-1]) - 1]["ringtoneId"] = ringtone_id
        if lost_response == "staging" and len(world.play_calls) == 1:
            raise OSError("lost staging response after device applied audio")
        return result

    world.play = identified_play
    first = manager(tmp_path, world)
    original_get = first.get_chime

    async def lost_inventory(chime_id):
        if world.play_calls:
            raise OSError("lost inventory response after successful staging")
        return await original_get(chime_id)

    if lost_response == "inventory":
        first.get_chime = lost_inventory
    assert not (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    journal = json.loads(first.provisioning_path.read_text())
    assert journal["operations"]["1"]["before"]["chime-1"][0]["md5"] == "base-1"
    assert world.uploads == 1

    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)
    assert status["ready"], status
    assert world.uploads == 2
    assert len(world.play_calls) == 2  # No duplicate staging of the first slot.
    assert restarted.slots[1].bindings["chime-1"].filename == "device-slot-1.mp3"
    assert json.loads(restarted.provisioning_path.read_text())["operations"] == {}


@pytest.mark.asyncio
async def test_lost_creation_response_recovers_exact_bootstrap_without_duplicate_upload(tmp_path):
    # Protect can stage on creation, before the first explicit play request.
    from test_production_slot_content_reuse import FakeProtectWorld, make_target

    world = FakeProtectWorld(stale_control_plane=False)
    upload = world.upload

    async def lost_upload(name, data):
        await upload(name, data)
        raise OSError("creation committed but response was lost")

    first = manager(tmp_path, world)
    first.upload_ringtone = lost_upload
    assert not (await first.startup([make_target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    assert not first.slots

    restarted = manager(tmp_path, world)
    status = await restarted.startup([make_target(world)], bootstrap_audio_factory=bootstrap)
    assert status["ready"], status
    assert world.upload_calls == 2
    assert len(world.ringtones) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_changes", [1, 2])
async def test_interrupted_provisioning_never_claims_unrelated_deltas(tmp_path, foreign_changes):
    world = DeltaWorld(mode="none")
    first = manager(tmp_path, world)
    assert not (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    for number in range(foreign_changes):
        world.tracks[number] = {
            "md5": f"unrelated-{number}", "size": 321,
            "fileName": f"unrelated-{number}.mp3",
        }
    plays_before = len(world.play_calls)

    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)
    assert not status["ready"]
    assert "positive ringtone identity" in status["last_error"]
    assert not restarted.slots[1].bindings
    assert len(world.play_calls) == plays_before
    assert json.loads(restarted.provisioning_path.read_text())["operations"]["1"]


@pytest.mark.asyncio
async def test_unidentified_transformed_interrupted_delta_remains_unavailable(tmp_path):
    world = DeltaWorld()
    first = manager(tmp_path, world)
    original_get = first.get_chime

    async def lost_inventory(chime_id):
        if world.play_calls:
            raise OSError("lost transformed track observation")
        return await original_get(chime_id)

    first.get_chime = lost_inventory
    assert not (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)
    assert not status["ready"]
    assert "positive ringtone identity" in status["last_error"]
    assert not restarted.slots[1].bindings


@pytest.mark.asyncio
async def test_provisioning_intent_must_be_durable_before_remote_mutation(tmp_path, monkeypatch):
    world = DeltaWorld()
    first = manager(tmp_path, world)

    def failed_journal():
        raise OSError("disk unavailable")

    monkeypatch.setattr(first, "_persist_provisioning", failed_journal)
    assert not (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    assert world.uploads == 0
    assert world.play_calls == []


@pytest.mark.asyncio
async def test_same_name_replacement_cannot_inherit_old_physical_binding(tmp_path):
    world = DeltaWorld()
    first = manager(tmp_path, world)
    assert (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    world.ringtones[0]["id"] = "replacement-with-same-name"
    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)
    assert not status["ready"]
    assert "same-name replacement" in status["last_error"]
    assert restarted.slots[1].protect_ringtone_id == "ring-1"


def test_delta_uses_reported_physical_number_in_filtered_inventory():
    before = [{"track_no": 1, "name": "Default", "md5": "builtin", "size": 100}]
    changed = {"track_no": 7, "name": "owned", "md5": "custom", "size": 200}
    assert DynamicTtsSlotManager._delta_candidate(before, before + [changed]) == (7, changed)


@pytest.mark.asyncio
async def test_multi_target_interruption_keeps_already_committed_bindings(tmp_path):
    from test_production_slot_content_reuse import FakeProtectWorld, make_target

    world = FakeProtectWorld(chime_ids=("chime-1", "chime-2"))
    targets = [make_target(world, chime_id) for chime_id in world.chimes]
    play_calls = []

    async def lose_second_target_response(ringtone_id, **kwargs):
        play_calls.append((ringtone_id, kwargs["chime_id"]))
        if len(play_calls) == 2:
            raise OSError("second target response lost")
        return {}

    world.play = lose_second_target_response
    first = manager(tmp_path, world)
    assert not (await first.startup(targets, bootstrap_audio_factory=bootstrap))["ready"]
    assert set(first.slots[1].bindings) == {"chime-1"}

    restarted = manager(tmp_path, world)
    status = await restarted.startup(targets, bootstrap_audio_factory=bootstrap)
    assert status["ready"], status
    assert world.upload_calls == 2
    assert play_calls.count(("ring-1", "chime-1")) == 1
    assert play_calls.count(("ring-1", "chime-2")) == 1
    assert set(restarted.slots[1].bindings) == {"chime-1", "chime-2"}


@pytest.mark.asyncio
async def test_crash_after_binding_commit_before_journal_cleanup_does_not_restage(tmp_path):
    world = DeltaWorld()
    first = manager(tmp_path, world)
    persist = first._persist_provisioning

    def fail_cleanup():
        if first.slots.get(1) and first.slots[1].bindings:
            raise OSError("crash before recovery-journal cleanup")
        persist()

    first._persist_provisioning = fail_cleanup
    assert not (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)
    assert status["ready"], status
    assert len(world.play_calls) == 2
    assert world.uploads == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("journal", [[], {"schema_version": 1, "operations": {}}])
async def test_corrupt_provisioning_journal_cannot_trigger_reprovisioning(tmp_path, journal):
    world = DeltaWorld()
    first = manager(tmp_path, world)
    assert (await first.startup([target(world)], bootstrap_audio_factory=bootstrap))["ready"]
    first.provisioning_path.write_text(json.dumps(journal))
    restarted = manager(tmp_path, world)
    status = await restarted.startup([target(world)], bootstrap_audio_factory=bootstrap)
    assert not status["ready"]
    assert "provisioning journal is invalid" in status["last_error"]
    assert world.uploads == 2
    assert len(world.play_calls) == 2
