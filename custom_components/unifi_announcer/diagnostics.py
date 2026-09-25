"""Diagnostics support for UniFi Announcer."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .api import UniFiAnnouncerError
from .const import INTEGRATION_VERSION

TO_REDACT = {"api_key", "password", "token", "authorization"}


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    runtime = entry.runtime_data
    data = runtime.coordinator.data or {}
    safe_entry = async_redact_data(dict(entry.data), TO_REDACT)
    try:
        backend_support = await runtime.client.async_get_support_bundle()
    except UniFiAnnouncerError as exc:
        # Do not copy exception text into a shareable diagnostic record. A
        # transport/server exception may contain private addresses or details.
        backend_support = {
            "available": False,
            "error_type": type(exc).__name__,
        }

    return {
        "config_entry": safe_entry,
        "options": dict(entry.options),
        "integration_version": INTEGRATION_VERSION,
        "announcer_version": runtime.version,
        "backend_support": backend_support,
        "health": data.get("health", {}),
        "chimes": [
            {
                "name": c.get("name"),
                "queue_depth": c.get("queue_depth"),
                "capability_state": c.get("capability_state"),
            }
            for c in data.get("chimes", {}).get("chimes", [])
        ],
        "cameras": [
            {
                "name": c.get("name"),
                "model": (c.get("capability_state") or {}).get("model"),
                "queue_depth": c.get("queue_depth"),
                "status": (c.get("capability_state") or {}).get("status"),
                "capabilities": c.get("capabilities") or {},
            }
            for c in data.get("chimes", {}).get("cameras", [])
        ],
        "group_capabilities": data.get("chimes", {}).get(
            "group_capabilities", {}
        ),
        "groups": list((data.get("chimes", {}).get("groups") or {}).keys()),
        "presets": [p.get("name") for p in data.get("presets", []) if p.get("name")],
    }
