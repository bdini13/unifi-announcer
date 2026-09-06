import json

from app.playback.dynamic_slots import DeviceSlotBinding
from app.playback.production_slots import DynamicTtsSlotManager


async def _unused(*_args, **_kwargs):
    return None


def test_write_ahead_invalidation_revokes_old_content_before_physical_write(tmp_path):
    manager = DynamicTtsSlotManager(
        data_dir=tmp_path,
        list_ringtones=_unused,
        upload_ringtone=_unused,
        delete_ringtone=_unused,
        resolve_ringtone=_unused,
        refresh_index=_unused,
        get_chime=_unused,
        play_ringtone=_unused,
    )
    manager.installation_id = "11111111-1111-1111-1111-111111111111"
    manager._content_state = manager._empty_content_state()

    binding = DeviceSlotBinding(
        chime_id="chime-1",
        device_slot=4,
        filename="ua_tts_1_deadbeef.mp3",
        provisioning_md5="bootstrap",
        provisioning_size=10,
        current_md5="old-content",
        current_size=123,
    )
    manager._set_state_entry(
        1,
        "chime-1",
        {
            "source_md5": "old-content",
            "source_size": 123,
            "device_slot": 4,
            "filename": "ua_tts_1_deadbeef.mp3",
            "write_generation": 7,
        },
    )
    manager._trusted_content.add((1, "chime-1"))

    manager._invalidate_content_proof(1, "chime-1", binding)

    assert (1, "chime-1") not in manager._trusted_content
    assert manager._state_entry(1, "chime-1") is None
    assert binding.current_md5 is None
    assert binding.current_size is None

    persisted = json.loads(manager.content_state_path.read_text())
    assert persisted["installation_id"] == manager.installation_id
    assert persisted["bindings"] == {}

    # A process crash at this point cannot resurrect the old content proof:
    # the write-ahead invalidation is already durable before network I/O.
    reloaded = DynamicTtsSlotManager(
        data_dir=tmp_path,
        list_ringtones=_unused,
        upload_ringtone=_unused,
        delete_ringtone=_unused,
        resolve_ringtone=_unused,
        refresh_index=_unused,
        get_chime=_unused,
        play_ringtone=_unused,
    )
    reloaded.installation_id = manager.installation_id
    reloaded._load_content_state()
    assert reloaded._state_entry(1, "chime-1") is None
