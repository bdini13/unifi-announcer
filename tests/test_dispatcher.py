import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.dispatcher import (
    AnnouncementCommand, AnnouncementDispatcher, DispatchResult, StaleRingtoneError,
)


class _Metrics:
    def __init__(self):
        self.observed = []
        self.counters = []

    def observe(self, name, value):
        self.observed.append((name, value))

    def inc(self, name, amount=1):
        self.counters.append((name, amount))


def _dispatcher(*, protect, targets):
    return AnnouncementDispatcher(
        protect=protect, chime=SimpleNamespace(), ringtone_index=SimpleNamespace(),
        synthesize=AsyncMock(), slug=lambda text: text,
        resolve_preset=AsyncMock(return_value="tone"),
        resolve_targets=lambda target: targets,
        profile=lambda values: values, quiet=lambda: False,
        metrics=_Metrics(), volume_default=50, repeat_default=1,
        debug_timings=True,
    )


@pytest.mark.asyncio
async def test_dispatch_fans_out_concurrently_with_each_chime_id():
    release = asyncio.Event()
    entered = []

    async def play(ringtone_id, volume, repeat_times, *, chime_id):
        entered.append(chime_id)
        if len(entered) == 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=0.2)
        return {"chime_id": chime_id}

    class Queue:
        async def submit(self, request):
            return await request.run()

    targets = [
        SimpleNamespace(desc=SimpleNamespace(name="one", chime_id="id-one"), queue=Queue()),
        SimpleNamespace(desc=SimpleNamespace(name="two", chime_id="id-two"), queue=Queue()),
    ]
    result = await _dispatcher(protect=SimpleNamespace(play=play), targets=targets).dispatch(
        AnnouncementCommand(action="play_preset", preset="tone")
    )

    assert entered == ["id-one", "id-two"]
    assert [job["chime_id"] for job in result.result["jobs"]] == ["id-one", "id-two"]


@pytest.mark.asyncio
async def test_three_chime_fanout_reports_correct_ids_and_group_skew():
    release = asyncio.Event()
    entered = []

    async def play(ringtone_id, volume, repeat_times, *, chime_id):
        entered.append(chime_id)
        if len(entered) == 3:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=0.2)
        return {}

    class Queue:
        async def submit(self, request):
            return await request.run()

    targets = [SimpleNamespace(
        desc=SimpleNamespace(name=f"chime-{n}", chime_id=f"id-{n}"), queue=Queue()
    ) for n in ("one", "two", "three")]

    result = await _dispatcher(protect=SimpleNamespace(play=play), targets=targets).dispatch(
        AnnouncementCommand(action="play_preset", preset="tone")
    )

    assert entered == ["id-one", "id-two", "id-three"]
    assert [job["chime_id"] for job in result.result["jobs"]] == entered
    assert result.result["group_skew_ms"] >= 0
    assert all("dispatch_at_ns" in job for job in result.result["jobs"])


@pytest.mark.asyncio
@pytest.mark.parametrize("priority", [-1, 101, 1.5, "10", True])
async def test_dispatch_rejects_invalid_priority_from_every_source(priority):
    protect = SimpleNamespace(play=AsyncMock())
    dispatcher = _dispatcher(protect=protect, targets=[])

    with pytest.raises(ValueError, match="priority must be an integer from 0..100"):
        await dispatcher.dispatch(AnnouncementCommand(
            action="play_preset", preset="tone", priority=priority, source="mqtt"))

    protect.play.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_named_target_fails_without_playback():
    protect = SimpleNamespace(play=AsyncMock())
    dispatcher = _dispatcher(protect=protect, targets=[])

    with pytest.raises(ValueError, match="unknown or empty target: missing"):
        await dispatcher.dispatch(AnnouncementCommand(
            action="play_preset", preset="tone", target="missing"))

    protect.play.assert_not_awaited()


@pytest.mark.asyncio
async def test_timed_records_elapsed_when_awaitable_raises():
    from app.observability import AnnouncementTiming

    dispatcher = _dispatcher(protect=SimpleNamespace(), targets=[])
    timing = AnnouncementTiming()

    async def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await dispatcher._timed(timing, "encode", fail())

    assert timing.as_dict()["encode_ms"] >= 0


