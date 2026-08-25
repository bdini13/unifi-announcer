"""Status sensors for UniFi Announcer."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity

from .entity import UniFiAnnouncerEntity, configured_targets


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.coordinator
    entities = [
        UniFiAnnouncerServiceSensor(entry, coordinator, "status"),
        UniFiAnnouncerServiceSensor(entry, coordinator, "version"),
    ]
    for target, chime_id, is_group in configured_targets(coordinator):
        entities.extend([
            UniFiAnnouncerTargetSensor(entry, coordinator, target, chime_id, is_group, "queue_depth"),
            UniFiAnnouncerTargetSensor(entry, coordinator, target, chime_id, is_group, "last_disposition"),
        ])
    async_add_entities(entities)


class UniFiAnnouncerServiceSensor(UniFiAnnouncerEntity, SensorEntity):
    """Service-level health/version sensor."""

    def __init__(self, entry, coordinator, kind: str) -> None:
        super().__init__(entry, coordinator)
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_translation_key = kind
        self._attr_name = None

    @property
    def native_value(self):
        if self.kind == "version":
            return self.runtime.version.get("git_sha") or self.runtime.version.get("service")
        health = (self.coordinator.data or {}).get("health", {})
        return health.get("status", "unknown")


class UniFiAnnouncerTargetSensor(UniFiAnnouncerEntity, SensorEntity):
    """Per-target queue/disposition sensor."""

    def __init__(self, entry, coordinator, target, chime_id, is_group, kind: str) -> None:
        super().__init__(entry, coordinator, target, chime_id, is_group)
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{target}_{kind}"
        self._attr_translation_key = kind
        self._attr_name = target

    @property
    def native_value(self):
        if self.kind == "last_disposition":
            return self.runtime.last_disposition.get(self.target, "unknown")
        for item in (self.coordinator.data or {}).get("chimes", {}).get("chimes", []):
            if item.get("name") == self.target:
                return item.get("queue_depth", 0)
        return 0
