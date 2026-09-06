import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from app.playback.dynamic_slots import DynamicSlotUnavailable
from app.playback.production_slots import DynamicTtsSlotManager


class FakeMetrics:
    def __init__(self):
        self.counters = {}
        self.histograms = {}

    def inc(self, name, amount=1):
        self.counters[name] = self.counters.get(name, 0) + amount

    def observe(self, name, value):
        self.histograms.setdefault(name, []).append(value)


class FakeProtectWorld:
    def __init__(self, chime_ids=("chime-1",), *, stale_control_plane=True):
        self.ringtones = []
        self.chimes = {
            chime_id: {"id": chime_id, "speakerTrackList": []}
            for chime_id in chime_ids
        }
        self.device_macs = {
            chime_id: f"aa:bb:cc:dd:ee:{index:02x}"
            for index, chime_id in enumerate(chime_ids, 1)
        }
        self.device_uptimes = {chime_id: 1_000 for chime_id in chime_ids}
        self.stale_control_plane = stale_control_plane
        self.upload_calls = 0
        self.overwrite_calls = []
        self.fail_overwrite_for = set()

    async def list_ringtones(self):
        return [dict(item) for item in self.ringtones]

    async def upload(self, name, mp3):
        self.upload_calls += 1
        item = {
            "id": f"ring-{self.upload_calls}",
            "name": name,
            "md5": hashlib.md5(mp3).hexdigest(),
            "size": len(mp3),
        }
        self.ringtones.append(item)
        for chime in self.chimes.values():
            chime["speakerTrackList"].append(
                {
                    "md5": item["md5"],
                    "size": item["size"],
                    "fileName": f"{name}.mp3",
                }
            )
        return dict(item)

    async def delete(self, ringtone_id):
        before = len(self.ringtones)
        self.ringtones = [
            ringtone for ringtone in self.ringtones
            if ringtone["id"] != ringtone_id
        ]
        return len(self.ringtones) != before

    async def resolve(self, name):
        return next(
            (dict(ringtone) for ringtone in self.ringtones if ringtone["name"] == name),
            None,
        )

    async def refresh(self):
        return None

    async def get_chime(self, chime_id):
        chime = self.chimes[chime_id]
        return {
            "id": chime_id,
            "speakerTrackList": [
                dict(track) for track in chime["speakerTrackList"]
            ],
        }

    async def play(self, *_args, **_kwargs):
        return {"played": True}


class FakeDirect:
    def __init__(self, world, chime_id):
        self.world = world
        self.chime_id = chime_id

    async def info(self):
        return {
            "version": "v1.7.20",
            "mac": self.world.device_macs[self.chime_id],
            "uptime": self.world.device_uptimes[self.chime_id],
            "featureFlags": {"supportCustomRingtone": True},
        }

    async def overwrite_owned_slot(
        self,
        *,
        slot,
        filename,
        mp3_bytes,
        owner,
        builtin=False,
        experiment_enabled=False,
    ):
        assert owner == "unifi_announcer"
        assert not builtin
        assert experiment_enabled
        if self.chime_id in self.world.fail_overwrite_for:
            raise RuntimeError("simulated direct write failure")
        fingerprint = hashlib.md5(mp3_bytes).hexdigest()
        self.world.overwrite_calls.append(
            (self.chime_id, slot, fingerprint, len(mp3_bytes))
        )
        if not self.world.stale_control_plane:
            track = self.world.chimes[self.chime_id]["speakerTrackList"][slot - 1]
            track["md5"] = fingerprint
            track["size"] = len(mp3_bytes)
            track["fileName"] = filename
        return {"uploaded": True, "slot": slot}


def make_target(world, chime_id="chime-1", name="default"):
    return SimpleNamespace(
        desc=SimpleNamespace(chime_id=chime_id, name=name),
        direct_client=FakeDirect(world, chime_id),
    )