@pytest.mark.asyncio
async def test_queue_disposition_and_wait_are_returned_and_measured():
    from app.playback.arbitration import ArbitrationQueue

    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=ArbitrationQueue("one"),
    )
    dispatcher = _dispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={"ok": True})),
        targets=[target],
    )
    result = await dispatcher.dispatch(AnnouncementCommand(
        action="play_preset", preset="tone", dedupe_key="fixture"))

    assert result.result["jobs"][0]["disposition"] == "played"
    assert result.result["jobs"][0]["queue_wait_ms"] >= 0
    assert result.timings["queue_wait_ms"] >= 0


@pytest.mark.asyncio
async def test_play_default_preserves_empty_device_defaults_but_pairs_partial_override():
    from app.playback.policy import PlaybackPolicy

    play_default = AsyncMock(return_value={})
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play_default=play_default), chime=SimpleNamespace(),
        ringtone_index=SimpleNamespace(), synthesize=AsyncMock(), slug=lambda text: text,
        resolve_preset=AsyncMock(), resolve_targets=lambda selected: [target],
        profile=lambda values: values, quiet=lambda: False, metrics=_Metrics(),
        volume_default=50, repeat_default=1,
        playback_policy=PlaybackPolicy(profiles={}, volume_default=50, repeat_default=1),
    )

    await dispatcher.dispatch(AnnouncementCommand(action="play_default"))
    await dispatcher.dispatch(AnnouncementCommand(action="play_default", volume=30))

    assert play_default.await_args_list[0].args == (None, None)
    assert play_default.await_args_list[1].args == (30, 1)


@pytest.mark.asyncio
async def test_stale_ringtone_id_refreshes_and_retries_play_once():
    tones = {"fixture": {"id": "old-id", "name": "fixture"}}

    class Index:
        loaded = True
        def get(self, name): return tones.get(name)
        def invalidate(self, name): tones.pop(name, None)
        async def refresh(self): tones["fixture"] = {"id": "new-id", "name": "fixture"}
        force_refresh = refresh

    play = AsyncMock(side_effect=[StaleRingtoneError("missing ringtone"), {"ok": True}])
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=play), chime=SimpleNamespace(), ringtone_index=Index(),
        synthesize=AsyncMock(), slug=lambda text: text,
        resolve_preset=AsyncMock(return_value="old-id"),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
    )

    result = await dispatcher.dispatch(AnnouncementCommand(
        action="play_preset", preset="fixture"))

    assert result.disposition == "played"
    assert [call.args[0] for call in play.await_args_list] == ["old-id", "new-id"]


@pytest.mark.asyncio
async def test_queue_stays_bounded_and_better_priority_displaces_worst():
    from app.playback.arbitration import (
        ArbitrationQueue, PlaybackRequest, QueueDisposition,
    )

    release = asyncio.Event()

    async def blocked():
        await release.wait()
        return {"ok": True}

    queue = ArbitrationQueue("fixture", max_depth=2)
    active = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=50)))
    await asyncio.sleep(0)
    low = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=100)))
    await asyncio.sleep(0)
    urgent = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=10)))
    await asyncio.sleep(0)
    assert queue.depth == 2
    assert (await low).disposition is QueueDisposition.DROPPED
    release.set()
    assert (await active).disposition is QueueDisposition.PLAYED
    assert (await urgent).disposition is QueueDisposition.PLAYED


@pytest.mark.asyncio
async def test_emergency_is_never_dropped_when_queue_is_full():
    from app.playback.arbitration import ArbitrationQueue, PlaybackRequest, QueueDisposition

    release = asyncio.Event()
    queue = ArbitrationQueue("fixture", max_depth=1)

    async def blocked():
        await release.wait()
        return {}

    active = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=50)))
    await asyncio.sleep(0)
    emergency = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=0)))
    await asyncio.sleep(0)
    assert not emergency.done()
    release.set()
    assert (await active).disposition is QueueDisposition.PLAYED
    assert (await emergency).disposition is QueueDisposition.PLAYED


