import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.dispatcher import AnnouncementCommand
from app.playback.admission import DispatchAdmission
from app.playback.arbitration import ChimeDescriptor, ChimeRuntime
from test_dispatcher import _dispatcher


def target(name, depth=3):
    return ChimeRuntime(ChimeDescriptor(name, name), max_depth=depth)


def command(priority=50, key=None):
    return AnnouncementCommand(action="announce", text="hello", priority=priority,
                               dedupe_key=key)


@pytest.mark.asyncio
async def test_priority_eviction_and_emergency_capacity_are_bounded():
    scheduler = DispatchAdmission()
    one = target("one", 2)
    active = await scheduler.acquire([one], command())
    info_task = asyncio.create_task(scheduler.acquire([one], command(100)))
    await asyncio.sleep(0)
    urgent_task = asyncio.create_task(scheduler.acquire([one], command(0)))
    await asyncio.sleep(0)
    evicted = await info_task
    assert evicted.targets == []
    assert evicted.excluded[0]["disposition"] == "dropped"
    overloaded = await scheduler.acquire([one], command(0))
    assert overloaded.targets == []
    assert one.queue.depth == 2
    active.release()
    urgent = await urgent_task
    urgent.release()
    assert one.queue.depth == 0


@pytest.mark.asyncio
async def test_queued_priority_and_disjoint_groups():
    scheduler = DispatchAdmission()
    a, b, c = target("a"), target("b"), target("c")
    active = await scheduler.acquire([a], command())
    low_task = asyncio.create_task(scheduler.acquire([a, b], command(100)))
    high_task = asyncio.create_task(scheduler.acquire([b, a], command(10)))
    await asyncio.sleep(0)
    independent = await scheduler.acquire([c], command())
    independent.release()
    active.release()
    high = await asyncio.wait_for(high_task, .2)
    assert not low_task.done()
    high.release()
    low = await asyncio.wait_for(low_task, .2)
    low.release()
    assert not scheduler.busy


@pytest.mark.asyncio
async def test_partial_dedupe_does_not_reserve_already_seen_target():
    scheduler = DispatchAdmission()
    a, b = target("a"), target("b")
    first = await scheduler.acquire([a], command(key="event"))
    first.release()
    second = await scheduler.acquire([a, b], command(key="event"))
    assert second.targets == [b]
    assert second.excluded[0]["target"] == "a"
    assert second.excluded[0]["disposition"] == "deduped"
    second.release()


@pytest.mark.asyncio
async def test_cancel_waiter_restores_capacity_without_releasing_owner():
    scheduler = DispatchAdmission()
    a = target("a")
    owner = await scheduler.acquire([a], command())
    waiter = asyncio.create_task(scheduler.acquire([a], command()))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert a.queue.depth == 1
    assert scheduler.key(a) in scheduler.busy
    owner.release()
    assert a.queue.depth == 0


@pytest.mark.asyncio
async def test_cancel_just_granted_reservation_releases_it():
    scheduler = DispatchAdmission()
    a = target("a")
    owner = await scheduler.acquire([a], command())
    waiter = asyncio.create_task(scheduler.acquire([a], command()))
    await asyncio.sleep(0)
    owner.release()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert a.queue.depth == 0
    assert not scheduler.busy


@pytest.mark.asyncio
async def test_dedupe_and_overload_skip_synthesis_and_slot_preparation():
    a = target("a", 1)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def synthesize(_):
        entered.set()
        await finish.wait()
        return b"audio"

    dispatcher = _dispatcher(protect=SimpleNamespace(play=AsyncMock(return_value={})), targets=[a])
    scheduler = dispatcher.admission = DispatchAdmission()
    dispatcher.synthesize = AsyncMock(side_effect=synthesize)
    lease = SimpleNamespace(ringtone_id="ring", duration_ms=10, logical_slot=1,
                            release_after=Mock(), release_now=AsyncMock())
    dispatcher.dynamic_slots = SimpleNamespace(prepare=AsyncMock(return_value=lease))
    first = asyncio.create_task(dispatcher.dispatch(command(key="event")))
    await entered.wait()
    duplicate = await dispatcher.dispatch(command(key="event"))
    dropped = await dispatcher.dispatch(command())
    assert duplicate.disposition == "deduped"
    assert dropped.disposition == "dropped"
    dispatcher.synthesize.assert_awaited_once()
    dispatcher.dynamic_slots.prepare.assert_not_awaited()
    finish.set()
    assert (await first).disposition == "played"
    assert a.queue.depth == 1  # Acoustic guard survives the HTTP response.
    await scheduler.stop()
    assert a.queue.depth == 0


