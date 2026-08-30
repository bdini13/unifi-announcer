import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.dispatcher import AnnouncementCommand, AnnouncementDispatcher
from app.playback.fixed_slots import DynamicTtsSlotManager, DynamicSlotUnavailable


class FakeMetrics:
    def __init__(self):
        self.counters = {}

    def inc(self, name, amount=1):
        self.counters[name] = self.counters.get(name, 0) + amount

    def observe(self, *_args, **_kwargs):
        pass


class FakeProtectWorld:
    def __init__(self, chime_ids=("chime-1",)):
        self.ringtones = []
        self.chimes = {chime_id: {"id": chime_id, "speakerTrackList": []} for chime_id in chime_ids}
        self.upload_calls = 0

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
            chime["speakerTrackList"].append({
                "md5": item["md5"], "size": item["size"],
                "fileName": f"{name}.mp3",
            })
        return dict(item)

    async def delete(self, ringtone_id):
        before = len(self.ringtones)
        self.ringtones = [r for r in self.ringtones if r["id"] != ringtone_id]
        return len(self.ringtones) != before

    async def resolve(self, name):
        return next((dict(r) for r in self.ringtones if r["name"] == name), None)

    async def refresh(self):
        return None

    async def get_chime(self, chime_id):
        chime = self.chimes[chime_id]
        return {"id": chime_id, "speakerTrackList": [dict(t) for t in chime["speakerTrackList"]]}

    async def play(self, *_args, **_kwargs):
        return {"played": True}


class FakeDirect:
    def __init__(self, world, chime_id):
        self.world = world
        self.chime_id = chime_id
        self.overwrites = []

    async def info(self):
        return {"version": "v1.7.20", "featureFlags": {"supportCustomRingtone": True}}

    async def overwrite_owned_slot(self, *, slot, filename, mp3_bytes, owner,
                                   builtin=False, experiment_enabled=False):
        assert owner == "unifi_announcer"
        assert not builtin
        assert experiment_enabled
        track = self.world.chimes[self.chime_id]["speakerTrackList"][slot - 1]
        track["md5"] = hashlib.md5(mp3_bytes).hexdigest()
        track["size"] = len(mp3_bytes)
        track["fileName"] = filename
        self.overwrites.append((slot, hashlib.md5(mp3_bytes).hexdigest()))
        return {"uploaded": True, "slot": slot}


def make_target(world, chime_id="chime-1", name="default"):
    return SimpleNamespace(
        desc=SimpleNamespace(chime_id=chime_id, name=name),
        direct_client=FakeDirect(world, chime_id),
    )


def make_manager(tmp_path, world, metrics=None):
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
        metrics=metrics or FakeMetrics(),
        minimum_guard_ms=1,
        reuse_margin_ms=0,
        provisioning_timeout_s=0.2,
        poll_interval_s=0.01,
    )


async def bootstrap(number):
    return (b"bootstrap-slot-" + str(number).encode()) * (10 + number)