@pytest.mark.asyncio
async def test_doorbell_displaces_info_but_normal_drops_at_capacity():
    from app.playback.arbitration import ArbitrationQueue, PlaybackRequest, QueueDisposition

    release = asyncio.Event()
    queue = ArbitrationQueue("fixture", max_depth=2)

    async def blocked():
        await release.wait()
        return {}

    active = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=50)))
    await asyncio.sleep(0)
    info = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=100)))
    await asyncio.sleep(0)
    normal = await queue.submit(PlaybackRequest(blocked, priority=50))
    assert normal.disposition is QueueDisposition.DROPPED
    doorbell = asyncio.create_task(queue.submit(PlaybackRequest(blocked, priority=10)))
    await asyncio.sleep(0)
    assert (await info).disposition is QueueDisposition.DROPPED
    release.set()
    await active
    assert (await doorbell).disposition is QueueDisposition.PLAYED


@pytest.mark.asyncio
async def test_expired_dedupe_entries_are_pruned():
    from app.playback.arbitration import ArbitrationQueue, PlaybackRequest

    queue = ArbitrationQueue("fixture")
    await queue.submit(PlaybackRequest(AsyncMock(return_value={}), dedupe_key="old", dedupe_window_ms=0))
    await queue.submit(PlaybackRequest(AsyncMock(return_value={}), dedupe_key="new"))

    assert "old" not in queue._recent


@pytest.mark.asyncio
async def test_announcement_upload_routes_through_each_target_direct_client():
    direct_one = SimpleNamespace(upload_ringtone=AsyncMock())
    direct_two = SimpleNamespace(upload_ringtone=AsyncMock())
    unconfigured = SimpleNamespace(upload_ringtone=AsyncMock())
    targets = [
        SimpleNamespace(
            desc=SimpleNamespace(name="one", chime_id="id-one", direct_ip="192.0.2.1"),
            direct_client=direct_one,
            queue=SimpleNamespace(submit=lambda request: request.run()),
        ),
        SimpleNamespace(
            desc=SimpleNamespace(name="two", chime_id="id-two", direct_ip="192.0.2.2"),
            direct_client=direct_two,
            queue=SimpleNamespace(submit=lambda request: request.run()),
        ),
        SimpleNamespace(
            desc=SimpleNamespace(name="three", chime_id="id-three", direct_ip=""),
            direct_client=unconfigured,
            queue=SimpleNamespace(submit=lambda request: request.run()),
        ),
    ]
    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone", "name": "key"}),
        put=lambda tone: None,
    )
    chime = SimpleNamespace(upload_ringtone=AsyncMock(return_value={"id": "tone"}))
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={})), chime=chime,
        ringtone_index=index, synthesize=AsyncMock(return_value=b"mp3"),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: targets, profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50,
        repeat_default=1,
    )

    await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    chime.upload_ringtone.assert_awaited_once_with(
        "key", b"mp3", direct_clients=[direct_one, direct_two, unconfigured])


@pytest.mark.asyncio
async def test_concurrent_cold_identical_announcements_create_ringtone_once(tmp_path):
    tone = None

    class Index:
        loaded = True
        def get(self, key): return tone
        def put(self, value):
            nonlocal tone
            tone = value
        async def resolve_or_refresh(self, key): return tone
        async def refresh(self): return None

    async def upload(name, mp3, **kwargs):
        nonlocal tone
        await asyncio.sleep(0)
        tone = {"id": "tone-1", "name": name}
        return tone

    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    async def render(text):
        await asyncio.sleep(0)
        return b"mp3"

    synthesize = AsyncMock(side_effect=render)
    chime = SimpleNamespace(upload_ringtone=AsyncMock(side_effect=upload))
    play = AsyncMock(return_value={})
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=play), chime=chime, ringtone_index=Index(),
        synthesize=synthesize, slug=lambda text: "same-key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
    )

    await asyncio.gather(*(
        dispatcher.dispatch(AnnouncementCommand(action="announce", text="same"))
        for _ in range(2)
    ))

    synthesize.assert_awaited_once()
    chime.upload_ringtone.assert_awaited_once()
    assert play.await_count == 2
    assert dispatcher._creation_locks == {}


