"""Single canonical dispatcher for REST, rules, and MQTT commands."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Any, Awaitable, Callable, Literal

from app.observability import AnnouncementTiming
from app.playback.arbitration import PlaybackRequest, QueueDisposition, QueueResult
from app.tracks import RingtoneCapacityError, TrackRecord

Action = Literal["announce", "buzzer", "play_default", "play_preset"]


class StaleRingtoneError(RuntimeError):
    """Protect explicitly rejected a cached ringtone identity."""


@dataclass
class AnnouncementCommand:
    action: Action
    text: str | None = None
    preset: str | None = None
    volume: int | None = None
    repeat_times: int | None = None
    profile: str | None = None
    target: str | None = None
    priority: int = 50
    dedupe_key: str | None = None
    dedupe_window_ms: int = 1000
    source: str = "api"


@dataclass
class DispatchResult:
    action: str
    disposition: str
    result: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] | None = None

    def response(self) -> dict[str, Any]:
        value = dict(self.result)
        value["disposition"] = self.disposition
        if self.timings is not None:
            value["timings"] = self.timings
        return value


class SuppressedResult(DispatchResult):
    """A successful dispatch decision that intentionally produced no sound."""

    def __init__(self, action: str, detail: str,
                 timings: dict[str, float] | None = None) -> None:
        super().__init__(action=action, disposition="suppressed",
                         result={"detail": detail}, timings=timings)


class AnnouncementDispatcher:
    """Validate → profile → quiet → targets → audio → per-chime queues."""

    def __init__(self, *, protect: Any, chime: Any, ringtone_index: Any,
                 synthesize: Callable[[str], Awaitable[bytes]],
                 slug: Callable[[str], str],
                 resolve_preset: Callable[[str], Awaitable[str]],
                 resolve_targets: Callable[[str | None], list],
                 profile: Callable[[dict], dict], quiet: Callable[[], bool],
                 metrics: Any, volume_default: int, repeat_default: int,
                 debug_timings: bool = False,
                 playback_policy: Any | None = None,
                 track_registry: Any | None = None,
                 track_reconciler: Any | None = None,
                 ringtone_backend: Any | None = None,
                 upload_lock: asyncio.Lock | None = None) -> None:
        self.protect = protect
        self.ringtone_backend = ringtone_backend or protect
        self.chime = chime
        self.index = ringtone_index
        self.synthesize = synthesize
        self.slug = slug
        self.resolve_preset = resolve_preset
        self.resolve_targets = resolve_targets
        self.profile = profile
        self.quiet = quiet
        self.metrics = metrics
        self.volume_default = volume_default
        self.repeat_default = repeat_default
        self.debug_timings = debug_timings
        self.playback_policy = playback_policy
        self.track_registry = track_registry
        self.track_reconciler = track_reconciler
        self._creation_locks: dict[str, asyncio.Lock] = {}
        self._creation_lock_users: dict[str, int] = {}
        self._upload_lock = upload_lock or asyncio.Lock()

    async def dispatch(self, command: AnnouncementCommand) -> DispatchResult:
        total_started = perf_counter_ns()
        timing = AnnouncementTiming()
        try:
            self._validate(command)
            use_device_defaults = (
                command.action == "play_default"
                and command.volume is None
                and command.repeat_times is None
                and command.profile is None
            )
            if use_device_defaults:
                volume, repeat = None, None
            elif self.playback_policy is not None:
                volume, repeat = self.playback_policy.resolve(
                    volume=command.volume, repeat_times=command.repeat_times,
                    profile=command.profile,
                )
            else:
                values = self.profile({"profile": command.profile, "volume": command.volume,
                                       "repeat": command.repeat_times})
                volume = values.get("volume") if values.get("volume") is not None else self.volume_default
                repeat = values.get("repeat") if values.get("repeat") is not None else self.repeat_default
            quiet = self.quiet()
            suppressed = (self.playback_policy.suppresses(quiet=quiet, priority=command.priority)
                          if self.playback_policy is not None
                          else quiet and command.priority >= 50)
            if command.action != "buzzer" and suppressed:
                self._record_finish("suppressed", timing, total_started)
                return SuppressedResult(
                    command.action, "suppressed during quiet hours",
                    timing.as_dict() if self.debug_timings else None,
                )

            targets = self.resolve_targets(command.target)
            if not targets:
                if command.target:
                    raise ValueError(f"unknown or empty target: {command.target}")
                raise RuntimeError("no chime targets are configured")

            ringtone_id: str | None = None
            ringtone_name: str | None = None
            if command.action == "play_preset":
                ringtone_name = command.preset or ""
                ringtone_id = await self.resolve_preset(command.preset or "")
            elif command.action == "announce":
                ringtone_name = self.slug(command.text or "")
                ringtone_id = await self._resolve_announcement(command, timing, targets)

            async def submit(target):
                chime_id = target.desc.chime_id
                dispatch_at_ns: int | None = None

                async def play() -> dict[str, Any]:
                    nonlocal dispatch_at_ns, ringtone_id
                    dispatch_at_ns = perf_counter_ns()
                    target_kw = {"chime_id": chime_id} if chime_id else {}
                    if command.action == "buzzer":
                        return await self.protect.play_buzzer(**target_kw)
                    if command.action == "play_default":
                        return await self.protect.play_default(
                            volume, repeat, **target_kw)
                    async def play_ringtone() -> dict[str, Any]:
                        if command.source == "rule":
                            return await self.protect.play(
                                ringtone_id, volume=volume, repeat_times=repeat,
                                **target_kw)
                        return await self.protect.play(
                            ringtone_id, volume, repeat, **target_kw)

                    try:
                        return await play_ringtone()
                    except StaleRingtoneError:
                        if not ringtone_name:
                            raise
                        self.index.invalidate(ringtone_name)
                        await self.index.force_refresh()
                        refreshed = self.index.get(ringtone_name)
                        if not refreshed:
                            raise
                        ringtone_id = refreshed["id"]
                        if self.track_registry is not None:
                            record = self.track_registry.records.get(ringtone_name)
                            if record is not None:
                                record.nvr_ringtone_id = ringtone_id
                                record.nvr_ringtone_name = refreshed.get("name", ringtone_name)
                                self.track_registry.put(record)
                        return await play_ringtone()

                queued = await target.queue.submit(PlaybackRequest(
                    factory=play, priority=command.priority,
                    dedupe_key=command.dedupe_key,
                    dedupe_window_ms=command.dedupe_window_ms,
                ))
                if isinstance(queued, QueueResult):
                    return {
                        "target": target.desc.name,
                        "chime_id": chime_id,
                        "disposition": queued.disposition.value,
                        "queue_wait_ms": queued.queue_wait_ms,
                        "dispatch_at_ns": dispatch_at_ns,
                        **queued.result,
                    }
                # Lightweight queue doubles may return the playback dict directly.
                return {"target": target.desc.name, "chime_id": chime_id,
                        "disposition": "played", "dispatch_at_ns": dispatch_at_ns,
                        **dict(queued)}

            jobs = await self._timed(timing, "play_request", asyncio.gather(
                *(submit(target) for target in targets)))
            dispatch_times = [j["dispatch_at_ns"] for j in jobs
                              if j.get("dispatch_at_ns") is not None]
            group_skew_ms = ((max(dispatch_times) - min(dispatch_times)) / 1_000_000
                             if dispatch_times else 0.0)
            waits = [j["queue_wait_ms"] for j in jobs if j.get("queue_wait_ms") is not None]
            if waits:
                timing.set("queue_wait", max(waits))
            dispositions = [j["disposition"] for j in jobs]
            if all(value == QueueDisposition.PLAYED.value for value in dispositions):
                disposition = "played"
            elif any(value == QueueDisposition.FAILED.value for value in dispositions):
                disposition = "failed"
            elif all(value == QueueDisposition.DEDUPED.value for value in dispositions):
                disposition = "deduped"
            elif all(value == QueueDisposition.DROPPED.value for value in dispositions):
                disposition = "dropped"
            else:
                disposition = "partial"
            result_payload = {"targets": len(targets), "jobs": jobs}
            if self.debug_timings:
                result_payload["group_skew_ms"] = group_skew_ms
            return self._finish(command, disposition, result_payload,
                                timing, total_started)
        except Exception:
            self._record_finish("failed", timing, total_started)
            raise

    async def _resolve_announcement(self, command: AnnouncementCommand,
                                    timing: AnnouncementTiming, targets: list) -> str:
        key = self.slug(command.text or "")
        tone = self.index.get(key)
        if tone is None and not self.index.loaded and hasattr(self.protect, "find_ringtone_by_name"):
            tone = await self.protect.find_ringtone_by_name(key)
            if tone:
                self.index.put(tone)
        if tone:
            self.metrics.inc("cache_hits")
            if self.track_registry is not None:
                self.track_registry.get(key)
            return tone["id"]
        lock = self._creation_locks.setdefault(key, asyncio.Lock())
        self._creation_lock_users[key] = self._creation_lock_users.get(key, 0) + 1
        try:
            async with lock:
                tone = self.index.get(key)
                if tone:
                    self.metrics.inc("cache_hits")
                    if self.track_registry is not None:
                        self.track_registry.get(key)
                    return tone["id"]
                self.metrics.inc("cache_misses")
                mp3 = await self._timed(timing, "tts", self.synthesize(command.text or ""))
                tts_ms = getattr(mp3, "tts_ms", None)
                if tts_ms is not None:
                    timing.set("tts", tts_ms)
                pcm_ms = getattr(mp3, "pcm_ms", None)
                if pcm_ms is not None:
                    timing.set("pcm_process", pcm_ms)
                encode_ms = getattr(mp3, "encode_ms", None)
                if encode_ms is not None:
                    timing.set("encode", encode_ms)
                direct_clients = [target.direct_client for target in targets
                                  if getattr(target, "direct_client", None) is not None]
                async with self._upload_lock:
                    if (self.track_reconciler is not None
                            and hasattr(self.track_reconciler, "ensure_capacity")):
                        snapshot = await self.ringtone_backend.list_ringtones()
                        evicted = await self.track_reconciler.ensure_capacity(snapshot, needed=1)
                        if any(item.get("nvr_delete") == "deleted" for item in evicted):
                            await self.index.force_refresh()
                    try:
                        await self._timed(timing, "upload", self.chime.upload_ringtone(
                            key, mp3, direct_clients=direct_clients))
                    except RingtoneCapacityError:
                        if (self.track_reconciler is None
                                or not hasattr(self.track_reconciler, "ensure_capacity")):
                            raise
                        snapshot = await self.ringtone_backend.list_ringtones()
                        if len(snapshot) < self.track_reconciler.max_total:
                            raise
                        self.metrics.inc("ringtone_capacity_retries")
                        evicted = await self.track_reconciler.ensure_capacity(snapshot, needed=1)
                        if not any(item.get("nvr_delete") == "deleted" for item in evicted):
                            raise
                        await self.index.force_refresh()
                        await self._timed(timing, "upload", self.chime.upload_ringtone(
                            key, mp3, direct_clients=direct_clients))
                    tone = await self.index.resolve_or_refresh(key)
                    if not tone:
                        raise RuntimeError("upload succeeded but tone not found on NVR")
                    self.index.put(tone)
                    if self.track_registry is not None:
                        self.track_registry.put(TrackRecord(
                            logical_key=key, kind="dynamic_tts", owner="unifi_announcer",
                            nvr_ringtone_id=tone["id"],
                            nvr_ringtone_name=tone.get("name", key),
                        ))
                    if self.track_reconciler is not None:
                        evicted = await self.track_reconciler.evict_to_limit()
                        if any(item.get("nvr_delete") == "deleted" for item in evicted):
                            await self.index.force_refresh()
                    return tone["id"]
        finally:
            users = self._creation_lock_users[key] - 1
            if users:
                self._creation_lock_users[key] = users
            else:
                self._creation_lock_users.pop(key, None)
                if self._creation_locks.get(key) is lock:
                    self._creation_locks.pop(key, None)

    def _finish(self, command: AnnouncementCommand, disposition: str,
                result: dict[str, Any], timing: AnnouncementTiming,
                total_started: int) -> DispatchResult:
        self._record_finish(disposition, timing, total_started)
        return DispatchResult(command.action, disposition, result,
                              timing.as_dict() if self.debug_timings else None)

    def _record_finish(self, disposition: str, timing: AnnouncementTiming,
                       total_started: int) -> None:
        timing.set("announce_total", (perf_counter_ns() - total_started) / 1_000_000)
        for name, value in timing.as_dict().items():
            self.metrics.observe(name, value)
        self.metrics.inc(f"dispatch_{disposition}")

    async def _timed(self, timing: AnnouncementTiming, stage: str, awaitable):
        timing.start(stage)
        try:
            return await awaitable
        finally:
            timing.stop(stage)

    @staticmethod
    def _validate(command: AnnouncementCommand) -> None:
        if command.action == "announce" and not (command.text or "").strip():
            raise ValueError("announce requires text")
        if command.action == "play_preset" and not (command.preset or "").strip():
            raise ValueError("play_preset requires preset")
        if command.volume is not None and not 0 <= command.volume <= 100:
            raise ValueError("volume must be 0..100")
        if command.repeat_times is not None and not 1 <= command.repeat_times <= 6:
            raise ValueError("repeat_times must be 1..6")
        if (not isinstance(command.priority, int) or isinstance(command.priority, bool)
                or not 0 <= command.priority <= 100):
            raise ValueError("priority must be an integer from 0..100")
