"""Bound preparation and reserve physical targets through estimated playback."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from types import SimpleNamespace
from typing import Any


@dataclass(eq=False)
class Reservation:
    owner: Any
    targets: list
    priority: int
    sequence: int
    future: asyncio.Future
    excluded: list = field(default_factory=list)
    started: float = field(default_factory=monotonic)
    wait_ms: float = 0
    holds: dict = field(default_factory=dict)
    released: bool = False

    def hold_for(self, target, seconds: float, *, in_flight_seconds: float = 0) -> None:
        key = self.owner.key(target)
        self.holds[key] = max(self.holds.get(key, 0), monotonic() + seconds)
        if self.owner.guards is not None:
            # Persist before a play request. Its uncertain network interval is
            # included until the caller records the final playback deadline.
            self.owner.guards.hold(target, seconds + in_flight_seconds)

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        for target in self.targets:
            delay = max(0, self.holds.get(self.owner.key(target), 0) - monotonic())
            if delay:
                task = asyncio.create_task(asyncio.sleep(delay))
                self.owner.releases.add(task)
                task.add_done_callback(lambda done, target=target: self.owner._released_task(done, target))
            else:
                self.owner._release(target)
        self.owner._pump()


class DispatchAdmission:
    """Admit per-target work before synthesis; atomically acquire whole groups.

    Only waiting work can be displaced. Even emergency requests obey capacity.
    Independent targets remain concurrent; overlapping groups cannot deadlock.
    """

    def __init__(self, *, guards=None) -> None:
        self.pending: list[Reservation] = []
        self.busy: set[tuple] = set()
        self.recent: dict[tuple, float] = {}
        self.sequence = 0
        self.releases: set[asyncio.Task] = set()
        self.guards = guards
        self._wake_handle = None
        self._stopped = False

    @staticmethod
    def key(target) -> tuple:
        desc = target.desc
        return (desc.kind, desc.device_id)

    def start(self) -> None:
        if self.pending or self.busy:
            raise RuntimeError("cannot restart admission while reservations remain")
        self._stopped = False

    @staticmethod
    def _exclude(target, disposition: str) -> dict:
        identity = "camera_id" if target.desc.kind == "camera" else "chime_id"
        if target.queue.metrics:
            target.queue.metrics.inc(f"queue_{disposition}")
        return {"target": target.desc.name, "target_type": target.desc.kind,
                identity: target.desc.device_id, "disposition": disposition}

    async def acquire(self, targets: list, command) -> Reservation:
        if self._stopped:
            raise RuntimeError("announcement admission is stopping")
        self.sequence += 1
        item = Reservation(self, [], command.priority, self.sequence,
                           asyncio.get_running_loop().create_future())
        now = monotonic()
        self.recent = {key: expiry for key, expiry in self.recent.items() if expiry > now}
        for target in targets:
            key = self.key(target)
            dedupe = (key, command.dedupe_key)
            if command.dedupe_key and dedupe in self.recent:
                item.excluded.append(self._exclude(target, "deduped"))
                continue
            if target.queue.admission_depth >= target.queue.max_depth:
                victims = [entry for entry in self.pending if target in entry.targets and (
                    (command.priority == 0 and entry.priority > 0)
                    or (command.priority <= 10 and entry.priority >= 100))]
                if not victims:
                    item.excluded.append(self._exclude(target, "dropped"))
                    continue
                victim = max(victims, key=lambda entry: (entry.priority, entry.sequence))
                victim.targets.remove(target)
                target.queue.admission_depth -= 1
                victim.excluded.append(self._exclude(target, "dropped"))
            target.queue.admission_depth += 1
            item.targets.append(target)
            if command.dedupe_key:
                self.recent[dedupe] = now + command.dedupe_window_ms / 1000
        self.pending.append(item)
        self._pump()
        try:
            await item.future
            return item
        except asyncio.CancelledError:
            if item in self.pending:
                self.pending.remove(item)
                for target in item.targets:
                    target.queue.admission_depth -= 1
            else:
                item.release()
            self._pump()
            raise

    def try_acquire(self, targets: list) -> Reservation | None:
        """Immediately reserve all maintenance targets, or leave state untouched.

        Maintenance cannot bypass queued announcements, playback deadlines,
        occupied targets, or capacity. The caller must release in finally.
        """
        if self._stopped:
            return None
        unique = list({self.key(target): target for target in targets}.values())
        keys = {self.key(target) for target in unique}
        if keys & self.busy or any(
            not item.future.cancelled()
            and keys.intersection(self.key(target) for target in item.targets)
            for item in self.pending
        ):
            return None
        if any(target.queue.admission_depth >= target.queue.max_depth
               or (self.guards is not None and self.guards.remaining(target) > 0)
               for target in unique):
            return None
        self.sequence += 1
        item = Reservation(self, unique, 50, self.sequence,
                           asyncio.get_running_loop().create_future())
        for target in unique:
            target.queue.admission_depth += 1
        self.busy.update(keys)
        item.future.set_result(None)
        return item

    async def acquire_maintenance(self, targets: list) -> Reservation:
        """Queue a whole-target maintenance reservation without partial work.

        A full queue is rejected before admission. Once queued, ordinary
        priority/fairness and durable playback deadlines apply.
        """
        unique = list({self.key(target): target for target in targets}.values())
        if any(target.queue.admission_depth >= target.queue.max_depth for target in unique):
            raise RuntimeError("maintenance cannot reserve all targets: announcement queue is full")
        reservation = await self.acquire(unique, SimpleNamespace(
            priority=50, dedupe_key=None, dedupe_window_ms=0))
        if reservation.excluded:
            reservation.release()
            raise RuntimeError("maintenance reservation was displaced; no mutation may proceed")
        return reservation

    def _pump(self) -> None:
        if self._wake_handle is not None:
            self._wake_handle.cancel()
            self._wake_handle = None
        if self._stopped:
            return
        blocked = set()
        delays = []
        for item in sorted(self.pending, key=lambda entry: (entry.priority, entry.sequence)):
            if item.future.cancelled():
                continue
            keys = {self.key(target) for target in item.targets}
            remaining = max((self.guards.remaining(target) for target in item.targets), default=0) if self.guards is not None else 0
            if remaining:
                delays.append(remaining)
                blocked.update(keys)
                continue
            if keys & (self.busy | blocked):
                blocked.update(keys)
                continue
            self.pending.remove(item)
            self.busy.update(keys)
            item.wait_ms = (monotonic() - item.started) * 1000
            if not item.future.done():
                item.future.set_result(None)
        if delays:
            self._wake_handle = asyncio.get_running_loop().call_later(min(delays), self._pump)

    def _release(self, target) -> None:
        self.busy.discard(self.key(target))
        target.queue.admission_depth -= 1

    def _released_task(self, task, target) -> None:
        self.releases.discard(task)
        self._release(target)
        self._pump()

    async def stop(self) -> None:
        self._stopped = True
        if self._wake_handle is not None:
            self._wake_handle.cancel()
            self._wake_handle = None
        for item in list(self.pending):
            self.pending.remove(item)
            for target in item.targets:
                target.queue.admission_depth -= 1
            item.targets.clear()
            item.future.cancel()
        for task in self.releases:
            task.cancel()
        await asyncio.gather(*self.releases, return_exceptions=True)