@pytest.mark.asyncio
async def test_new_dynamic_announcement_is_registered_and_gc_runs_once(tmp_path):
    from app.tracks import TrackRegistry

    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone-1", "name": "key"}),
        put=lambda tone: None,
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    registry = TrackRegistry(tmp_path / "tracks.json", max_dynamic=3)
    reconciler = SimpleNamespace(evict_to_limit=AsyncMock(return_value=[]))
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={})),
        chime=SimpleNamespace(upload_ringtone=AsyncMock(return_value={})),
        ringtone_index=index, synthesize=AsyncMock(return_value=b"mp3"),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
        track_registry=registry, track_reconciler=reconciler,
    )

    await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    record = registry.records["key"]
    assert record.kind == "dynamic_tts"
    assert record.nvr_ringtone_id == "tone-1"
    reconciler.evict_to_limit.assert_awaited_once()


@pytest.mark.asyncio
async def test_announcement_reserves_total_capacity_before_upload(tmp_path):
    from app.tracks import TrackRegistry

    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone-1", "name": "key"}),
        put=lambda tone: None,
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    protect = SimpleNamespace(
        play=AsyncMock(return_value={}),
        list_ringtones=AsyncMock(return_value=[{"id": "existing"}]),
    )
    reconciler = SimpleNamespace(
        ensure_capacity=AsyncMock(return_value=[]),
        evict_to_limit=AsyncMock(return_value=[]),
    )
    dispatcher = AnnouncementDispatcher(
        protect=protect, chime=SimpleNamespace(upload_ringtone=AsyncMock(return_value={})),
        ringtone_index=index, synthesize=AsyncMock(return_value=b"mp3"),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
        track_registry=TrackRegistry(tmp_path / "tracks.json"),
        track_reconciler=reconciler,
    )

    await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    reconciler.ensure_capacity.assert_awaited_once_with([{"id": "existing"}], needed=1)


@pytest.mark.asyncio
async def test_capacity_upload_error_evicts_one_and_retries_once(tmp_path):
    from app.tracks import RingtoneCapacityError, TrackRegistry

    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone-1", "name": "key"}),
        put=lambda tone: None, force_refresh=AsyncMock(),
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    snapshot = [{"id": "existing"}]
    protect = SimpleNamespace(
        play=AsyncMock(return_value={}), list_ringtones=AsyncMock(return_value=snapshot),
    )
    upload = AsyncMock(side_effect=[RingtoneCapacityError("full"), {}])
    reconciler = SimpleNamespace(
        max_total=1,
        ensure_capacity=AsyncMock(side_effect=[[], [{"nvr_delete": "deleted"}]]),
        evict_to_limit=AsyncMock(return_value=[]),
    )
    metrics = _Metrics()
    dispatcher = AnnouncementDispatcher(
        protect=protect, chime=SimpleNamespace(upload_ringtone=upload),
        ringtone_index=index, synthesize=AsyncMock(return_value=b"mp3"),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=metrics, volume_default=50, repeat_default=1,
        track_registry=TrackRegistry(tmp_path / "tracks.json"),
        track_reconciler=reconciler,
    )

    result = await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    assert result.disposition == "played"
    assert upload.await_count == 2
    assert reconciler.ensure_capacity.await_args_list[-1].kwargs == {"needed": 1}
    index.force_refresh.assert_awaited_once()
    assert ("ringtone_capacity_retries", 1) in metrics.counters


@pytest.mark.asyncio
async def test_empty_400_does_not_evict_or_retry_below_verified_capacity(tmp_path):
    from app.tracks import RingtoneCapacityError, TrackRegistry

    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    upload = AsyncMock(side_effect=RingtoneCapacityError("invalid media"))
    reconciler = SimpleNamespace(
        max_total=6, ensure_capacity=AsyncMock(return_value=[]),
        evict_to_limit=AsyncMock(return_value=[]),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock()),
        ringtone_backend=SimpleNamespace(list_ringtones=AsyncMock(return_value=[{"id": "one"}])),
        chime=SimpleNamespace(upload_ringtone=upload),
        ringtone_index=SimpleNamespace(get=lambda key: None, loaded=True),
        synthesize=AsyncMock(return_value=b"mp3"), slug=lambda text: "key",
        resolve_preset=AsyncMock(), resolve_targets=lambda selected: [target],
        profile=lambda values: values, quiet=lambda: False, metrics=_Metrics(),
        volume_default=50, repeat_default=1,
        track_registry=TrackRegistry(tmp_path / "tracks.json"),
        track_reconciler=reconciler,
    )

    with pytest.raises(RingtoneCapacityError, match="invalid media"):
        await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    assert upload.await_count == 1
    assert reconciler.ensure_capacity.await_count == 1


