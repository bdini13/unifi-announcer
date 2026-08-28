import hashlib
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
    return DynamicTtsSlotManager(
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
