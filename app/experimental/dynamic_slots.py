"""Default-off scaffold for a future controlled slot experiment."""
from dataclasses import dataclass

SERVICE_OWNER = "unifi_announcer"


@dataclass(frozen=True)
class SlotMetadata:
    slot: int
    owner: str
    builtin: bool = False
    logical_key: str | None = None


class DynamicSlotPool:
    """Selects metadata only; it contains no upload, overwrite, or playback I/O."""

    def __init__(self, *, enabled: bool, slots: list[SlotMetadata]) -> None:
        self.enabled = enabled
        self.slots = tuple(slots)

    def reserve(self) -> SlotMetadata:
        if not self.enabled:
            raise RuntimeError("DYNAMIC_SLOT_EXPERIMENT is false")
        candidate = next((slot for slot in self.slots
                          if slot.owner == SERVICE_OWNER and not slot.builtin), None)
        if candidate is None:
            raise RuntimeError("no explicitly service-owned non-built-in slot metadata")
        return candidate