def make_manager(tmp_path, world, metrics=None):
    return DynamicTtsSlotManager(
        data_dir=tmp_path,
        list_ringtones=world.list_ringtones,
        upload_ringtone=world.upload,
        delete_ringtone=world.delete,
        resolve_ringtone=world.resolve,
        refresh_index=world.refresh,
        get_chime=world.get_chime,
        play_ringtone=world.play,
        metrics=metrics or FakeMetrics(),
        minimum_guard_ms=1,
        reuse_margin_ms=0,
        provisioning_timeout_s=0.2,
        poll_interval_s=0.001,
        device_sync_timeout_s=0.005,
        device_settle_delay_s=0,
    )


async def bootstrap(number):
    return (b"bootstrap-slot-" + str(number).encode()) * (10 + number)


@pytest.mark.asyncio
async def test_repeated_identical_phrase_reuses_resident_slot_with_stale_protect_metadata(
    tmp_path,
):
    world = FakeProtectWorld(stale_control_plane=True)
    metrics = FakeMetrics()
    target = make_target(world)
    manager = make_manager(tmp_path, world, metrics)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    first = await manager.prepare(b"same-message", [target])
    first_slot = first.logical_slot
    await first.release_now()

    second = await manager.prepare(b"same-message", [target])
    await second.release_now()

    assert second.logical_slot == first_slot
    assert len(world.overwrite_calls) == 1
    assert metrics.counters["tts_slot_content_hits"] == 1
    assert metrics.counters["tts_slot_overwrite_skips"] == 1
    assert metrics.counters["tts_slot_sync_stale_inventory_accepts"] == 1


