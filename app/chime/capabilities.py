"""Firmware-aware direct-device capability model used at runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(init=False)
class DirectDeviceCapabilities:
    firmware: str
    device_type: str
    has_wifi: bool
    has_https_ota: bool
    supports_custom_ringtone: bool

    def __init__(self, info: dict[str, Any] | None = None, **values: Any) -> None:
        info = info or {}
        self.firmware = str(values.get("firmware", info.get("version", "unknown")))
        self.device_type = str(values.get("device_type", info.get("type", "unknown")))
        flags = info.get("featureFlags") or {}
        self.has_wifi = bool(values.get("has_wifi", flags.get("hasWifi")))
        self.has_https_ota = bool(values.get("has_https_ota", flags.get("hasHttpsClientOTA")))
        self.supports_custom_ringtone = bool(values.get(
            "supports_custom_ringtone", flags.get("supportCustomRingtone")))

    @classmethod
    def from_info(cls, info: dict) -> "DirectDeviceCapabilities":
        return cls(info)

    @property
    def known_firmware(self) -> bool:
        return self.firmware.startswith(("v1.7.", "1.7."))

    @property
    def ringtone_write(self) -> bool:
        return self.allows_upload()

    @property
    def info_read(self) -> bool:
        return True

    @property
    def support_log_read(self) -> bool:
        return True

    def allows_upload(self) -> bool:
        return self.known_firmware and self.supports_custom_ringtone

    def to_dict(self) -> dict:
        return {"firmware": self.firmware, "device_type": self.device_type,
                "has_wifi": self.has_wifi, "has_https_client_ota": self.has_https_ota,
                "supports_custom_ringtone": self.supports_custom_ringtone,
                "direct_upload_allowed": self.allows_upload()}