@pytest.mark.asyncio
async def test_first_start_creates_exactly_two_persistent_identities(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    manager = make_manager(tmp_path, world)

    status = await manager.startup([target], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is True
    assert len(world.ringtones) == 2
    assert world.upload_calls == 2
    assert [r["name"] for r in world.ringtones] == [
        f"UA-TTS-1-{manager.installation_suffix}",
        f"UA-TTS-2-{manager.installation_suffix}",
    ]
    assert (tmp_path / "installation.json").exists()
    assert (tmp_path / "dynamic_tts_slots.json").exists()


@pytest.mark.asyncio
async def test_restart_reuses_same_two_identities(tmp_path):
    world = FakeProtectWorld()
    first = make_manager(tmp_path, world)
    await first.startup([make_target(world)], bootstrap_audio_factory=bootstrap)
    first_suffix = first.installation_suffix

    second = make_manager(tmp_path, world)
    status = await second.startup([make_target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is True
    assert second.installation_suffix == first_suffix
    assert world.upload_calls == 2
    assert len(world.ringtones) == 2


@pytest.mark.asyncio
async def test_persisted_id_with_foreign_protect_name_fails_closed(tmp_path):
    world = FakeProtectWorld()
    first = make_manager(tmp_path, world)
    await first.startup([make_target(world)], bootstrap_audio_factory=bootstrap)
    world.ringtones[0]["name"] = "User Preset"

    restarted = make_manager(tmp_path, world)
    restarted.installation_id = restarted._load_or_create_identity()
    restarted._load_registry()
    restarted._targets = {"chime-1": make_target(world)}
    restarted._bootstrap_audio[1] = await bootstrap(1)

    with pytest.raises(DynamicSlotUnavailable, match="Protect ringtone name"):
        await restarted._ensure_slot(1)


@pytest.mark.asyncio
async def test_missing_persisted_id_recovers_unique_expected_name(tmp_path):
    # A stale ID is recoverable only because exactly one Protect ringtone still
    # has the installation-specific expected name; this is safe identity repair,
    # not permission to claim an unregistered name or physical slot.
    world = FakeProtectWorld()
    first = make_manager(tmp_path, world)
    await first.startup([make_target(world)], bootstrap_audio_factory=bootstrap)
    world.ringtones[0]["id"] = "replacement-ring-1"

    restarted = make_manager(tmp_path, world)
    status = await restarted.startup(
        [make_target(world)], bootstrap_audio_factory=bootstrap
    )

    assert status["ready"] is True, status
    assert restarted.slots[1].protect_ringtone_id == "replacement-ring-1"
    assert world.upload_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_slot", ["missing", "extra"])
async def test_global_validation_rejects_corrupt_logical_slot_keys(
    tmp_path, corrupt_slot
):
    world = FakeProtectWorld()
    manager = make_manager(tmp_path, world)
    assert (await manager.startup(
        [make_target(world)], bootstrap_audio_factory=bootstrap
    ))["ready"]

    if corrupt_slot == "missing":
        manager.slots.pop(2)
    else:
        manager.slots[3] = manager.slots[2]

    with pytest.raises(DynamicSlotUnavailable, match="exactly logical slots 1 and 2"):
        await manager._validate_all_bindings()


@pytest.mark.asyncio
async def test_global_validation_rejects_whitespace_only_protect_id(tmp_path):
    world = FakeProtectWorld()
    manager = make_manager(tmp_path, world)
    assert (await manager.startup(
        [make_target(world)], bootstrap_audio_factory=bootstrap
    ))["ready"]
    manager.slots[1].protect_ringtone_id = "   "

    with pytest.raises(DynamicSlotUnavailable, match="distinct nonempty Protect IDs"):
        await manager._validate_all_bindings()


@pytest.mark.asyncio
async def test_global_validation_rejects_duplicate_protect_ids(tmp_path):
    world = FakeProtectWorld()
    manager = make_manager(tmp_path, world)
    assert (await manager.startup(
        [make_target(world)], bootstrap_audio_factory=bootstrap
    ))["ready"]
    manager.slots[2].protect_ringtone_id = manager.slots[1].protect_ringtone_id

    with pytest.raises(DynamicSlotUnavailable, match="distinct nonempty Protect IDs"):
        await manager._validate_all_bindings()


@pytest.mark.asyncio
async def test_global_validation_rejects_duplicate_physical_slot_bindings(tmp_path):
    world = FakeProtectWorld()
    manager = make_manager(tmp_path, world)
    assert (await manager.startup(
        [make_target(world)], bootstrap_audio_factory=bootstrap
    ))["ready"]
    first = manager.slots[1].bindings["chime-1"]
    second = manager.slots[2].bindings["chime-1"]
    second.device_slot = first.device_slot
    second.filename = first.filename

    with pytest.raises(DynamicSlotUnavailable, match="distinct physical slots"):
        await manager._validate_all_bindings()


@pytest.mark.asyncio
async def test_physical_slot_uniqueness_is_scoped_per_chime(tmp_path):
    world = FakeProtectWorld(("chime-1", "chime-2"))
    targets = [
        make_target(world, "chime-1", "kitchen"),
        make_target(world, "chime-2", "hallway"),
    ]
    manager = make_manager(tmp_path, world)

    status = await manager.startup(targets, bootstrap_audio_factory=bootstrap)

    assert status["ready"] is True, status
    assert set(manager.slots) == {1, 2}
    assert {
        number: manager.slots[number].bindings["chime-1"].device_slot
        for number in (1, 2)
    } == {1: 1, 2: 2}
    assert {
        number: manager.slots[number].bindings["chime-2"].device_slot
        for number in (1, 2)
    } == {1: 1, 2: 2}
    for chime_id in ("chime-1", "chime-2"):
        mappings = {
            manager.slots[number].bindings[chime_id].device_slot
            for number in (1, 2)
        }
        assert mappings == {1, 2}


@pytest.mark.asyncio
async def test_100_unique_hermes_messages_never_create_more_ringtones(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    await manager.startup([target], bootstrap_audio_factory=bootstrap)
    identities_after_provisioning = world.upload_calls
    used_slots = []

    for number in range(100):
        lease = await manager.prepare(f"Hermes unique message {number}".encode(), [target])
        used_slots.append(lease.logical_slot)
        await lease.release_now()

    assert identities_after_provisioning == 2
    assert world.upload_calls == 2
    assert len(world.ringtones) == 2
    assert set(used_slots) == {1, 2}
    assert used_slots[:6] == [1, 2, 1, 2, 1, 2]
    assert len(target.direct_client.overwrites) == 100


@pytest.mark.asyncio
async def test_repeat_content_skips_flash_overwrite(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    metrics = FakeMetrics()
    manager = make_manager(tmp_path, world, metrics)
    await manager.startup([target], bootstrap_audio_factory=bootstrap)

    first = await manager.prepare(b"same-message", [target])
    first_slot = first.logical_slot
    await first.release_now()
    second = await manager.prepare(b"different", [target])
    await second.release_now()
    third = await manager.prepare(b"same-message", [target])
    assert third.logical_slot == first_slot
    await third.release_now()

    # Slot 1 was written once for same-message; returning to the same content skips it.
    assert metrics.counters.get("tts_slot_overwrite_skips", 0) >= 1


@pytest.mark.asyncio
async def test_prepare_waits_for_overwritten_audio_to_reach_physical_slot(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    manager.device_sync_timeout_s = 0.1
    manager.device_settle_delay_s = 0
    await manager.startup([target], bootstrap_audio_factory=bootstrap)
    binding = manager.slots[1].bindings["chime-1"]
    original_get_chime = manager.get_chime
    polls = 0

    async def delayed_sync(chime_id):
        nonlocal polls
        polls += 1
        chime = await original_get_chime(chime_id)
        if polls < 3:
            chime["speakerTrackList"][binding.device_slot - 1]["md5"] = "stale"
        return chime

    manager.get_chime = delayed_sync
    prepared = await manager.prepare(b"new-audio", [target])

    assert polls >= 3
    await prepared.release_now()


@pytest.mark.asyncio
async def test_prepare_fails_when_physical_slot_never_synchronizes(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    manager.device_sync_timeout_s = 0.1
    manager.poll_interval_s = 0.005
    manager.device_settle_delay_s = 0
    await manager.startup([target], bootstrap_audio_factory=bootstrap)
    binding = manager.slots[1].bindings["chime-1"]
    original_get_chime = manager.get_chime

    async def never_synced(chime_id):
        chime = await original_get_chime(chime_id)
        chime["speakerTrackList"][binding.device_slot - 1]["md5"] = "stale"
        return chime

    manager.get_chime = never_synced
    with pytest.raises(DynamicSlotUnavailable, match="did not synchronize"):
        await manager.prepare(b"new-audio", [target])


@pytest.mark.asyncio
async def test_slot_drift_fails_closed_before_overwrite(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    await manager.startup([target], bootstrap_audio_factory=bootstrap)
    binding = manager.slots[1].bindings["chime-1"]
    world.chimes["chime-1"]["speakerTrackList"][binding.device_slot - 1] = {
        "md5": "foreign", "size": 999, "fileName": "foreign.mp3"
    }

    with pytest.raises(DynamicSlotUnavailable, match="ownership proof"):
        await manager.prepare(b"must-not-overwrite", [target])

    assert target.direct_client.overwrites == []


@pytest.mark.asyncio
async def test_preflight_uses_physical_track_number_when_slots_are_sparse(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    await manager.startup([target], bootstrap_audio_factory=bootstrap)
    binding = manager.slots[1].bindings["chime-1"]
    binding.device_slot = 6
    owned = world.chimes["chime-1"]["speakerTrackList"][0]
    owned["track_no"] = binding.device_slot
    world.chimes["chime-1"]["speakerTrackList"] = [
        {"track_no": 1, "md5": "builtin", "size": 1, "name": "Default"},
        owned,
    ]

    expected_filename = binding.filename
    await manager._preflight_binding(manager.slots[1], binding)

    assert binding.filename == expected_filename


@pytest.mark.asyncio
async def test_corrupt_installation_identity_fails_without_allocating_slots(tmp_path):
    Path(tmp_path, "installation.json").write_text('{"installation_id":"not-a-uuid"}')
    world = FakeProtectWorld()
    manager = make_manager(tmp_path, world)

    status = await manager.startup([make_target(world)], bootstrap_audio_factory=bootstrap)

    assert status["ready"] is False
    assert "identity is corrupt" in status["last_error"]
    assert world.upload_calls == 0


class InlineQueue:
    depth = 0

    async def submit(self, request):
        return await request.factory()


class FakeLease:
    logical_slot = 1
    ringtone_id = "persistent-slot-id"

    def __init__(self):
        self.released = False

    async def refresh_ringtone_id(self):
        return self.ringtone_id

    def release_after(self, _repeat):
        self.released = True

    async def release_now(self):
        self.released = True


@pytest.mark.asyncio
async def test_dispatcher_with_slot_manager_never_calls_legacy_upload():
    target = SimpleNamespace(
        desc=SimpleNamespace(chime_id="chime-1", name="default"),
        queue=InlineQueue(), direct_client=SimpleNamespace(),
    )
    protect = SimpleNamespace(
        play=AsyncMock(return_value={"played": True}),
        play_buzzer=AsyncMock(), play_default=AsyncMock(),
    )
    legacy_chime = SimpleNamespace(upload_ringtone=AsyncMock())
    lease = FakeLease()
    dynamic = SimpleNamespace(prepare=AsyncMock(return_value=lease))
    metrics = FakeMetrics()
    dispatcher = AnnouncementDispatcher(
        protect=protect,
        chime=legacy_chime,
        ringtone_index=SimpleNamespace(),
        synthesize=AsyncMock(return_value=b"mp3"),
        slug=lambda text: text,
        resolve_preset=AsyncMock(),
        resolve_targets=lambda _target: [target],
        profile=lambda value: value,
        quiet=lambda: False,
        metrics=metrics,
        volume_default=50,
        repeat_default=1,
        dynamic_slots=dynamic,
    )

    result = await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    assert result.disposition == "played"
    dynamic.prepare.assert_awaited_once()
    legacy_chime.upload_ringtone.assert_not_awaited()
    protect.play.assert_awaited_once()
    assert protect.play.await_args.args[0] == "persistent-slot-id"
    assert lease.released is True