@pytest.mark.asyncio
async def test_a_b_a_reuses_existing_a_slot_without_another_write(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    a1 = await manager.prepare(b"A", [target])
    a_slot = a1.logical_slot
    await a1.release_now()

    b = await manager.prepare(b"B", [target])
    b_slot = b.logical_slot
    await b.release_now()

    a2 = await manager.prepare(b"A", [target])
    await a2.release_now()

    assert a_slot != b_slot
    assert a2.logical_slot == a_slot
    assert len(world.overwrite_calls) == 2


@pytest.mark.asyncio
async def test_third_phrase_evicts_least_recently_used_free_slot(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    a = await manager.prepare(b"A", [target])
    a_slot = a.logical_slot
    await a.release_now()

    b = await manager.prepare(b"B", [target])
    b_slot = b.logical_slot
    await b.release_now()

    a_again = await manager.prepare(b"A", [target])
    await a_again.release_now()

    c = await manager.prepare(b"C", [target])
    await c.release_now()

    assert a_again.logical_slot == a_slot
    assert c.logical_slot == b_slot
    assert len(world.overwrite_calls) == 3


@pytest.mark.asyncio
async def test_restart_reuses_content_after_device_identity_and_binding_validation(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    first = make_manager(tmp_path, world)
    assert (await first.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    prepared = await first.prepare(b"restart-safe", [target])
    slot = prepared.logical_slot
    await prepared.release_now()
    await first.shutdown()
    before = len(world.overwrite_calls)

    second_target = make_target(world)
    second = make_manager(tmp_path, world)
    status = await second.startup(
        [second_target], bootstrap_audio_factory=bootstrap
    )
    assert status["ready"]
    assert status["content_reuse"]["trusted_bindings"] >= 1

    replay = await second.prepare(b"restart-safe", [second_target])
    await replay.release_now()

    assert replay.logical_slot == slot
    assert len(world.overwrite_calls) == before


@pytest.mark.asyncio
async def test_replacement_device_identity_invalidates_restart_fast_path(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    first = make_manager(tmp_path, world)
    assert (await first.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    prepared = await first.prepare(b"replacement-check", [target])
    await prepared.release_now()
    await first.shutdown()
    before = len(world.overwrite_calls)

    world.device_macs["chime-1"] = "aa:bb:cc:dd:ee:ff"
    second_target = make_target(world)
    second = make_manager(tmp_path, world)
    status = await second.startup(
        [second_target], bootstrap_audio_factory=bootstrap
    )
    assert status["ready"]

    replay = await second.prepare(b"replacement-check", [second_target])
    await replay.release_now()

    assert len(world.overwrite_calls) == before + 1


@pytest.mark.asyncio
async def test_uptime_reset_invalidates_content_even_when_device_identity_is_unchanged(
    tmp_path,
):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    first = await manager.prepare(b"survives-only-this-boot", [target])
    await first.release_now()
    before = len(world.overwrite_calls)

    # Same device identity and owned slot metadata, but a fresh hardware boot.
    world.device_uptimes["chime-1"] = 1
    replay = await manager.prepare(b"survives-only-this-boot", [target])
    await replay.release_now()

    assert len(world.overwrite_calls) == before + 1
    assert manager.status()["content_reuse"]["last_prepare"]["content_hit"] is False


@pytest.mark.asyncio
async def test_concurrent_requests_never_share_a_busy_slot(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    first, second = await asyncio.gather(
        manager.prepare(b"concurrent-A", [target]),
        manager.prepare(b"concurrent-B", [target]),
    )

    assert first.logical_slot != second.logical_slot
    await first.release_now()
    await second.release_now()


@pytest.mark.asyncio
async def test_multi_target_hit_requires_matching_content_on_every_target(tmp_path):
    world = FakeProtectWorld(("chime-1", "chime-2"), stale_control_plane=True)
    targets = [
        make_target(world, "chime-1", "kitchen"),
        make_target(world, "chime-2", "hallway"),
    ]
    manager = make_manager(tmp_path, world)
    assert (await manager.startup(targets, bootstrap_audio_factory=bootstrap))["ready"]

    first = await manager.prepare(b"whole-house", [targets[0]])
    first_slot = first.logical_slot
    await first.release_now()
    before = len(world.overwrite_calls)

    second = await manager.prepare(b"whole-house", targets)
    await second.release_now()

    assert second.logical_slot != first_slot
    assert len(world.overwrite_calls) == before + 2


@pytest.mark.asyncio
async def test_partial_multi_target_write_does_not_commit_content_identity(tmp_path):
    world = FakeProtectWorld(("chime-1", "chime-2"), stale_control_plane=True)
    targets = [
        make_target(world, "chime-1", "kitchen"),
        make_target(world, "chime-2", "hallway"),
    ]
    manager = make_manager(tmp_path, world)
    assert (await manager.startup(targets, bootstrap_audio_factory=bootstrap))["ready"]

    world.fail_overwrite_for.add("chime-2")
    with pytest.raises(RuntimeError, match="simulated direct write failure"):
        await manager.prepare(b"partial", targets)

    # The first physical write may have succeeded, but no application-authoritative
    # content assignment is committed unless every requested target succeeds.
    assert not manager.status()["content_reuse"]["assignments"]


@pytest.mark.asyncio
async def test_ownership_drift_still_fails_closed_before_content_reuse(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    prepared = await manager.prepare(b"owned", [target])
    slot_number = prepared.logical_slot
    await prepared.release_now()

    binding = manager.slots[slot_number].bindings["chime-1"]
    track = world.chimes["chime-1"]["speakerTrackList"][binding.device_slot - 1]
    track["fileName"] = "foreign.mp3"
    track["md5"] = "foreign"
    track["size"] = 999

    with pytest.raises(DynamicSlotUnavailable, match="ownership proof"):
        await manager.prepare(b"owned", [target])


@pytest.mark.asyncio
async def test_slot_status_exposes_sanitized_reuse_and_stage_timing(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    metrics = FakeMetrics()
    target = make_target(world)
    manager = make_manager(tmp_path, world, metrics)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]

    prepared = await manager.prepare(b"timed", [target])
    await prepared.release_now()
    status = manager.status()

    last = status["content_reuse"]["last_prepare"]
    assert last["content_hit"] is False
    assert last["overwrites"] == 1
    assert "slot_direct_upload_ms" in last
    assert "slot_sync_ms" in last
    assert metrics.histograms["slot_prepare_ms"]
    assert metrics.histograms["slot_direct_upload_ms"]
