import asyncio
import json
from types import SimpleNamespace

import pytest

from app.playback.dynamic_slots import DynamicSlotUnavailable
from test_production_slot_content_reuse import (
    FakeProtectWorld, bootstrap, make_manager, make_target,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", [
    "top_level", "slot_row", "binding_row", "generation", "negative_generation",
    "nonfinite_epoch", "source_size", "timestamp", "oversized_timestamp",
])
async def test_corrupt_optional_cache_becomes_a_safe_miss(tmp_path, corruption):
    world = FakeProtectWorld(stale_control_plane=False)
    target = make_target(world)
    first = make_manager(tmp_path, world)
    assert (await first.startup([target], bootstrap_audio_factory=bootstrap))["ready"]
    lease = await first.prepare(b"known phrase", [target])
    await lease.release_now()
    await first.shutdown()

    raw = json.loads(first.content_state_path.read_text())
    entry = raw["bindings"][str(lease.logical_slot)]["chime-1"]
    if corruption == "top_level":
        raw = []
    elif corruption == "slot_row":
        raw["bindings"] = {"1": "invalid row", "2": []}
    elif corruption == "binding_row":
        raw["bindings"][str(lease.logical_slot)]["chime-1"] = []
    elif corruption == "generation":
        entry["write_generation"] = "not a number"
    elif corruption == "negative_generation":
        entry["write_generation"] = -1
    elif corruption == "nonfinite_epoch":
        entry["device_boot_epoch"] = float("nan")
    elif corruption == "source_size":
        entry["source_size"] = True
    elif corruption == "timestamp":
        entry["last_used_at"] = {}
    elif corruption == "oversized_timestamp":
        entry["written_at"] = 10 ** 400
    first.content_state_path.write_text(json.dumps(raw))
    uploads_before = world.upload_calls
    writes_before = len(world.overwrite_calls)

    restarted = make_manager(tmp_path, world)
    status = await restarted.startup([target], bootstrap_audio_factory=bootstrap)
    assert status["ready"]
    assert status["content_reuse"]["trusted_bindings"] == 0
    assert restarted.metrics.counters["tts_slot_content_state_resets"] == 1
    lease = await restarted.prepare(b"known phrase", [target])
    await lease.release_now()
    assert world.upload_calls == uploads_before  # Ownership registry survives.
    assert len(world.overwrite_calls) == writes_before + 1
    await restarted.shutdown()


@pytest.mark.asyncio
async def test_recovery_stays_unavailable_through_migration_and_content_restore(tmp_path):
    world = FakeProtectWorld()
    target = make_target(world)
    manager = make_manager(tmp_path, world)
    migration_entered = asyncio.Event()
    migration_release = asyncio.Event()
    restore_entered = asyncio.Event()
    restore_release = asyncio.Event()
    restore = manager._restore_startup_state

    async def paused_migration(_registry):
        migration_entered.set()
        await migration_release.wait()

    async def paused_restore():
        restore_entered.set()
        await restore_release.wait()
        await restore()

    manager._migrate_legacy = paused_migration
    manager._restore_startup_state = paused_restore
    startup = asyncio.create_task(manager.startup(
        [target], bootstrap_audio_factory=bootstrap,
        legacy_registry=SimpleNamespace(records={}),
    ))
    try:
        await asyncio.wait_for(migration_entered.wait(), 1)
        assert not manager.status()["ready"]
        with pytest.raises(DynamicSlotUnavailable, match="not ready"):
            await manager.prepare(b"too early", [target])
        migration_release.set()
        await asyncio.wait_for(restore_entered.wait(), 1)
        assert not manager.status()["ready"]
        with pytest.raises(DynamicSlotUnavailable, match="not ready"):
            await manager.prepare(b"still too early", [target])
        restore_release.set()
        assert (await startup)["ready"]
        assert manager._device_identities
        assert not world.overwrite_calls
    finally:
        migration_release.set()
        restore_release.set()
        await startup
        await manager.shutdown()
