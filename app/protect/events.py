"""Normalized Protect event contracts and update-frame decoder."""
from __future__ import annotations

from dataclasses import dataclass
import json
import struct
from typing import Any
import zlib


@dataclass(frozen=True)
class ProtectFrameHeader:
    """The observed eight-byte Protect update frame header."""

    packet_type: int
    payload_format: int
    compressed: bool
    reserved: int
    payload_length: int

    @classmethod
    def parse(cls, raw: bytes) -> "ProtectFrameHeader":
        if len(raw) < 8:
            raise ValueError("Protect frame is shorter than its 8-byte header")
        return cls(raw[0], raw[1], bool(raw[2]), raw[3], struct.unpack(">I", raw[4:8])[0])


@dataclass
class NormalizedProtectEvent:
    action: str
    model: str
    event_id: str | None = None
    event: str | None = None
    camera_id: str | None = None
    last_ring: int | None = None
    payload: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "model": self.model,
            "event_id": self.event_id,
            "event": self.event,
            "camera_id": self.camera_id,
            "last_ring": self.last_ring,
            **(self.payload or {}),
        }


def _decode_frame(raw: bytes) -> tuple[dict[str, Any] | None, bytes]:
    header = ProtectFrameHeader.parse(raw)
    if header.packet_type != 1 or header.payload_format != 1:
        return None, b""
    end = 8 + header.payload_length
    if header.payload_length <= 0 or end > len(raw):
        return None, b""
    payload = raw[8:end]
    if header.compressed:
        try:
            payload = zlib.decompress(payload)
        except zlib.error:
            return None, raw[end:]
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        decoded = None
    return decoded if isinstance(decoded, dict) else None, raw[end:]


def parse_update_frame(
    raw: bytes | str, data_raw: bytes | str | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Decode linked action/data frames, or separately supplied frame bytes.

    Only the observed JSON payload format is accepted. The header compression
    flag enables zlib decoding. Unsupported payload formats fail closed.
    """
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None, None
        return (value if isinstance(value, dict) else None), None
    try:
        action, remainder = _decode_frame(raw)
    except ValueError:
        return None, None
    second = data_raw if data_raw is not None else remainder
    if isinstance(second, str):
        try:
            value = json.loads(second)
            return action, value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return action, None
    if second:
        try:
            data, _ = _decode_frame(second)
        except ValueError:
            data = None
        return action, data
    return action, None
