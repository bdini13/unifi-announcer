from unittest.mock import AsyncMock

import pytest

from app.playback.dynamic_slots import DeviceSlotBinding, DynamicSlotUnavailable
from app.playback.production_slots import DynamicTtsSlotManager


class Metrics:
    def __init__(self):
        self.counters = {}

    def inc(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount


def manager(tmp_path, get_chime, metrics=None):
    async def empty_list():
        return []

    async def noop(*_args, **_kwargs):
        return None

    return DynamicTtsSlotManager(
        data_dir=tmp_path,
        list_ringtones=empty_list,
        upload_ringtone=noop,
        delete_ringtone=noop,
        resolve_ringtone=noop,
        refresh_index=noop,
        get_chime=get_chime,
        play_ringtone=noop,
        metrics=metrics,
        device_sync_timeout_s=0.02,
        device_settle_delay_s=0,
        poll_interval_s=0.002,
    )


def binding():
    return DeviceSlotBinding(
        chime_id="chime-1",
        device_slot=7,
        filename="owned-slot.mp3",
        provisioning_md5="provisioned",
        provisioning_size=111,
        current_md5="old",
        current_size=222,
    )


@pytest.mark.asyncio
async def test_production_sync_accepts_stale_inventory_for_exact_owned_slot(tmp_path):
    metrics = Metrics()
    stale = {
        "speakerTrackList": [
            {"track_no": 7, "fileName": "owned-slot.mp3", "md5": "old", "size": 222}
        ]
    }
    get_chime = AsyncMock(return_value=stale)
    mgr = manager(tmp_path, get_chime, metrics)

    await mgr._wait_for_device_sync(
        binding(), expected_md5="new", expected_size=333
    )

    assert get_chime.await_count >= 2
    assert metrics.counters.get("tts_slot_sync_stale_inventory_accepts") == 1
    assert metrics.counters.get("tts_slot_sync_timeouts", 0) == 0


@pytest.mark.asyncio
async def test_production_sync_prefers_fresh_fingerprint_when_protect_updates(tmp_path):
    metrics = Metrics()
    responses = [
        {"speakerTrackList": [
            {"track_no": 7, "fileName": "owned-slot.mp3", "md5": "old", "size": 222}
        ]},
        {"speakerTrackList": [
            {"track_no": 7, "fileName": "owned-slot.mp3", "md5": "new", "size": 333}
        ]},
    ]
    get_chime = AsyncMock(side_effect=responses)
    mgr = manager(tmp_path, get_chime, metrics)

    await mgr._wait_for_device_sync(
        binding(), expected_md5="new", expected_size=333
    )

    assert metrics.counters.get("tts_slot_sync_successes") == 1
    assert metrics.counters.get("tts_slot_sync_stale_inventory_accepts", 0) == 0


@pytest.mark.asyncio
async def test_production_sync_rejects_positive_filename_drift_immediately(tmp_path):
    metrics = Metrics()
    get_chime = AsyncMock(return_value={
        "speakerTrackList": [
            {"track_no": 7, "fileName": "foreign.mp3", "md5": "old", "size": 222}
        ]
    })
    mgr = manager(tmp_path, get_chime, metrics)

    with pytest.raises(DynamicSlotUnavailable, match="ownership proof"):
        await mgr._wait_for_device_sync(
            binding(), expected_md5="new", expected_size=333
        )

    assert get_chime.await_count == 1
    assert metrics.counters.get("tts_slot_sync_ownership_drift") == 1


@pytest.mark.asyncio
async def test_production_sync_still_fails_when_owned_slot_metadata_disappears(tmp_path):
    metrics = Metrics()
    get_chime = AsyncMock(return_value={"speakerTrackList": []})
    mgr = manager(tmp_path, get_chime, metrics)

    with pytest.raises(DynamicSlotUnavailable, match="did not synchronize"):
        await mgr._wait_for_device_sync(
            binding(), expected_md5="new", expected_size=333
        )

    assert metrics.counters.get("tts_slot_sync_timeouts") == 1
    assert metrics.counters.get("tts_slot_sync_stale_inventory_accepts", 0) == 0
