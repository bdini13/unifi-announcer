"""Shared Home Assistant entities for UniFi Announcer."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def configured_targets(coordinator) -> list[tuple[str, str | None, bool]]:
    """Return (target name, chime id, is_group) tuples from coordinator state."""
    data = coordinator.data or {}
    chime_data = data.get("chimes", {})
    targets: list[tuple[str, str | None, bool]] = []
    for chime in chime_data.get("chimes", []):
        name = str(chime.get("name") or chime.get("id") or "chime")
        targets.append((name, chime.get("id"), False))
    for group in (chime_data.get("groups") or {}):
        targets.append((str(group), None, True))
    return targets


class UniFiAnnouncerEntity(CoordinatorEntity):
    """Base coordinator-backed entity."""

    _attr_has_entity_name = True

    def __init__(self, entry, coordinator, target: str | None = None,
                 chime_id: str | None = None, is_group: bool = False) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.runtime = entry.runtime_data
        self.target = target
        self.chime_id = chime_id
        self.is_group = is_group

    @property
    def device_info(self) -> DeviceInfo:
        service_identifier = (DOMAIN, self.entry.data["url"])
        if self.target and self.chime_id and not self.is_group:
            return DeviceInfo(
                identifiers={(DOMAIN, str(self.chime_id))},
                name=self.target,
                manufacturer="Ubiquiti",
                model="Protect Smart Chime",
                via_device=service_identifier,
            )
        return DeviceInfo(
            identifiers={service_identifier},
            name=self.entry.title,
            manufacturer="UniFi Announcer",
            model="Local announcement service",
            entry_type=DeviceEntryType.SERVICE,
        )
