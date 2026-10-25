from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.playback.dynamic_slots import DynamicSlotUnavailable, DynamicTtsSlotManager as BaseManager
from app.playback.fixed_slots import DynamicTtsSlotManager as FixedManager


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_class", [BaseManager, FixedManager])
@pytest.mark.parametrize("numbering", ["sparse", "missing", "duplicate", "invalid"])
async def test_legacy_cleanup_uses_only_unambiguous_physical_numbers(
    tmp_path, manager_class, numbering,
):
    legacy = {"md5": "owned-legacy", "size": 123, "fileName": "legacy.mp3", "track_no": 7}
    tracks = [{"track_no": 1, "md5": "builtin", "size": 9}, legacy]
    if numbering == "missing":
        legacy.pop("track_no")
    elif numbering == "duplicate":
        tracks.append({"track_no": 7, "md5": "other", "size": 456})
    elif numbering == "invalid":
        legacy["track_no"] = 0
    deletion = AsyncMock(return_value=True)
    write = AsyncMock(return_value={})
    manager = manager_class(
        data_dir=tmp_path,
        list_ringtones=AsyncMock(return_value=[{"id": "legacy-id", "md5": "owned-legacy", "size": 123}]),
        upload_ringtone=AsyncMock(), delete_ringtone=deletion,
        resolve_ringtone=AsyncMock(), refresh_index=AsyncMock(),
        get_chime=AsyncMock(return_value={"speakerTrackList": tracks}),
        play_ringtone=AsyncMock(),
    )
    manager.installation_id = "11111111-1111-1111-1111-111111111111"
    manager._bootstrap_audio[1] = b"silent cleanup audio"
    manager._targets["chime-1"] = SimpleNamespace(
        desc=SimpleNamespace(chime_id="chime-1"),
        direct_client=SimpleNamespace(overwrite_owned_slot=write),
    )
    removed = []
    registry = SimpleNamespace(
        records={"legacy": SimpleNamespace(owner="unifi_announcer", kind="dynamic_tts", nvr_ringtone_id="legacy-id")},
        remove=removed.append, put=lambda _record: None,
    )
    if numbering == "sparse":
        await manager._migrate_legacy(registry)
        write.assert_awaited_once()
        assert write.await_args.kwargs["slot"] == 7
        deletion.assert_awaited_once_with("legacy-id")
        assert removed == ["legacy"]
    else:
        with pytest.raises(DynamicSlotUnavailable, match="physical track number"):
            await manager._migrate_legacy(registry)
        write.assert_not_awaited()
        deletion.assert_not_awaited()
