import pytest

from app.playback.dynamic_slots import DeviceSlotBinding, DynamicSlotUnavailable
from app.playback.production_slots import DynamicTtsSlotManager
from test_production_slot_content_reuse import (
    FakeProtectWorld, bootstrap, make_manager, make_target,
)


@pytest.mark.asyncio
async def test_owned_play_requires_an_active_prepared_lease_even_after_restart(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    first = make_manager(tmp_path, world)
    assert (await first.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    lease = await first.prepare(b"leased speech", [target])
    chime = await world.get_chime("chime-1")
    assert first.verify_owned_play(lease.ringtone_id, "chime-1", chime)
    await lease.release_now()
    with pytest.raises(DynamicSlotUnavailable, match="prepared content proof"):
        first.verify_owned_play(lease.ringtone_id, "chime-1", chime)

    restarted = make_manager(tmp_path, world)
    assert (await restarted.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    assert restarted._trusted_content  # Restoration is not a playback lease.
    with pytest.raises(DynamicSlotUnavailable, match="prepared content proof"):
        restarted.verify_owned_play(lease.ringtone_id, "chime-1", chime)
    await restarted.shutdown()


@pytest.mark.asyncio
async def test_owned_play_requires_the_target_in_the_active_lease(tmp_path):
    world = FakeProtectWorld(chime_ids=("chime-1", "chime-2"), stale_control_plane=False)
    targets = [make_target(world, chime_id) for chime_id in world.chimes]
    manager = make_manager(tmp_path, world)
    assert (await manager.startup(targets, bootstrap_audio_factory=bootstrap))["ready"]
    first = await manager.prepare(b"shared phrase", targets)
    await first.release_now()
    lease = await manager.prepare(b"shared phrase", targets[:1])
    assert manager.verify_owned_play(lease.ringtone_id, "chime-1", await world.get_chime("chime-1"))
    with pytest.raises(DynamicSlotUnavailable, match="prepared content proof"):
        manager.verify_owned_play(lease.ringtone_id, "chime-2", await world.get_chime("chime-2"))
    await lease.release_now()


@pytest.mark.asyncio
async def test_controller_event_during_write_cannot_commit_or_leak_a_slot(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    overwrite = target.direct_client.overwrite_owned_slot

    async def write_with_controller_event(**kwargs):
        result = await overwrite(**kwargs)
        manager.note_external_change(["chime-1"])
        return result

    target.direct_client.overwrite_owned_slot = write_with_controller_event
    with pytest.raises(DynamicSlotUnavailable, match="changed ringtone state"):
        await manager.prepare(b"racing controller update", [target])
    assert not manager._trusted_content
    assert not manager._busy
    assert not manager._busy_targets
    assert not manager._content_state["bindings"]


@pytest.mark.asyncio
async def test_controller_event_after_prepare_revokes_dispatch_permission(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    lease = await manager.prepare(b"revoked before dispatch", [target])
    manager.note_external_change(["chime-1"])
    with pytest.raises(DynamicSlotUnavailable, match="changed ringtone state"):
        manager.validate_prepared(lease, "chime-1")
    with pytest.raises(DynamicSlotUnavailable, match="prepared content proof"):
        manager.verify_owned_play(lease.ringtone_id, "chime-1", await world.get_chime("chime-1"))
    await lease.release_now()


@pytest.mark.asyncio
async def test_conflicting_inventory_after_restart_forces_a_fresh_write(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    first = make_manager(tmp_path, world)
    assert (await first.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    lease = await first.prepare(b"phrase before controller resync", [target])
    await lease.release_now()
    binding = first.slots[lease.logical_slot].bindings["chime-1"]
    track = world.chimes["chime-1"]["speakerTrackList"][binding.device_slot - 1]
    track.update(md5="controller-restored-content", size=999)
    before = len(world.overwrite_calls)

    restarted = make_manager(tmp_path, world)
    assert (await restarted.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    replay = await restarted.prepare(b"phrase before controller resync", [target])
    assert len(world.overwrite_calls) == before + 1
    assert not restarted.last_prepare["content_hit"]
    await replay.release_now()


def _binding(slot=2):
    return DeviceSlotBinding("chime-1", slot, "owned.mp3", "old-md5", 10)


def test_sparse_numbered_inventory_never_falls_back_to_position():
    tracks = [
        {"track_no": 1, "name": "Default"},
        {"track_no": 7, "name": "other"},
    ]
    assert DynamicTtsSlotManager._reported_binding_track(tracks, _binding()) is None
    assert DynamicTtsSlotManager._reported_binding_track(tracks, _binding(7)) is tracks[1]


def test_mixed_inventory_does_not_infer_a_physical_number_for_unnumbered_rows():
    tracks = [{"track_no": 1}, {"name": "owned"}]
    assert DynamicTtsSlotManager._reported_binding_track(tracks, _binding()) is None


@pytest.mark.parametrize("number", [0, -1, True, 2.5, "invalid"])
def test_invalid_explicit_track_numbers_are_rejected(number):
    with pytest.raises(DynamicSlotUnavailable, match="invalid physical track number"):
        DynamicTtsSlotManager._reported_binding_track([{"track_no": number}], _binding())


def test_duplicate_physical_numbers_remain_ambiguous():
    with pytest.raises(DynamicSlotUnavailable, match="ambiguous"):
        DynamicTtsSlotManager._reported_binding_track([
            {"track_no": 2}, {"trackNo": 2},
        ], _binding())
