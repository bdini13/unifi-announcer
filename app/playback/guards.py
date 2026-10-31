"""Durable acoustic deadlines: an HTTP/process lifetime is not a sound lifetime."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import time

from app.persistence import atomic_json


def _boot_identity() -> str | None:
    """Use the host boot identity, shared across processes and containers."""
    try:
        if sys.platform.startswith("linux"):
            value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        elif sys.platform == "darwin":
            value = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
                check=True, capture_output=True, text=True, timeout=1,
            ).stdout.strip()
        else:
            return None
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


class PlaybackGuards:
    """Persist deadlines before sending a command that might start sound.

    Wall deadlines survive host/container replacement. The companion monotonic
    deadline avoids shortening a hold on same-host wall-clock adjustments.
    Malformed safety state fails closed instead of silently discarding holds.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, dict] = {}
        self.boot_id = _boot_identity()
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                    raise ValueError("unsupported guard schema")
                entries = raw["targets"]
                if not isinstance(entries, dict):
                    raise ValueError("invalid target guards")
                for key, entry in entries.items():
                    if not isinstance(key, str) or not isinstance(entry, dict):
                        raise ValueError("invalid target guard")
                    for field in ("wall_until", "monotonic_until", "written_monotonic"):
                        value = entry[field]
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                            raise ValueError("invalid guard deadline")
                    if entry["monotonic_until"] < entry["written_monotonic"]:
                        raise ValueError("guard ends before it was written")
                    if entry.get("boot_id") is not None and not isinstance(entry["boot_id"], str):
                        raise ValueError("invalid guard boot identity")
                rebased = False
                now = time.monotonic()
                for entry in entries.values():
                    changed_boot = bool(self.boot_id and entry.get("boot_id")
                                        and self.boot_id != entry["boot_id"])
                    if changed_boot or now < entry["written_monotonic"]:
                        # Remote sound can outlive a reboot of the service host.
                        # Its old uptime and a corrected wall clock cannot prove
                        # elapsed time: hold one full recorded period. Persist
                        # the fixed deadline so another process restart neither
                        # discards it nor starts the quarantine over again.
                        seconds = entry["monotonic_until"] - entry["written_monotonic"]
                        entry.update(wall_until=time.time() + seconds,
                                     monotonic_until=now + seconds,
                                     written_monotonic=now, boot_id=self.boot_id)
                        rebased = True
                if rebased:
                    atomic_json(path, {"schema_version": 1, "targets": entries})
                self.entries = entries
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise RuntimeError("playback guard state is invalid; retain it for recovery before enabling playback") from exc

    @staticmethod
    def key(target) -> str:
        return f"{target.desc.kind}:{target.desc.device_id}"

    def remaining(self, target) -> float:
        entry = self.entries.get(self.key(target))
        if entry is None:
            return 0.0
        wall = entry["wall_until"] - time.time()
        now = time.monotonic()
        monotonic = entry["monotonic_until"] - now
        return max(0.0, wall, monotonic)

    def hold(self, target, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("playback guard duration must be finite and nonnegative")
        now = time.monotonic()
        entries = {**self.entries, self.key(target): {
            "wall_until": time.time() + seconds,
            "monotonic_until": now + seconds,
            "written_monotonic": now,
            "boot_id": self.boot_id,
        }}
        atomic_json(self.path, {"schema_version": 1, "targets": entries})
        self.entries = entries
