import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from app.playback.fixed_slots import DynamicTtsSlotManager


class World:
    def __init__(self):
        self.ringtones = []
        self.tracks = []
        self.uploads = 0

    async def list_ringtones(self):
        return [dict(item) for item in self.ringtones]

    async def upload(self, name, data):
        self.uploads += 1
        tone = {
            "id": f"ring-{self.uploads}",
            "name": name,
            "md5": hashlib.md5(data).hexdigest(),
            "size": len(data),
        }
        self.ringtones.append(tone)
        self.tracks.append({
            "md5": tone["md5"], "size": tone["size"],
            "fileName": f"{name}.mp3",
        })
        return dict(tone)

    async def delete(self, ringtone_id):
        before = len(self.ringtones)
        self.ringtones = [tone for tone in self.ringtones if tone["id"] != ringtone_id]
        return len(self.ringtones) != before

    async def resolve(self, name):
        return next((dict(tone) for tone in self.ringtones if tone["name"] == name), None)

    async def refresh(self):
        return None

    async def get_chime(self, _chime_id):
        return {"speakerTrackList": [dict(track) for track in self.tracks]}

    async def play(self, *_args, **_kwargs):
        return {"played": True}


class Direct:
    def __init__(self, world):
        self.world = world

    async def info(self):
        return {"featureFlags": {"supportCustomRingtone": True}}

    async def overwrite_owned_slot(self, *, slot, filename, mp3_bytes, **_kwargs):
        track = self.world.tracks[slot - 1]
        track.update({
            "md5": hashlib.md5(mp3_bytes).hexdigest(),
            "size": len(mp3_bytes),
            "fileName": filename,
        })
        return {"uploaded": True, "slot": slot}


def target(world):
    return SimpleNamespace(
        desc=SimpleNamespace(chime_id="chime-1", name="default"),
        direct_client=Direct(world),
    )


def manager(tmp_path, world):
    async def capacity(_snapshot, _needed):
        return []

    return DynamicTtsSlotManager(
        data_dir=tmp_path,
        list_ringtones=world.list_ringtones,
        upload_ringtone=world.upload,
        delete_ringtone=world.delete,
        resolve_ringtone=world.resolve,
        refresh_index=world.refresh,
        get_chime=world.get_chime,
        play_ringtone=world.play,
        ensure_capacity=capacity,
        minimum_guard_ms=1,
        reuse_margin_ms=0,
        provisioning_timeout_s=0.2,
        poll_interval_s=0.01,
    )


async def bootstrap(number):
    return (f"bootstrap-{number}".encode()) * 16


@pytest.mark.asyncio
async def test_third_message_waits_until_one_of_two_slots_is_released(tmp_path):
    world = World()
    mgr = manager(tmp_path, world)
    tgt = target(world)
    assert (await mgr.startup([tgt], bootstrap_audio_factory=bootstrap))["ready"]

    first = await mgr.prepare(b"one", [tgt])
    second = await mgr.prepare(b"two", [tgt])
    assert {first.logical_slot, second.logical_slot} == {1, 2}

    third_task = asyncio.create_task(mgr.prepare(b"three", [tgt]))
    await asyncio.sleep(0)
    assert not third_task.done()

    await first.release_now()
    third = await asyncio.wait_for(third_task, timeout=0.5)
    assert third.logical_slot == first.logical_slot

    await second.release_now()
    await third.release_now()


@pytest.mark.asyncio
async def test_production_startup_migrates_only_after_both_slots_are_proven(tmp_path):
    events = []
    world = World()

    class OrderedManager(DynamicTtsSlotManager):
        async def _migrate_legacy(self, registry):
            events.append("migrate")

        async def _ensure_slot(self, number):
            events.append(f"ensure-{number}")
            return SimpleNamespace()

        async def _validate_all_bindings(self):
            events.append("validate")

    mgr = OrderedManager(
        data_dir=tmp_path,
        list_ringtones=world.list_ringtones,
        upload_ringtone=world.upload,
        delete_ringtone=world.delete,
        resolve_ringtone=world.resolve,
        refresh_index=world.refresh,
        get_chime=world.get_chime,
        play_ringtone=world.play,
    )

    status = await mgr.startup(
        [target(world)],
        bootstrap_audio_factory=bootstrap,
        legacy_registry=SimpleNamespace(records={}),
    )

    assert status["ready"] is True
    assert events == ["ensure-1", "ensure-2", "validate", "migrate"]