@pytest.mark.asyncio
async def test_audio_guard_survives_failed_play_request_and_waiter_deadline():
    a = target("a")
    dispatcher = _dispatcher(protect=SimpleNamespace(play=AsyncMock(side_effect=OSError("ambiguous"))), targets=[a])
    scheduler = dispatcher.admission = DispatchAdmission()
    dispatcher.command_timeout = .025
    dispatcher.playback_fallback_seconds = .01
    preset = AnnouncementCommand(action="play_preset", preset="saved", repeat_times=1)
    assert (await dispatcher.dispatch(preset)).disposition == "failed"
    with pytest.raises(RuntimeError, match="deadline exceeded"):
        await dispatcher.dispatch(preset)
    dispatcher.protect.play.assert_awaited_once()
    assert a.queue.depth == 1
    await scheduler.stop()


@pytest.mark.asyncio
async def test_later_play_request_waits_for_audio_guard():
    a = target("a")
    dispatcher = _dispatcher(protect=SimpleNamespace(play=AsyncMock(return_value={})), targets=[a])
    scheduler = dispatcher.admission = DispatchAdmission()
    dispatcher.playback_fallback_seconds = .01
    preset = AnnouncementCommand(action="play_preset", preset="saved", repeat_times=1)
    await dispatcher.dispatch(preset)
    later = asyncio.create_task(dispatcher.dispatch(preset))
    await asyncio.sleep(.02)
    dispatcher.protect.play.assert_awaited_once()
    assert (await asyncio.wait_for(later, 2)).disposition == "played"
    assert dispatcher.protect.play.await_count == 2
    await scheduler.stop()


@pytest.mark.asyncio
async def test_shutdown_reaps_active_preparation_and_waiters_before_resources():
    a = target("a")
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def synthesize(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    dispatcher = _dispatcher(protect=SimpleNamespace(), targets=[a])
    scheduler = dispatcher.admission = DispatchAdmission()
    dispatcher.dynamic_slots = SimpleNamespace()
    dispatcher.synthesize = synthesize
    first = asyncio.create_task(dispatcher.dispatch(command()))
    await entered.wait()
    second = asyncio.create_task(dispatcher.dispatch(command()))
    await asyncio.sleep(0)
    await dispatcher.stop()
    await scheduler.stop()
    assert first.cancelled() and second.cancelled() and cancelled.is_set()
    assert a.queue.depth == 0
    assert not scheduler.busy
    with pytest.raises(RuntimeError, match="stopping"):
        await dispatcher.dispatch(command())


@pytest.mark.asyncio
async def test_upstream_timeout_is_not_misreported_as_command_deadline():
    a = target("a")
    dispatcher = _dispatcher(protect=SimpleNamespace(), targets=[a])
    dispatcher.dynamic_slots = SimpleNamespace()
    dispatcher.synthesize = AsyncMock(side_effect=TimeoutError("Piper timeout"))
    with pytest.raises(TimeoutError, match="Piper timeout"):
        await dispatcher.dispatch(command())


@pytest.mark.asyncio
async def test_shutdown_releases_guard_even_before_its_timer_starts():
    scheduler = DispatchAdmission()
    a = target("a")
    reservation = await scheduler.acquire([a], command())
    reservation.hold_for(a, 30)
    reservation.release()
    await scheduler.stop()
    assert a.queue.depth == 0
    assert not scheduler.busy
    assert not scheduler.releases
