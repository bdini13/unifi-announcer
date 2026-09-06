import asyncio
import json

import pytest

from app.playback.dynamic_slots import DeviceSlotBinding, DynamicTtsSlot
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


@pytest.mark.asyncio
async def test_device_lifecycle_invalidation_revokes_all_chime_content(tmp_path):
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

    for number in (1, 2):
        binding = DeviceSlotBinding(
            chime_id="chime-1",
            device_slot=number + 3,
            filename=f"ua_tts_{number}_deadbeef.mp3",
            provisioning_md5="bootstrap",
            provisioning_size=10,
            current_md5=f"content-{number}",
            current_size=100 + number,
        )
        manager.slots[number] = DynamicTtsSlot(
            logical_slot=number,
            protect_name=f"UA-TTS-{number}",
            protect_ringtone_id=f"ringtone-{number}",
            bootstrap_md5="bootstrap",
            bootstrap_size=10,
            bindings={"chime-1": binding},
        )
        manager._set_state_entry(
            number,
            "chime-1",
            {
                "source_md5": f"content-{number}",
                "source_size": 100 + number,
                "device_slot": number + 3,
                "filename": binding.filename,
            },
        )
        manager._trusted_content.add((number, "chime-1"))

    invalidated = await manager.invalidate_target_content(
        ["chime-1"], reason="device_reboot"
    )

    assert invalidated == 2
    assert manager._trusted_content == set()
    assert manager._content_state["bindings"] == {}
    assert all(
        binding.current_md5 is None and binding.current_size is None
        for slot in manager.slots.values()
        for binding in slot.bindings.values()
    )
    persisted = json.loads(manager.content_state_path.read_text())
    assert persisted["bindings"] == {}


@pytest.mark.asyncio
async def test_device_lifecycle_invalidation_waits_for_active_target_lease(tmp_path):
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
        current_md5="resident-content",
        current_size=123,
    )
    manager.slots[1] = DynamicTtsSlot(
        logical_slot=1,
        protect_name="UA-TTS-1",
        protect_ringtone_id="ringtone-1",
        bootstrap_md5="bootstrap",
        bootstrap_size=10,
        bindings={"chime-1": binding},
    )
    manager._set_state_entry(
        1,
        "chime-1",
        {
            "source_md5": "resident-content",
            "source_size": 123,
            "device_slot": 4,
            "filename": binding.filename,
        },
    )
    manager._trusted_content.add((1, "chime-1"))

    second_binding = DeviceSlotBinding(
        chime_id="chime-1",
        device_slot=5,
        filename="ua_tts_2_deadbeef.mp3",
        provisioning_md5="bootstrap",
        provisioning_size=10,
        current_md5="other-resident-content",
        current_size=321,
    )
    manager.slots[2] = DynamicTtsSlot(
        logical_slot=2,
        protect_name="UA-TTS-2",
        protect_ringtone_id="ringtone-2",
        bootstrap_md5="bootstrap",
        bootstrap_size=10,
        bindings={"chime-1": second_binding},
    )
    manager._set_state_entry(
        2,
        "chime-1",
        {
            "source_md5": "other-resident-content",
            "source_size": 321,
            "device_slot": 5,
            "filename": second_binding.filename,
        },
    )
    manager._trusted_content.add((2, "chime-1"))
    manager._busy.add(1)

    invalidation = asyncio.create_task(
        manager.invalidate_target_content(["chime-1"], reason="device_reconnect")
    )
    await asyncio.sleep(0)
    assert not invalidation.done()

    acquisition = asyncio.create_task(
        manager._acquire_slot_number_for_content(
            md5="resident-content", size=123, target_ids=["chime-1"]
        )
    )
    await asyncio.sleep(0)
    assert not acquisition.done()

    await manager.release_now(1)
    assert await invalidation == 2
    acquired_slot, _content_match = await acquisition
    await manager.release_now(acquired_slot)
    assert manager._trusted_content == set()
    assert manager._state_entry(1, "chime-1") is None
