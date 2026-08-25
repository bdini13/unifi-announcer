"""Disconnected UCP4 research boundary.

This module intentionally contains no socket, HTTP, subprocess, file, or key
handling. It can validate a tiny read-only command vocabulary, but it cannot
send a command until a separately approved transport and trust model exist.
"""
from __future__ import annotations

from dataclasses import dataclass
import os


class Ucp4ResearchError(RuntimeError):
    """Base class for fail-closed research-client errors."""


class ResearchDisabled(Ucp4ResearchError):
    """Raised when the default-off research flag is not enabled."""


class ResearchCommandDenied(Ucp4ResearchError):
    """Raised for playback, mutation, destructive, or unknown commands."""


class ResearchTransportUnavailable(Ucp4ResearchError):
    """Raised because no legitimate callable transport was found."""


_READ_ONLY_COMMANDS = frozenset({"getstatus", "getversion", "getcapabilities"})
_PERMANENTLY_DENIED = frozenset(
    {
        "playspeaker",
        "playbuzzer",
        "adopt",
        "factoryreset",
        "changepassword",
        "deleteringtone",
        "uploadringtone",
        "reboot",
    }
)


@dataclass(frozen=True)
class Ucp4ResearchClient:
    """Default-off interface with deliberately no production transport."""

    enabled: bool = False

    @classmethod
    def from_env(cls) -> "Ucp4ResearchClient":
        return cls(enabled=os.getenv("UCP4_RESEARCH_ENABLED", "false").lower() == "true")

    def status(self) -> dict[str, bool | str]:
        return {
            "enabled": self.enabled,
            "connected": False,
            "transport": "unavailable",
            "protocol": "research_only",
        }

    def request(self, command: str) -> None:
        """Validate policy and fail before any possible I/O.

        Denial is checked before the feature flag so prohibited command names
        remain prohibited in every configuration.
        """
        normalized = "".join(character for character in command.lower() if character.isalnum())
        if normalized in _PERMANENTLY_DENIED or normalized not in _READ_ONLY_COMMANDS:
            raise ResearchCommandDenied(f"UCP4 research command denied: {command}")
        if not self.enabled:
            raise ResearchDisabled("UCP4 research is disabled")
        raise ResearchTransportUnavailable("no verified UCP4 transport or trust path")
