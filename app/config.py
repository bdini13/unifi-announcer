"""Environment-backed application configuration."""
from __future__ import annotations

from dataclasses import dataclass
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() == "true"


@dataclass(frozen=True)
class Settings:
    unifi_host: str
    chime_id: str
    app_port: int
    volume_default: int
    repeat_default: int
    debug_timings: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            unifi_host=os.getenv("UNIFI_HOST", ""),
            chime_id=os.getenv("CHIME_ID", ""),
            app_port=int(os.getenv("APP_PORT", "8095")),
            volume_default=int(os.getenv("VOLUME_DEFAULT", "50")),
            repeat_default=int(os.getenv("REPEAT_DEFAULT", "1")),
            debug_timings=_bool("DEBUG_TIMINGS"),
        )
