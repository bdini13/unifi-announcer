"""Optional Model Context Protocol interface for UniFi Announcer.

The MCP layer is deliberately thin: tools resolve AppServices at call time and
submit the same canonical AnnouncementCommand objects used by REST, MQTT and
local rules. It never creates its own Protect, TTS, cache or playback clients.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Callable

from app.routes.commands import announce_command, buzzer_command, default_command, preset_command


@dataclass
class MCPRuntime:
    """Mounted MCP application plus lifecycle-owned server."""

    server: Any
    app: Any


class _BearerAuthASGI:
    """Small ASGI wrapper for a dedicated MCP bearer key."""

    def __init__(self, app: Any, key: str) -> None:
        self.app = app
        self.key = key

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http" and self.key:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            supplied = headers.get("authorization", "")
            expected = f"Bearer {self.key}"
            if not hmac.compare_digest(supplied, expected):
                body = b'{"detail":"invalid or missing MCP bearer token"}'
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def build_mcp_runtime(
    services: Callable[[], Any], *, api_key: str, allowed_hosts: list[str],
    groups: Callable[[], dict[str, list[str]]] | None = None,
) -> MCPRuntime:
    """Build a mountable MCP v2 server."""
    from mcp.server import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings

    server = MCPServer(
        "UniFi Announcer",
        instructions=(
            "Local announcement tools for configured UniFi Protect Smart Chimes. "
            "Playback obeys the service's existing target, quiet-hours, queue, "
            "dedupe and volume policies."
        ),
    )

    def _result(result: Any, message: str) -> dict[str, Any]:
        payload = result.response()
        return {
            "disposition": payload.get("disposition", result.disposition),
            "targets": [job.get("target") for job in payload.get("jobs", []) if job.get("target")],
            "message": message,
            "details": payload,
        }

    @server.tool()
    async def get_status() -> dict[str, Any]:
        """Return cached service/component health without causing playback."""
        svc = services()
        status = dict(svc.health.snapshot())
        dynamic_slots = getattr(svc, "dynamic_slots", None)
        if dynamic_slots is not None:
            status["dynamic_tts"] = dynamic_slots.status()
        tts_cache = getattr(svc, "tts_cache", None)
        if tts_cache is not None:
            status["tts_cache"] = tts_cache.stats()
        return status

    @server.tool()
    async def list_chimes() -> dict[str, Any]:
        """List configured chimes, groups and current queue depths."""
        svc = services()
        return {
            "chimes": [
                {"name": name, "queue_depth": runtime.queue.depth,
                 "capability_state": runtime.capability_state}
                for name, runtime in svc.chime_runtimes.items()
            ],
            "groups": groups() if groups is not None else {},
        }

    @server.tool()
    async def list_presets() -> dict[str, Any]:
        """List user-facing Protect ringtone presets, excluding internal TTS slots."""
        tones = await services().ringtone_backend.list_ringtones()
        return {"presets": [
            {"name": t.get("name"), "is_default": bool(t.get("isDefault"))}
            for t in tones
            if not t.get("isDefault")
            and not str(t.get("name", "")).upper().startswith("UA-TTS-")
        ]}

    @server.tool()
    async def get_recent_events(limit: int = 10) -> dict[str, Any]:
        """Return recent normalized Protect events from the in-memory ring buffer."""
        limit = max(1, min(int(limit), 100))
        items = list(services().events.recent)[-limit:]
        items.reverse()
        return {"connected": services().events.connected, "events": items}

    @server.tool()
    async def get_queue_status() -> dict[str, Any]:
        """Return current per-chime playback queue depths."""
        return {name: runtime.queue.depth for name, runtime in services().chime_runtimes.items()}

    @server.tool()
    async def announce(text: str, target: str | None = None,
                       volume: int | None = None, repeat_times: int | None = None,
                       profile: str | None = None, priority: int = 50,
                       dedupe_key: str | None = None) -> dict[str, Any]:
        """Speak text on a configured chime or group."""
        if not text or not text.strip() or len(text) > 500:
            raise ValueError("text must contain 1-500 characters")
        result = await services().dispatcher.dispatch(announce_command(
            text.strip(), target=target, volume=volume, repeat_times=repeat_times,
            profile=profile, priority=priority, dedupe_key=dedupe_key, source="mcp"))
        return _result(result, "Announcement processed")

    @server.tool()
    async def play_preset(name: str, target: str | None = None,
                          volume: int | None = None, repeat_times: int | None = None,
                          priority: int = 50, dedupe_key: str | None = None) -> dict[str, Any]:
        """Play an existing preset on a configured chime or group."""
        result = await services().dispatcher.dispatch(preset_command(
            name, target=target, volume=volume, repeat_times=repeat_times,
            priority=priority, dedupe_key=dedupe_key, source="mcp"))
        return _result(result, "Preset processed")

    @server.tool()
    async def play_default(target: str | None = None, volume: int | None = None,
                           repeat_times: int | None = None, priority: int = 50) -> dict[str, Any]:
        """Play each target's assigned default ringtone."""
        result = await services().dispatcher.dispatch(default_command(
            target=target, volume=volume, repeat_times=repeat_times,
            priority=priority, source="mcp"))
        return _result(result, "Default playback processed")

    @server.tool()
    async def buzzer(target: str | None = None, priority: int = 50) -> dict[str, Any]:
        """Play the physical Smart Chime buzzer."""
        result = await services().dispatcher.dispatch(buzzer_command(
            target=target, priority=priority, source="mcp"))
        return _result(result, "Buzzer processed")

    host_patterns = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    for host in allowed_hosts:
        host = host.strip()
        if host:
            host_patterns.extend([host, f"{host}:*"])
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(set(host_patterns)),
        allowed_origins=[],
    )
    mcp_app = server.streamable_http_app(
        streamable_http_path="/",
        transport_security=security,
    )
    return MCPRuntime(server=server, app=_BearerAuthASGI(mcp_app, api_key))
