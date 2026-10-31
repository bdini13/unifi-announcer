"""Own direct-write inventory updates must not look like controller conflicts."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from app.playback.dynamic_slots import DynamicSlotUnavailable
from test_production_slot_content_reuse import (
    FakeProtectWorld, bootstrap, make_manager, make_target,
)


@pytest.mark.asyncio
async def test_expected_inventory_event_during_prepare_preserves_lease(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    overwrite = target.direct_client.overwrite_owned_slot

    async def write_with_feedback(**kwargs):
        result = await overwrite(**kwargs)
        manager.observe_inventory("chime-1", (await world.get_chime("chime-1"))["speakerTrackList"])
        return result

    target.direct_client.overwrite_owned_slot = write_with_feedback
    lease = await manager.prepare(b"expected speech", [target])
    manager.validate_prepared(lease, "chime-1")
    chime = await world.get_chime("chime-1")
    assert manager.verify_owned_play(lease.ringtone_id, "chime-1", chime)
    assert manager._pending_writes == {}

    # The same feedback arriving after commit is benign too.
    manager.observe_inventory("chime-1", chime["speakerTrackList"])
    manager.validate_prepared(lease, "chime-1")
    await lease.release_now()


@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.asyncio
async def test_fresh_prepared_content_restore_without_event_is_rejected_at_play(tmp_path, reuse):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    lease = await manager.prepare(b"fresh speech", [target])
    if reuse:
        await lease.release_now()
        assert not manager._fresh_lease_content
        lease = await manager.prepare(b"fresh speech", [target])
        assert manager.last_prepare["content_hit"]
    binding = manager.slots[lease.logical_slot].bindings["chime-1"]
    chime = await world.get_chime("chime-1")
    track = manager._reported_binding_track(chime["speakerTrackList"], binding)
    track.update(md5=binding.provisioning_md5, size=binding.provisioning_size)

    with pytest.raises(DynamicSlotUnavailable, match="content changed after fresh preparation"):
        manager.verify_owned_play(lease.ringtone_id, "chime-1", chime)
    with pytest.raises(DynamicSlotUnavailable, match="changed ringtone state"):
        manager.validate_prepared(lease, "chime-1")
    assert not manager._trusted_content
    await lease.release_now()
    assert not manager._fresh_lease_content


@pytest.mark.asyncio
async def test_stale_inventory_fallback_keeps_owned_play_compatibility(tmp_path):
    world = FakeProtectWorld(stale_control_plane=True)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    lease = await manager.prepare(b"speech not yet visible in Protect", [target])
    assert not manager._fresh_lease_content
    assert manager.verify_owned_play(
        lease.ringtone_id, "chime-1", await world.get_chime("chime-1")
    )
    await lease.release_now()


@pytest.mark.parametrize("conflict", ["canonical-restore", "other-slot", "missing", "malformed"])
@pytest.mark.asyncio
async def test_conflicting_inventory_during_prepare_revokes_target(tmp_path, conflict):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    overwrite = target.direct_client.overwrite_owned_slot

    async def write_with_conflicting_feedback(**kwargs):
        result = await overwrite(**kwargs)
        tracks = (await world.get_chime("chime-1"))["speakerTrackList"]
        if conflict == "canonical-restore":
            binding = next(
                slot.bindings["chime-1"] for slot in manager.slots.values()
                if slot.bindings["chime-1"].device_slot == kwargs["slot"]
            )
            tracks[kwargs["slot"] - 1].update(
                md5=binding.provisioning_md5, size=binding.provisioning_size,
            )
        elif conflict == "other-slot":
            other = next(index for index in range(len(tracks)) if index != kwargs["slot"] - 1)
            tracks[other]["fileName"] = "unexpected-other-slot-owner.mp3"
        elif conflict == "missing":
            tracks = []
        else:
            tracks = [None]
        manager.observe_inventory("chime-1", tracks)
        return result

    target.direct_client.overwrite_owned_slot = write_with_conflicting_feedback
    with pytest.raises(DynamicSlotUnavailable, match="changed ringtone state"):
        await manager.prepare(b"must be revoked", [target])
    assert manager._pending_writes == {}
    assert not manager._trusted_content
    assert not manager._busy


@pytest.mark.asyncio
async def test_expected_feedback_with_other_slot_already_revoked_does_not_block_recovery(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    await manager.invalidate_target_content(["chime-1"], reason="preset_mutation")
    assert not manager._trusted_content
    assert all(slot.bindings["chime-1"].current_md5 is None for slot in manager.slots.values())
    overwrite = target.direct_client.overwrite_owned_slot

    async def write_with_feedback(**kwargs):
        result = await overwrite(**kwargs)
        manager.observe_inventory("chime-1", (await world.get_chime("chime-1"))["speakerTrackList"])
        return result

    target.direct_client.overwrite_owned_slot = write_with_feedback
    lease = await manager.prepare(b"recover after mutation", [target])
    manager.validate_prepared(lease, "chime-1")
    assert manager._trusted_content == {(lease.logical_slot, "chime-1")}
    assert len(world.overwrite_calls) == 1
    await lease.release_now()


@pytest.mark.asyncio
async def test_changed_content_in_other_trusted_slot_still_revokes_pending_write(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    earlier = await manager.prepare(b"already trusted speech", [target])
    trusted_slot = manager.slots[earlier.logical_slot].bindings["chime-1"].device_slot
    await earlier.release_now()
    overwrite = target.direct_client.overwrite_owned_slot

    async def write_with_conflict_in_trusted_slot(**kwargs):
        assert kwargs["slot"] != trusted_slot
        result = await overwrite(**kwargs)
        tracks = (await world.get_chime("chime-1"))["speakerTrackList"]
        tracks[trusted_slot - 1]["md5"] = "restored-content-in-other-trusted-slot"
        manager.observe_inventory("chime-1", tracks)
        return result

    target.direct_client.overwrite_owned_slot = write_with_conflict_in_trusted_slot
    with pytest.raises(DynamicSlotUnavailable, match="changed ringtone state"):
        await manager.prepare(b"new speech", [target])
    assert not manager._trusted_content
    assert not manager._pending_writes


@pytest.mark.asyncio
async def test_matching_feedback_does_not_restore_revoked_trust(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    lease = await manager.prepare(b"must stay revoked", [target])
    manager.note_external_change(["chime-1"])
    manager.observe_inventory("chime-1", (await world.get_chime("chime-1"))["speakerTrackList"])
    with pytest.raises(DynamicSlotUnavailable, match="changed ringtone state"):
        manager.validate_prepared(lease, "chime-1")
    assert not manager._trusted_content
    await lease.release_now()


@pytest.mark.asyncio
async def test_cancelled_direct_write_clears_pending_fingerprint(tmp_path):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    assert (await manager.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    writing = asyncio.Event()

    async def blocked_write(**kwargs):
        writing.set()
        await asyncio.Event().wait()

    target.direct_client.overwrite_owned_slot = blocked_write
    task = asyncio.create_task(manager.prepare(b"cancelled write", [target]))
    await asyncio.wait_for(writing.wait(), 1)
    assert manager._pending_writes
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager._pending_writes == {}
    assert not manager._busy


@pytest.mark.asyncio
async def test_event_stream_forwards_inventory_without_invalidating_connected_heartbeat(
    main_module, monkeypatch,
):
    stream = main_module.ProtectEventStream()
    changed = Mock()
    stream.on_chime_content_change = changed
    monkeypatch.setattr(main_module.mqtt_bridge, "publish_event", AsyncMock())
    action = {"action": "update", "modelKey": "chime", "id": "chime-1"}

    # An unknown first connection may follow a missed reconnect; revoke once.
    await stream._handle(action, {"state": "CONNECTED"})
    changed.assert_called_once_with("chime-1", None)
    changed.reset_mock()
    await stream._handle(action, {"state": "CONNECTED"})
    changed.assert_not_called()
    tracks = [{"name": "owned", "track_no": 5, "md5": "expected", "size": 100}]
    await stream._handle(action, {"state": "CONNECTED", "speakerTrackList": tracks})
    changed.assert_called_once_with("chime-1", tracks)
    changed.reset_mock()
    await stream._handle(action, {"state": "DISCONNECTED"})
    changed.assert_called_once_with("chime-1", None)


@pytest.mark.asyncio
async def test_ringtone_catalog_event_remains_unconditional(main_module, monkeypatch):
    stream = main_module.ProtectEventStream()
    changed = Mock()
    stream.on_chime_content_change = changed
    monkeypatch.setattr(main_module.mqtt_bridge, "publish_event", AsyncMock())
    await stream._handle({"action": "update", "modelKey": "ringtone", "id": "tone"}, {})
    changed.assert_called_once_with(None, None)
