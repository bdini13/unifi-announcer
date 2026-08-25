"""Deterministic playback value and quiet-hours policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PlaybackPolicy:
    profiles: Mapping[str, Mapping[str, Any]]
    volume_default: int
    repeat_default: int

    def resolve(self, *, volume: int | None, repeat_times: int | None,
                profile: str | None) -> tuple[int, int]:
        values = self.profiles.get(profile, {}) if profile else {}
        resolved_volume = volume if volume is not None else values.get("volume")
        resolved_repeat = repeat_times if repeat_times is not None else values.get("repeat")
        if resolved_volume is None:
            resolved_volume = self.volume_default
        if resolved_repeat is None:
            resolved_repeat = self.repeat_default
        return int(resolved_volume), int(resolved_repeat)

    @staticmethod
    def suppresses(*, quiet: bool, priority: int) -> bool:
        """Quiet hours apply only after priority is known; urgent work passes."""
        return quiet and priority >= 50
