"""Optional MQTT integration and canonical command conversion."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from urllib.parse import urlparse
from typing import Any, Awaitable, Callable

from app.dispatcher import AnnouncementCommand

log = logging.getLogger("unifi-announcer")
ROOT = "unifi-announcer"


def _topic_target(topic: str | None) -> str | None:
    parts = (topic or "").split("/")
    if len(parts) == 4 and parts[:2] == [ROOT, "chime"] and parts[3] == "play":
        return parts[2]
    return None


def mqtt_command(payload: dict, *, topic: str | None = None) -> AnnouncementCommand:
    """Convert an MQTT payload/topic into the transport-neutral command."""
    target = payload.get("target") or _topic_target(topic)
    if payload.get("buzzer"):
        return AnnouncementCommand(action="buzzer", target=target, source="mqtt")
    common = {
        "volume": payload.get("volume"),
        "repeat_times": payload.get("repeat_times"),
        "profile": payload.get("profile"),
        "priority": payload.get("priority", 50),
        "target": target,
        "source": "mqtt",
    }
    if payload.get("default"):
        return AnnouncementCommand(action="play_default", **common)
    if payload.get("preset"):
        return AnnouncementCommand(action="play_preset", preset=payload["preset"], **common)
    return AnnouncementCommand(action="announce", text=payload.get("text"), **common)


class MqttBridge:
    def __init__(
        self,
        dispatch: Callable[[AnnouncementCommand], Awaitable[Any]] | None = None,
        discovery_chimes: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.task: asyncio.Task | None = None
        self.connected = False
        self._client: Any = None
        self._dispatch = dispatch
        self._discovery_chimes = discovery_chimes or (lambda: [])
        self.url = os.getenv("MQTT_URL", "")
        self.username = os.getenv("MQTT_USERNAME", "")
        self.password = os.getenv("MQTT_PASSWORD", "")

    def bind(self, dispatch: Callable[[AnnouncementCommand], Awaitable[Any]]) -> None:
        self._dispatch = dispatch

    def bind_discovery(self, discovery_chimes: Callable[[], list[dict[str, Any]]]) -> None:
        self._discovery_chimes = discovery_chimes

    async def start(self) -> None:
        if self.url and self.task is None:
            self.task = asyncio.create_task(self._run())

    def _make_client(self) -> Any:
        """Build a client using the API exposed by pinned aiomqtt 2.3.0."""
        import aiomqtt
        parsed = urlparse(self.url)
        return aiomqtt.Client(
            hostname=parsed.hostname or "localhost",
            port=parsed.port or 1883,
            username=self.username or None,
            password=self.password or None,
            will=aiomqtt.Will(f"{ROOT}/status", "offline", retain=True),
        )

    async def _run(self) -> None:
        backoff = 2
        while True:
            try:
                async with self._make_client() as client:
                    self._client = client
                    self.connected = True
                    backoff = 2
                    await client.publish(f"{ROOT}/status", "online", retain=True)
                    await self._publish_discovery(client)
                    await client.subscribe(f"{ROOT}/announce")
                    await client.subscribe(f"{ROOT}/chime/+/play")
                    async for message in client.messages:
                        await self._on_message(message)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                log.warning("MQTT error (%s); retrying in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                self.connected = False
                self._client = None

    @staticmethod
    def _device(name: str) -> dict[str, Any]:
        return {
            "identifiers": [f"unifi_announcer_{name}"],
            "name": f"UniFi Chime {name}",
            "manufacturer": "Ubiquiti",
            "via_device": "unifi_announcer",
        }

    async def _publish_discovery(self, client: Any) -> None:
        for chime in self._discovery_chimes():
            name = chime["name"]
            command_topic = f"{ROOT}/chime/{name}/play"
            device = self._device(name)
            availability = f"{ROOT}/status"
            buttons = {
                "buzzer": {"buzzer": True, "target": name},
                "default": {"default": True, "target": name},
            }
            for kind, press_payload in buttons.items():
                payload = {
                    "name": kind.replace("_", " ").title(),
                    "unique_id": f"unifi_announcer_{name}_{kind}",
                    "command_topic": command_topic,
                    "payload_press": json.dumps(press_payload, separators=(",", ":")),
                    "availability_topic": availability,
                    "device": device,
                }
                await client.publish(
                    f"homeassistant/button/unifi_announcer/{name}_{kind}/config",
                    json.dumps(payload), retain=True,
                )
            sensors = {
                "direct_health": chime.get("direct_health", "unknown"),
                "queue_depth": chime.get("queue_depth", 0),
                "firmware": chime.get("firmware") or "unknown",
                "last_ring": chime.get("last_ring") or "unknown",
            }
            for kind, state in sensors.items():
                state_topic = f"{ROOT}/chime/{name}/{kind}"
                payload = {
                    "name": kind.replace("_", " ").title(),
                    "unique_id": f"unifi_announcer_{name}_{kind}",
                    "state_topic": state_topic,
                    "availability_topic": availability,
                    "device": device,
                }
                if kind == "queue_depth":
                    payload["state_class"] = "measurement"
                await client.publish(
                    f"homeassistant/sensor/unifi_announcer/{name}_{kind}/config",
                    json.dumps(payload), retain=True,
                )
                await client.publish(state_topic, str(state), retain=True)

    async def _on_message(self, message: Any) -> None:
        try:
            payload = json.loads(message.payload or b"{}")
        except (json.JSONDecodeError, TypeError):
            log.warning("Ignoring invalid MQTT JSON on %s", message.topic)
            return
        topic = str(message.topic)
        if topic != f"{ROOT}/announce" and not topic.endswith("/play"):
            return
        dispatch = self._dispatch
        if dispatch is None:
            from app import main
            dispatch = main.dispatcher.dispatch
        try:
            result = await dispatch(mqtt_command(payload, topic=topic))
            log.info("MQTT command disposition=%s action=%s",
                     result.disposition, result.action)
            await self.publish_disposition(result)
        except Exception as exc:
            log.warning("MQTT command failed: %s", exc)

    async def publish_disposition(self, result: Any) -> None:
        await self._publish(
            f"{ROOT}/disposition",
            json.dumps({"action": result.action,
                        "disposition": result.disposition,
                        **result.result}, default=str),
        )

    async def _publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
        client = self._client
        if not (self.connected and client is not None):
            return
        try:
            await client.publish(topic, payload, retain=retain)
        except Exception:
            log.debug("MQTT publish failed", exc_info=True)

    async def publish_event(self, event: dict) -> None:
        await self._publish(f"{ROOT}/event", json.dumps(event, default=str))
        last_ring = event.get("lastRing") or event.get("last_ring")
        if last_ring is not None:
            for chime in self._discovery_chimes():
                await self._publish(
                    f"{ROOT}/chime/{chime['name']}/last_ring",
                    str(last_ring), retain=True,
                )

    async def stop(self) -> None:
        # Publish graceful retained availability while the active connection is
        # still usable; the LWT remains the crash/ungraceful-disconnect path.
        if self.connected and self._client is not None:
            try:
                await self._client.publish(f"{ROOT}/status", "offline", retain=True)
            except Exception:
                log.debug("MQTT offline publish failed", exc_info=True)
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