@pytest.mark.asyncio
async def test_capacity_preflight_failure_aborts_before_upload(tmp_path):
    from app.tracks import RingtoneCapacityError, TrackRegistry

    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    upload = AsyncMock()
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock()),
        ringtone_backend=SimpleNamespace(
            list_ringtones=AsyncMock(return_value=[{"id": "full"}])
        ),
        chime=SimpleNamespace(upload_ringtone=upload),
        ringtone_index=SimpleNamespace(get=lambda key: None, loaded=True),
        synthesize=AsyncMock(return_value=b"mp3"), slug=lambda text: "key",
        resolve_preset=AsyncMock(), resolve_targets=lambda selected: [target],
        profile=lambda values: values, quiet=lambda: False, metrics=_Metrics(),
        volume_default=50, repeat_default=1,
        track_registry=TrackRegistry(tmp_path / "tracks.json"),
        track_reconciler=SimpleNamespace(
            ensure_capacity=AsyncMock(side_effect=RingtoneCapacityError("full")),
            evict_to_limit=AsyncMock(return_value=[]),
        ),
    )

    with pytest.raises(RingtoneCapacityError, match="full"):
        await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamic_cache_hit_updates_registry_lru(tmp_path):
    from app.tracks import TrackRecord, TrackRegistry

    registry = TrackRegistry(tmp_path / "tracks.json")
    record = TrackRecord("key", nvr_ringtone_id="tone-1", last_used_at=1.0)
    registry.put(record)
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={})), chime=SimpleNamespace(),
        ringtone_index=SimpleNamespace(
            get=lambda key: {"id": "tone-1", "name": "key"}, loaded=True),
        synthesize=AsyncMock(), slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
        track_registry=registry,
    )

    await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    assert registry.records["key"].last_used_at > 1.0


@pytest.mark.asyncio
async def test_dynamic_gc_refreshes_ringtone_index_after_eviction(tmp_path):
    from app.tracks import TrackRegistry

    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone-1", "name": "key"}),
        put=lambda tone: None, refresh=AsyncMock(), force_refresh=AsyncMock(),
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={})),
        chime=SimpleNamespace(upload_ringtone=AsyncMock(return_value={})),
        ringtone_index=index, synthesize=AsyncMock(return_value=b"mp3"),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
        track_registry=TrackRegistry(tmp_path / "tracks.json"),
        track_reconciler=SimpleNamespace(evict_to_limit=AsyncMock(
            return_value=[{"logical_key": "old", "nvr_delete": "deleted"}])),
    )

    await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    index.force_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_dynamic_gc_does_not_refresh_when_nvr_was_not_deleted(tmp_path):
    from app.tracks import TrackRegistry

    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone-1", "name": "key"}),
        put=lambda tone: None, refresh=AsyncMock(),
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={})),
        chime=SimpleNamespace(upload_ringtone=AsyncMock(return_value={})),
        ringtone_index=index, synthesize=AsyncMock(return_value=b"mp3"),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
        track_registry=TrackRegistry(tmp_path / "tracks.json"),
        track_reconciler=SimpleNamespace(evict_to_limit=AsyncMock(
            return_value=[{"logical_key": "old", "nvr_delete": "failed"}])),
    )

    await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))

    index.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_dynamic_id_updates_registry_to_replacement(tmp_path):
    from app.tracks import TrackRecord, TrackRegistry

    tones = {"fixture": {"id": "old-id", "name": "fixture"}}

    class Index:
        loaded = True
        def get(self, name): return tones.get(name)
        def invalidate(self, name): tones.pop(name, None)
        async def refresh(self): tones["fixture"] = {"id": "new-id", "name": "fixture"}
        force_refresh = refresh

    registry = TrackRegistry(tmp_path / "tracks.json")
    registry.put(TrackRecord("fixture", nvr_ringtone_id="old-id",
                             nvr_ringtone_name="fixture"))
    play = AsyncMock(side_effect=[StaleRingtoneError("missing ringtone"), {}])
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=play), chime=SimpleNamespace(), ringtone_index=Index(),
        synthesize=AsyncMock(), slug=lambda text: text,
        resolve_preset=AsyncMock(return_value="old-id"),
        resolve_targets=lambda selected: [target], profile=lambda values: values,
        quiet=lambda: False, metrics=_Metrics(), volume_default=50, repeat_default=1,
        track_registry=registry,
    )

    await dispatcher.dispatch(AnnouncementCommand(action="play_preset", preset="fixture"))

    assert registry.records["fixture"].nvr_ringtone_id == "new-id"


