import pytest

from app.experimental.dynamic_slots import DynamicSlotPool, SlotMetadata


def test_dynamic_slots_default_off_is_impossible_to_use():
    pool = DynamicSlotPool(enabled=False, slots=[SlotMetadata(7, "unifi_announcer")])
    with pytest.raises(RuntimeError, match="DYNAMIC_SLOT_EXPERIMENT"):
        pool.reserve()


def test_dynamic_slots_require_owned_non_builtin_metadata():
    pool = DynamicSlotPool(enabled=True, slots=[
        SlotMetadata(0, "builtin", builtin=True), SlotMetadata(1, "user"),
    ])
    with pytest.raises(RuntimeError, match="service-owned"):
        pool.reserve()
    owned = DynamicSlotPool(enabled=True, slots=[SlotMetadata(4, "unifi_announcer")])
    assert owned.reserve().slot == 4


def test_dynamic_slot_scaffold_remains_metadata_only():
    pool = DynamicSlotPool(enabled=True, slots=[
        SlotMetadata(6, "unifi_announcer", logical_key="ua-tts-slot-a"),
        SlotMetadata(7, "unifi_announcer", logical_key="ua-tts-slot-b"),
    ])
    assert pool.reserve().logical_key == "ua-tts-slot-a"
    for operation in ("upload", "overwrite", "play", "delete"):
        assert not hasattr(pool, operation)
