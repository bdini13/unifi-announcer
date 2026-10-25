"""Offline evidence for persistence boundaries and physical-target isolation."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.dispatcher import AnnouncementCommand, AnnouncementDispatcher
from app.playback import guards as guard_module
from app.playback.admission import DispatchAdmission
from app.playback.arbitration import ChimeDescriptor, ChimeRuntime
from app.playback.guards import PlaybackGuards


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(wall=1000.0, monotonic=100.0, boot="boot-one")
    monkeypatch.setattr(guard_module, "time", SimpleNamespace(
        time=lambda: value.wall, monotonic=lambda: value.monotonic))
    monkeypatch.setattr(guard_module, "_boot_identity", lambda: value.boot)
    return value


def target(name="one", identity="physical-one", max_depth=16):
    runtime = ChimeRuntime(ChimeDescriptor(name, identity))
    runtime.queue.max_depth = max_depth
    return runtime


def command(priority=50):
    return AnnouncementCommand(action="play_preset", preset="alert", priority=priority,
                               repeat_times=1)


def dispatcher(admission, physical, play):
    return AnnouncementDispatcher(
        protect=SimpleNamespace(play=play), chime=SimpleNamespace(),
        ringtone_index=SimpleNamespace(), synthesize=AsyncMock(), slug=lambda text: text,
        resolve_preset=AsyncMock(return_value="tone"), resolve_targets=lambda _: [physical],
        profile=lambda values: values, quiet=lambda: False, metrics=Mock(),
        volume_default=50, repeat_default=1, admission=admission,
        command_timeout=30, playback_fallback_seconds=2,
    )


def test_restart_preserves_deadline_by_physical_identity(tmp_path, clock):
    path = tmp_path / "guards.json"
    guards = PlaybackGuards(path)
    guards.hold(target(), 10)
    clock.wall += 3
    clock.monotonic += 3
    restarted = PlaybackGuards(path)
    assert restarted.remaining(target("renamed-alias")) == pytest.approx(7)
    assert restarted.remaining(target("different", "physical-two")) == 0


def test_forward_wall_clock_change_cannot_shorten_same_boot_hold(tmp_path, clock):
    path = tmp_path / "guards.json"
    guards = PlaybackGuards(path)
    guards.hold(target(), 10)
    clock.wall += 10000
    clock.monotonic += 2
    assert PlaybackGuards(path).remaining(target()) == pytest.approx(8)


def test_new_boot_rebases_once_and_persists_quarantine(tmp_path, clock):
    path = tmp_path / "guards.json"
    guards = PlaybackGuards(path)
    guards.hold(target(), 10)
    clock.wall += 10000
    clock.monotonic = 1
    clock.boot = "boot-two"
    restarted = PlaybackGuards(path)
    assert restarted.remaining(target()) == pytest.approx(10)
    clock.wall += 4
    clock.monotonic += 4
    assert restarted.remaining(target()) == pytest.approx(6)
    assert PlaybackGuards(path).remaining(target()) == pytest.approx(6)
    clock.wall += 6
    clock.monotonic += 6
    assert PlaybackGuards(path).remaining(target()) == 0


def test_expired_deadlines_do_not_reserve_targets(tmp_path, clock):
    guards = PlaybackGuards(tmp_path / "guards.json")
    guards.hold(target(), 1)
    clock.wall += 2
    clock.monotonic += 2
    assert guards.remaining(target()) == 0


@pytest.mark.parametrize("entry", [
    {"wall_until": 10, "monotonic_until": 9, "written_monotonic": 10},
    {"wall_until": float("nan"), "monotonic_until": 11, "written_monotonic": 10},
    {"wall_until": 10, "monotonic_until": True, "written_monotonic": 0},
])
def test_invalid_safety_state_fails_closed(tmp_path, clock, entry):
    path = tmp_path / "guards.json"
    path.write_text(json.dumps({"schema_version": 1, "targets": {"chime:one": entry}}))
    with pytest.raises(RuntimeError, match="state is invalid"):
        PlaybackGuards(path)


def test_failed_shortening_retains_prior_durable_and_in_memory_hold(tmp_path, clock, monkeypatch):
    guards = PlaybackGuards(tmp_path / "guards.json")
    guards.hold(target(), 60)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(guard_module, "atomic_json", fail)
    with pytest.raises(OSError, match="disk full"):
        guards.hold(target(), 2)
    assert guards.remaining(target()) == 60
    assert PlaybackGuards(guards.path).remaining(target()) == 60


@pytest.mark.asyncio
async def test_failed_preplay_commit_prevents_remote_command(tmp_path, clock, monkeypatch):
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)
    physical = target()
    play = AsyncMock()

    def fail(*args):
        raise OSError("guard commit failed")

    monkeypatch.setattr(guard_module, "atomic_json", fail)
    try:
        with pytest.raises(OSError, match="guard commit failed"):
            await dispatcher(admission, physical, play).dispatch(command())
        play.assert_not_awaited()
        assert guards.entries == {}
    finally:
        await admission.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "ambiguous"])
async def test_unacknowledged_play_retains_network_interval_across_shutdown(tmp_path, clock, failure):
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)
    physical = target()
    entered = asyncio.Event()

    async def play(*args, **kwargs):
        assert guards.remaining(physical) >= 33.25
        entered.set()
        if failure == "ambiguous":
            raise OSError("response lost after possible device acceptance")
        await asyncio.Event().wait()

    runner = dispatcher(admission, physical, play)
    task = asyncio.create_task(runner.dispatch(command()))
    try:
        await entered.wait()
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).disposition == "failed"
        await admission.stop()
        assert PlaybackGuards(guards.path).remaining(physical) >= 33.25
        assert physical.queue.admission_depth == 0
    finally:
        await admission.stop()


@pytest.mark.asyncio
async def test_acknowledged_play_shortens_only_the_network_interval(tmp_path, clock):
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)
    physical = target()

    async def play(*args, **kwargs):
        assert guards.remaining(physical) >= 33.25
        return {"played": True}

    try:
        assert (await dispatcher(admission, physical, play).dispatch(command())).disposition == "played"
        assert guards.remaining(physical) == pytest.approx(3.25)
    finally:
        await admission.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["announce", "play_preset"])
async def test_cancelled_slot_write_keeps_durable_uncertainty_window(tmp_path, clock, action):
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)
    physical = target()
    play = AsyncMock()
    runner = dispatcher(admission, physical, play)
    runner.synthesize = AsyncMock(return_value=b"audio")
    runner.synthesize_preset = AsyncMock(return_value=b"audio")

    async def prepare(*args):
        assert PlaybackGuards(guards.path).remaining(physical) == 30
        raise asyncio.CancelledError()

    runner.dynamic_slots = SimpleNamespace(prepare=prepare)
    try:
        with pytest.raises(asyncio.CancelledError):
            await runner.dispatch(AnnouncementCommand(
                action=action, text="hello" if action == "announce" else None,
                preset="alert" if action == "play_preset" else None,
                repeat_times=1,
            ))
        play.assert_not_awaited()
        assert physical.queue.admission_depth == 0
        assert PlaybackGuards(guards.path).remaining(physical) == 30
        assert admission.try_acquire([physical]) is None
    finally:
        await admission.stop()


@pytest.mark.asyncio
async def test_failed_prewrite_guard_prevents_physical_slot_upload(tmp_path, clock, monkeypatch):
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)
    physical = target()
    play, prepare = AsyncMock(), AsyncMock()
    runner = dispatcher(admission, physical, play)
    runner.synthesize = AsyncMock(return_value=b"audio")
    runner.dynamic_slots = SimpleNamespace(prepare=prepare)

    def fail(*args):
        raise OSError("guard commit failed")

    monkeypatch.setattr(guard_module, "atomic_json", fail)
    try:
        with pytest.raises(OSError, match="guard commit failed"):
            await runner.dispatch(AnnouncementCommand(action="announce", text="hello"))
        prepare.assert_not_awaited()
        play.assert_not_awaited()
    finally:
        await admission.stop()


@pytest.mark.asyncio
async def test_restart_guard_blocks_only_its_target_and_wakes_after_expiry(tmp_path, clock):
    path = tmp_path / "guards.json"
    first, second = target(), target("two", "physical-two")
    PlaybackGuards(path).hold(first, 10)
    admission = DispatchAdmission(guards=PlaybackGuards(path))
    waiting = asyncio.create_task(admission.acquire([first], command()))
    try:
        await asyncio.sleep(0)
        assert not waiting.done()
        other = await admission.acquire([second], command())
        other.release()
        clock.wall += 10
        clock.monotonic += 10
        admission._pump()
        released = await waiting
        released.release()
        assert first.queue.admission_depth == second.queue.admission_depth == 0
    finally:
        await admission.stop()


@pytest.mark.asyncio
async def test_maintenance_try_acquire_is_atomic_and_respects_pending_fairness(tmp_path, clock):
    guards = PlaybackGuards(tmp_path / "guards.json")
    first, second = target(), target("two", "physical-two")
    admission = DispatchAdmission(guards=guards)
    guards.hold(first, 10)
    waiting = asyncio.create_task(admission.acquire([first, second], command()))
    try:
        await asyncio.sleep(0)
        assert admission.try_acquire([second]) is None
        assert second.queue.admission_depth == 1
        assert admission.try_acquire([first, second]) is None
        assert not admission.busy
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        reservation = admission.try_acquire([second])
        assert reservation is not None
        assert admission.try_acquire([second]) is None
        reservation.release()
        assert second.queue.admission_depth == 0
    finally:
        await admission.stop()


@pytest.mark.asyncio
async def test_queued_maintenance_rejects_partial_preemption(clock):
    first = target(max_depth=2)
    admission = DispatchAdmission()
    occupied = await admission.acquire([first], command())
    waiting = asyncio.create_task(admission.acquire_maintenance([first]))
    emergency = None
    try:
        await asyncio.sleep(0)
        emergency = asyncio.create_task(admission.acquire([first], command(priority=0)))
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="displaced"):
            await waiting
        occupied.release()
        admitted = await emergency
        admitted.release()
        assert first.queue.admission_depth == 0
    finally:
        await admission.stop()


@pytest.mark.asyncio
async def test_shutdown_cancels_waiters_without_erasing_guard_or_waking_new_work(tmp_path, clock):
    physical = target()
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)
    reservation = await admission.acquire([physical], command())
    reservation.hold_for(physical, 10)
    reservation.release()
    waiting = asyncio.create_task(admission.acquire([physical], command()))
    await asyncio.sleep(0)
    await admission.stop()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert physical.queue.admission_depth == 0
    assert guards.remaining(physical) == 10
    assert admission._wake_handle is None
    assert admission.try_acquire([physical]) is None
    with pytest.raises(RuntimeError, match="stopping"):
        await admission.acquire([physical], command())
    admission.start()
    assert admission.try_acquire([physical]) is None  # Persisted hold still applies.
    await admission.stop()


@pytest.mark.asyncio
async def test_startup_defers_slot_writes_while_guarded(tmp_path, clock, monkeypatch):
    from app import server
    physical = target()
    guards = PlaybackGuards(tmp_path / "guards.json")
    guards.hold(physical, 10)
    admission = DispatchAdmission(guards=guards)
    slots = SimpleNamespace(ready=True, last_error=None, startup=AsyncMock(return_value={"ready": True}),
                            status=lambda: {"ready": slots.ready, "last_error": slots.last_error})
    monkeypatch.setattr(server, "admission", admission)
    monkeypatch.setattr(server, "dynamic_slots", slots)
    monkeypatch.setattr(server.core, "chime_runtimes", {"one": physical})
    monkeypatch.setattr(server.core, "ringtone_upload_lock", asyncio.Lock())
    try:
        result = await server._startup_dynamic_slots()
        assert not result["ready"]
        slots.startup.assert_not_awaited()
        clock.wall += 10
        clock.monotonic += 10
        await server._startup_dynamic_slots()
        slots.startup.assert_awaited_once()
        assert physical.queue.admission_depth == 0
    finally:
        await admission.stop()


@pytest.mark.asyncio
async def test_startup_reserves_targets_until_slot_work_finishes(clock, monkeypatch):
    from app import server
    physical = target()
    admission = DispatchAdmission()
    entered, release = asyncio.Event(), asyncio.Event()

    async def startup(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"ready": True}

    monkeypatch.setattr(server, "admission", admission)
    monkeypatch.setattr(server, "dynamic_slots", SimpleNamespace(startup=startup))
    monkeypatch.setattr(server.core, "chime_runtimes", {"one": physical})
    monkeypatch.setattr(server.core, "ringtone_upload_lock", asyncio.Lock())
    task = asyncio.create_task(server._startup_dynamic_slots())
    waiting = None
    try:
        await entered.wait()
        waiting = asyncio.create_task(admission.acquire([physical], command()))
        await asyncio.sleep(0)
        assert not waiting.done()
        release.set()
        await task
        reservation = await waiting
        reservation.release()
        assert physical.queue.admission_depth == 0
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await admission.stop()


@pytest.mark.asyncio
async def test_startup_rechecks_guard_after_waiting_for_upload_lock(tmp_path, clock, monkeypatch):
    from app import server
    physical = target()
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)
    lock = asyncio.Lock()
    slots = SimpleNamespace(ready=True, last_error=None, startup=AsyncMock(return_value={"ready": True}),
                            status=lambda: {"ready": slots.ready})
    monkeypatch.setattr(server, "admission", admission)
    monkeypatch.setattr(server, "dynamic_slots", slots)
    monkeypatch.setattr(server.core, "chime_runtimes", {"one": physical})
    monkeypatch.setattr(server.core, "ringtone_upload_lock", lock)
    await lock.acquire()
    task = asyncio.create_task(server._startup_dynamic_slots())
    try:
        await asyncio.sleep(0)
        guards.hold(physical, 10)
        lock.release()
        assert not (await task)["ready"]
        slots.startup.assert_not_awaited()
    finally:
        if lock.locked():
            lock.release()
        await asyncio.gather(task, return_exceptions=True)
        await admission.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancel", "error", "success"])
async def test_preset_mutation_persists_guard_until_confirmed_completion(tmp_path, clock, monkeypatch, outcome):
    from app import server
    physical = target()
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)

    @asynccontextmanager
    async def lifecycle(*args, **kwargs):
        yield

    monkeypatch.setattr(server, "admission", admission)
    monkeypatch.setattr(server, "dynamic_slots", SimpleNamespace(
        target_lifecycle_guard=lifecycle, note_external_change=Mock()))
    monkeypatch.setattr(server.core, "chime_runtimes", {"one": physical})
    monkeypatch.setattr(server.core.dispatcher, "command_timeout", 30)

    async def mutate():
        async with server._ringtone_mutation_guard():
            assert PlaybackGuards(guards.path).remaining(physical) == 30
            if outcome == "cancel":
                raise asyncio.CancelledError()
            if outcome == "error":
                raise OSError("response lost")

    try:
        if outcome == "success":
            await mutate()
        else:
            with pytest.raises(asyncio.CancelledError if outcome == "cancel" else OSError):
                await mutate()
        assert PlaybackGuards(guards.path).remaining(physical) == (0 if outcome == "success" else 30)
        assert physical.queue.admission_depth == 0
        assert not admission.busy
    finally:
        await admission.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancel", "not_ready", "migration_error", "success"])
async def test_startup_retains_uncertain_write_guard_on_incomplete_result(tmp_path, clock, monkeypatch, outcome):
    from app import server
    physical = target()
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)

    async def startup(*args, **kwargs):
        assert PlaybackGuards(guards.path).remaining(physical) == 30
        if outcome == "cancel":
            raise asyncio.CancelledError()
        return {"ready": outcome != "not_ready",
                "migration_error": "uncertain remote write" if outcome == "migration_error" else None}

    monkeypatch.setattr(server, "admission", admission)
    monkeypatch.setattr(server, "dynamic_slots", SimpleNamespace(startup=startup))
    monkeypatch.setattr(server.core, "chime_runtimes", {"one": physical})
    monkeypatch.setattr(server.core, "ringtone_upload_lock", asyncio.Lock())
    monkeypatch.setattr(server.core.dispatcher, "command_timeout", 30)
    try:
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await server._startup_dynamic_slots()
        else:
            await server._startup_dynamic_slots()
        assert PlaybackGuards(guards.path).remaining(physical) == (0 if outcome == "success" else 30)
        assert physical.queue.admission_depth == 0
        assert not admission.busy
    finally:
        await admission.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["startup", "preset"])
async def test_failed_maintenance_guard_clear_keeps_hold_and_releases_reservation(tmp_path, clock, monkeypatch, operation):
    from app import server
    physical = target()
    guards = PlaybackGuards(tmp_path / "guards.json")
    admission = DispatchAdmission(guards=guards)

    @asynccontextmanager
    async def lifecycle(*args, **kwargs):
        yield

    original = guard_module.atomic_json

    def fail_clear(path, payload):
        if payload["targets"][PlaybackGuards.key(physical)]["wall_until"] == clock.wall:
            raise OSError("durable guard clear failed")
        return original(path, payload)

    monkeypatch.setattr(guard_module, "atomic_json", fail_clear)
    monkeypatch.setattr(server, "admission", admission)
    monkeypatch.setattr(server, "dynamic_slots", SimpleNamespace(
        startup=AsyncMock(return_value={"ready": True}),
        target_lifecycle_guard=lifecycle, note_external_change=Mock()))
    monkeypatch.setattr(server.core, "chime_runtimes", {"one": physical})
    monkeypatch.setattr(server.core, "ringtone_upload_lock", asyncio.Lock())
    monkeypatch.setattr(server.core.dispatcher, "command_timeout", 30)
    try:
        with pytest.raises(OSError, match="guard clear failed"):
            if operation == "startup":
                await server._startup_dynamic_slots()
            else:
                async with server._ringtone_mutation_guard():
                    pass
        assert guards.remaining(physical) == PlaybackGuards(guards.path).remaining(physical) == 30
        assert physical.queue.admission_depth == 0
        assert not admission.busy
    finally:
        await admission.stop()