@pytest.mark.asyncio
async def test_encoded_audio_records_encode_stage():
    from app.audio.tts import EncodedAudio

    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone", "name": "key"}),
        put=lambda tone: None,
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={})),
        chime=SimpleNamespace(upload_ringtone=AsyncMock(return_value={})),
        ringtone_index=index,
        synthesize=AsyncMock(return_value=EncodedAudio(b"mp3", encode_ms=4.5)),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda target: [target_obj],
        profile=lambda values: values, quiet=lambda: False, metrics=_Metrics(),
        volume_default=50, repeat_default=1, debug_timings=True,
    )
    target_obj = target
    result = await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))
    assert result.timings["encode_ms"] == 4.5


@pytest.mark.asyncio
async def test_encoded_audio_separates_tts_and_encode_stages():
    from app.audio.tts import EncodedAudio

    index = SimpleNamespace(
        get=lambda key: None, loaded=True,
        resolve_or_refresh=AsyncMock(return_value={"id": "tone", "name": "key"}),
        put=lambda tone: None,
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="one", chime_id="id-one"),
        queue=SimpleNamespace(submit=lambda request: request.run()),
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=AsyncMock(return_value={})),
        chime=SimpleNamespace(upload_ringtone=AsyncMock(return_value={})),
        ringtone_index=index,
        synthesize=AsyncMock(return_value=EncodedAudio(
            b"mp3", tts_ms=3.25, encode_ms=1.75)),
        slug=lambda text: "key", resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target],
        profile=lambda values: values, quiet=lambda: False, metrics=_Metrics(),
        volume_default=50, repeat_default=1, debug_timings=True,
    )
    result = await dispatcher.dispatch(AnnouncementCommand(action="announce", text="hello"))
    assert result.timings["tts_ms"] == 3.25
    assert result.timings["encode_ms"] == 1.75


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "json", "action"),
    [
        ("/announce", {"text": "fixture"}, "announce"),
        ("/buzzer", None, "buzzer"),
        ("/play-default", None, "play_default"),
        ("/presets/fixture/play", None, "play_preset"),
    ],
)
async def test_http_command_entrypoints_use_dispatcher(main_module, monkeypatch, path, json, action):
    dispatch = AsyncMock(return_value=DispatchResult(action=action, disposition="played", result={"ok": True}))
    monkeypatch.setattr(main_module.dispatcher, "dispatch", dispatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main_module.app), base_url="http://test") as client:
        response = await client.post(path, json=json)
    assert response.status_code == 200
    command = dispatch.await_args.args[0]
    assert command.action == action
    assert command.source == "api"


@pytest.mark.asyncio
async def test_replacing_services_container_changes_route_dispatch(main_module):
    dispatch = AsyncMock(return_value=DispatchResult(
        action="buzzer", disposition="played", result={"injected": True}))
    main_module.app.state.services = SimpleNamespace(dispatcher=SimpleNamespace(dispatch=dispatch))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.post("/buzzer")

    assert response.status_code == 200
    assert response.json()["injected"] is True
    dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_quiet_hour_suppression_maps_to_http_202(main_module):
    dispatch = AsyncMock(return_value=DispatchResult(
        action="announce", disposition="suppressed",
        result={"detail": "suppressed during quiet hours"}))
    main_module.app.state.services = SimpleNamespace(dispatcher=SimpleNamespace(dispatch=dispatch))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.post("/announce", json={"text": "fixture"})

    assert response.status_code == 202
    assert response.json()["disposition"] == "suppressed"


