import asyncio
from types import SimpleNamespace

import pytest

from app.playback.recovery import SlotRecovery


@pytest.mark.asyncio
async def test_startup_failure_recovers_once_without_manual_restart():
    manager = SimpleNamespace(ready=False, last_error=None)
    manager.status = lambda: {"ready": manager.ready, "last_error": manager.last_error}
    calls = 0
    recovered = asyncio.Event()

    async def startup():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("offline")
        manager.ready = True
        recovered.set()
        return manager.status()

    recovery = SlotRecovery(manager, startup, interval=.001)
    assert not (await recovery.attempt())["ready"]
    recovery.start()
    await asyncio.wait_for(recovered.wait(), .2)
    await recovery.task
    assert calls == 2
    await recovery.stop()


@pytest.mark.asyncio
async def test_attempt_timeout_and_shutdown_cancel_pending_startup():
    manager = SimpleNamespace(ready=False, last_error=None)
    manager.status = lambda: {"ready": manager.ready, "last_error": manager.last_error}
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def startup():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    recovery = SlotRecovery(manager, startup, interval=.001, timeout=.01)
    assert not (await recovery.attempt())["ready"]
    assert "TimeoutError" in manager.last_error
    entered.clear()
    cancelled.clear()
    recovery.start()
    await entered.wait()
    await recovery.stop()
    assert cancelled.is_set()
    assert recovery.task is None


@pytest.mark.asyncio
async def test_production_recovery_waits_for_preset_upload_before_allocating(monkeypatch):
    from unittest.mock import AsyncMock
    from app import server
    lock = asyncio.Lock()
    startup = AsyncMock(return_value={"ready": True})
    monkeypatch.setattr(server.core, "ringtone_upload_lock", lock)
    monkeypatch.setattr(server, "dynamic_slots", SimpleNamespace(startup=startup))
    async with lock:
        recovery = asyncio.create_task(server._startup_dynamic_slots())
        await asyncio.sleep(0)
        startup.assert_not_awaited()
    assert (await asyncio.wait_for(recovery, .2))["ready"]
    startup.assert_awaited_once()
