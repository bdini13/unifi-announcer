"""Diagnostics support for UniFi Announcer."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import INTEGRATION_VERSION

TO_REDACT = {"api_key", "password", "token", "authorization"}


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    runtime = entry.runtime_data
    data = runtime.coordinator.data or {}
    safe_entry = async_redact_data(dict(entry.data), TO_REDACT)
    return {
        "config_entry": safe_entry,
        "options": dict(entry.options),
        "integration_version": INTEGRATION_VERSION,
        "announcer_version": runtime.version,
        "health": data.get("health", {}),
        "chimes": [
            {
                "name": c.get("name"),
                "queue_depth": c.get("queue_depth"),
                "capability_state": c.get("capability_state"),
            }
            for c in data.get("chimes", {}).get("chimes", [])
        ],
        "groups": list((data.get("chimes", {}).get("groups") or {}).keys()),
        "presets": [p.get("name") for p in data.get("presets", []) if p.get("name")],
    }
