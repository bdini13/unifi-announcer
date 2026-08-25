"""Per-chime playback arbitration with dedupe and bounded priority queues."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import heapq
from time import perf_counter_ns
from typing import Any, Awaitable, Callable


class QueueDisposition(str, Enum):
    PLAYED = "played"
    QUEUED = "queued"
    DEDUPED = "deduped"
    DROPPED = "dropped"
    FAILED = "failed"


@dataclass
class PlaybackRequest:
    factory: Callable[[], Awaitable[dict[str, Any]]]
    priority: int = 50
    dedupe_key: str | None = None
    dedupe_window_ms: int = 1000
    enqueued_ns: int = field(default_factory=perf_counter_ns)

    async def run(self) -> dict[str, Any]:
        return await self.factory()


@dataclass
class QueueResult:
    disposition: QueueDisposition
    result: dict[str, Any] = field(default_factory=dict)
    queue_wait_ms: float | None = None


class ArbitrationQueue:
    """Bounded priority arbitration for one chime.

    Requests on one chime are serialized, priority orders queued work, and
    distinct ``ArbitrationQueue`` instances execute concurrently.
    """

    def __init__(self, name: str, *, max_depth: int = 16, metrics: Any = None) -> None:
        self.name = name
        self.max_depth = max_depth
        self.metrics = metrics
        self._heap: list[tuple[int, int, PlaybackRequest, asyncio.Future]] = []
        self._sequence = 0
        self._recent: dict[str, int] = {}
        self._worker: asyncio.Task | None = None
        self._active = False

    @property
    def depth(self) -> int:
        return len(self._heap) + int(self._active)

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self.worker())

    async def submit(self, request: PlaybackRequest) -> QueueResult:
        now = perf_counter_ns()
        # Values are expirations, not unbounded history. Prune opportunistically
        # on every submission so high-cardinality event keys cannot leak RAM.
        self._recent = {key: expires for key, expires in self._recent.items()
                        if expires > now}
        if request.dedupe_key and request.dedupe_key in self._recent:
            if self.metrics:
                self.metrics.inc("queue_deduped")
            return QueueResult(QueueDisposition.DEDUPED)
        if self.depth >= self.max_depth:
            candidates = []
            if request.priority == 0:  # emergency: displace anything queued
                candidates = [item for item in self._heap if item[0] > 0]
            elif request.priority <= 10:  # doorbell: displace informational work
                candidates = [item for item in self._heap if item[0] >= 100]
            if candidates:
                victim = max(candidates, key=lambda item: (item[0], item[1]))
                self._heap.remove(victim)
                heapq.heapify(self._heap)
                victim_future = victim[3]
                if not victim_future.done():
                    victim_future.set_result(QueueResult(QueueDisposition.DROPPED))
                if self.metrics:
                    self.metrics.inc("queue_dropped")
            elif request.priority != 0:
                if self.metrics:
                    self.metrics.inc("queue_dropped")
                return QueueResult(QueueDisposition.DROPPED)
            # Emergency is admitted even if the sole capacity is currently
            # active; an in-flight playback is never interrupted.
        if request.dedupe_key:
            self._recent[request.dedupe_key] = now + request.dedupe_window_ms * 1_000_000
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._sequence += 1
        heapq.heappush(self._heap, (request.priority, self._sequence, request, future))
        self._ensure_worker()
        return await future

    async def worker(self) -> None:
        try:
            while self._heap:
                _, _, request, future = heapq.heappop(self._heap)
                if future.cancelled():
                    continue
                self._active = True
                wait_ms = (perf_counter_ns() - request.enqueued_ns) / 1_000_000
                try:
                    result = await request.run()
                    outcome = QueueResult(QueueDisposition.PLAYED, result, wait_ms)
                except Exception as exc:
                    outcome = QueueResult(QueueDisposition.FAILED, {"error": str(exc)}, wait_ms)
                finally:
                    self._active = False
                if not future.done():
                    future.set_result(outcome)
        except asyncio.CancelledError:
            for _, _, _, future in self._heap:
                if not future.done():
                    future.cancel()
            self._heap.clear()
            raise

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None


@dataclass
class ChimeDescriptor:
    name: str
    chime_id: str
    direct_ip: str = ""


class ChimeRuntime:
    def __init__(self, desc: ChimeDescriptor, *, direct_client: Any = None,
                 metrics: Any = None, max_depth: int = 16) -> None:
        self.desc = desc
        self.direct_client = direct_client
        self.capability_state: Any = "not_yet_probed"
        self.queue = ArbitrationQueue(desc.name, max_depth=max_depth, metrics=metrics)
        self.probe_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start a read-only capability probe isolated to this chime."""
        if self.probe_task is not None:
            return
        if self.direct_client is None:
            self.capability_state = {"status": "unconfigured"}
            return
        self.probe_task = asyncio.create_task(self._probe_capabilities())

    async def _probe_capabilities(self) -> None:
        try:
            await self.direct_client.info()
            capabilities = self.direct_client.capabilities
            values = capabilities.to_dict() if capabilities is not None else {}
            self.capability_state = {"status": "available", **values}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Expose only the exception class: device errors can contain URLs or
            # credential material and capability reporting is a public GET.
            self.capability_state = {
                "status": "unavailable", "error_type": type(exc).__name__}

    async def stop(self) -> None:
        if self.probe_task is not None and not self.probe_task.done():
            self.probe_task.cancel()
            await asyncio.gather(self.probe_task, return_exceptions=True)
        self.probe_task = None
        await self.queue.stop()
