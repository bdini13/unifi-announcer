"""Protect capability boundaries without fabricating official API routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProtectStateBackend(Protocol):
    async def list_chimes(self) -> list[dict]: ...
    async def get_chime(self, *, chime_id: str | None = None) -> dict: ...


@runtime_checkable
class PlaybackBackend(Protocol):
    async def play(self, ringtone_id: str | None = None, volume: int = 50,
                   repeat_times: int = 1, *, chime_id: str | None = None) -> dict: ...
    async def play_buzzer(self, *, chime_id: str | None = None) -> dict: ...
    async def play_default(self, volume: int | None = None,
                           repeat_times: int | None = None, *,
                           chime_id: str | None = None) -> dict: ...


@runtime_checkable
class RingtoneBackend(Protocol):
    async def list_ringtones(self) -> list[dict]: ...
    async def upload_ringtone(self, name: str, mp3: bytes) -> dict: ...
    async def delete_ringtone(self, ringtone_id: str) -> bool: ...


@dataclass(frozen=True)
class ProtectBackends:
    state: ProtectStateBackend
    playback: PlaybackBackend
    ringtone: RingtoneBackend
    source: str
    official_status: str = "not-configured"


def select_protect_backends(*, private, official_api_key: str,
                            official_base_url: str) -> ProtectBackends:
    """Keep verified private paths until official endpoint mappings exist.

    An API key/base URL alone does not define endpoint paths or response schemas.
    The selector records configuration readiness but deliberately creates no
    official HTTP client and performs no network I/O.
    """
    status = ("configured-but-no-verified-endpoint-mapping"
              if official_api_key and official_base_url else "not-configured")
    return ProtectBackends(private, private, private, "private-session", status)