@pytest.mark.asyncio
async def test_failed_playback_disposition_maps_to_http_502(main_module):
    dispatch = AsyncMock(return_value=DispatchResult(
        action="buzzer", disposition="failed",
        result={"jobs": [{"disposition": "failed", "error": "Protect unavailable"}]}))
    main_module.app.state.services = SimpleNamespace(
        dispatcher=SimpleNamespace(dispatch=dispatch))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.post("/buzzer")

    assert response.status_code == 502
    assert response.json()["disposition"] == "failed"
    assert response.json()["jobs"][0]["error"] == "Protect unavailable"


@pytest.mark.asyncio
async def test_stale_classifier_does_not_retry_when_chime_is_missing(main_module, respx_mock):
    main_module.protect._logged_in = True
    main_module.protect._csrf = "fixture"
    respx_mock.post(
        "https://unifi.invalid/proxy/protect/api/chimes/chime-fixture/play-speaker"
    ).mock(return_value=httpx.Response(404, text="Ringtone playback target chime not found"))

    with pytest.raises(RuntimeError, match="play-speaker failed"):
        await main_module.protect.play("tone", 50, 1, chime_id="chime-fixture")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "json"),
    [
        ("/announce", {"text": "fixture", "target": "downstairs"}),
        ("/buzzer?target=downstairs", None),
        ("/play-default?target=downstairs", None),
        ("/presets/fixture/play?target=downstairs", None),
    ],
)
async def test_rest_play_routes_accept_target(main_module, path, json):
    dispatch = AsyncMock(return_value=DispatchResult("fixture", "played"))
    main_module.app.state.services = SimpleNamespace(dispatcher=SimpleNamespace(dispatch=dispatch))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=json)

    assert response.status_code == 200
    assert dispatch.await_args.args[0].target == "downstairs"


@pytest.mark.asyncio
async def test_missing_default_chime_id_returns_config_error_without_playback(main_module, monkeypatch):
    play = AsyncMock()
    monkeypatch.setattr(main_module, "chime_runtimes", {})
    monkeypatch.setattr(main_module.protect, "play_buzzer", play)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.post("/buzzer")

    assert response.status_code == 503
    assert response.json()["detail"] == "no chime targets are configured"
    play.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_rules_use_dispatcher(main_module, monkeypatch):
    engine = main_module.RulesEngine()
    engine.rules = [{"name": "fixture", "when": {"event": "doorbell_ring", "model": "camera"}, "then": {"preset": "tone"}, "cooldown_ms": 0}]
    dispatch = AsyncMock(return_value=DispatchResult("play_preset", "played"))
    monkeypatch.setattr(main_module.dispatcher, "dispatch", dispatch)
    await engine.evaluate({"action": "add", "model": "camera", "is_event": True})
    command = dispatch.await_args.args[0]
    assert command.action == "play_preset"
    assert command.source == "rule"
    assert command.dedupe_window_ms == 0


@pytest.mark.asyncio
async def test_mqtt_commands_use_dispatcher(main_module, monkeypatch):
    dispatch = AsyncMock(return_value=DispatchResult("buzzer", "played"))
    monkeypatch.setattr(main_module.dispatcher, "dispatch", dispatch)
    message = SimpleNamespace(topic="unifi-announcer/chime/default/play", payload=b'{"buzzer": true}')
    await main_module.mqtt_bridge._on_message(message)
    command = dispatch.await_args.args[0]
    assert command.action == "buzzer"
    assert command.source == "mqtt"


def test_command_contract_contains_exact_supported_actions_and_fields():
    command = AnnouncementCommand(action="announce", text="x")
    assert set(command.__dataclass_fields__) == {
        "action", "text", "preset", "volume", "repeat_times", "profile",
        "target", "priority", "dedupe_key", "dedupe_window_ms", "source",
    }
