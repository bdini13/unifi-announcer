import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.dispatcher import AnnouncementCommand, DispatchResult
from app.integrations.mqtt import MqttBridge, mqtt_command


@pytest.mark.asyncio
async def test_pinned_aiomqtt_client_construction_uses_supported_will_api(monkeypatch):
    """Construct the real aiomqtt client without contacting a broker."""
    monkeypatch.setenv("MQTT_URL", "mqtt://broker.invalid:1884")
    bridge = MqttBridge()

    client = bridge._make_client()

    assert client._client._will_topic == b"unifi-announcer/status"
    assert client._client._will_payload == b"offline"
    assert client._client._will_retain is True


def test_main_mqtt_discovery_uses_runtime_registry(main_module):
    discovered = main_module.mqtt_bridge._discovery_chimes()

    assert [item["name"] for item in discovered] == list(main_module.chime_runtimes)


def test_mqtt_discovery_reports_lazy_per_chime_capability_state(
    main_module, monkeypatch
):
    runtime = SimpleNamespace(
        desc=SimpleNamespace(direct_ip=""), direct_client=SimpleNamespace(),
        capability_state={"status": "available", "firmware": "v1.7.20"},
        queue=SimpleNamespace(depth=0),
    )
    monkeypatch.setattr(main_module, "chime_runtimes", {"upstairs": runtime})

    discovered = main_module._mqtt_discovery_chimes()

    assert discovered[0]["direct_health"] == "available"
    assert discovered[0]["firmware"] == "v1.7.20"


def test_mqtt_command_supports_default_and_topic_target():
    command = mqtt_command(
        {"default": True, "profile": "night", "priority": 10},
        topic="unifi-announcer/chime/kitchen/play",
    )

    assert command == AnnouncementCommand(
        action="play_default", profile="night", priority=10,
        target="kitchen", source="mqtt",
    )


@pytest.mark.asyncio
async def test_stop_publishes_retained_offline_before_cancelling_connection():
    order = []
    client = SimpleNamespace(publish=AsyncMock(
        side_effect=lambda *args, **kwargs: order.append(
            ("publish", args[0], args[1], kwargs.get("retain")))))
    bridge = MqttBridge()
    bridge.connected = True
    bridge._client = client

    async def active_connection():
        try:
            await asyncio.Event().wait()
        finally:
            order.append(("cancelled",))

    bridge.task = asyncio.create_task(active_connection())
    await asyncio.sleep(0)

    await bridge.stop()

    assert order == [
        ("publish", "unifi-announcer/status", "offline", True),
        ("cancelled",),
    ]


@pytest.mark.asyncio
async def test_one_active_broker_client_handles_100_publishes():
    client = SimpleNamespace(publish=AsyncMock())
    bridge = MqttBridge()
    bridge.connected = True
    bridge._client = client

    await asyncio.gather(*(bridge.publish_event({"sequence": n}) for n in range(100)))

    assert client.publish.await_count == 100
    assert all(call.args[0] == "unifi-announcer/event"
               for call in client.publish.await_args_list)


@pytest.mark.asyncio
async def test_message_handler_dispatches_canonical_command_and_publishes_result():
    dispatch = AsyncMock(return_value=DispatchResult("play_default", "played"))
    bridge = MqttBridge(dispatch)
    bridge.publish_disposition = AsyncMock()

    await bridge._on_message(SimpleNamespace(
        topic="unifi-announcer/chime/kitchen/play",
        payload=b'{"default":true,"profile":"night","priority":10}',
    ))

    command = dispatch.await_args.args[0]
    assert command == AnnouncementCommand(
        action="play_default", profile="night", priority=10,
        target="kitchen", source="mqtt",
    )
    bridge.publish_disposition.assert_awaited_once()


@pytest.mark.asyncio
async def test_ha_discovery_is_published_per_chime_with_actual_topics():
    client = SimpleNamespace(publish=AsyncMock())
    bridge = MqttBridge(discovery_chimes=lambda: [
        {
            "name": "kitchen",
            "queue_depth": 2,
            "direct_health": "available",
            "firmware": "1.7.3",
            "last_ring": 1234,
        },
        {
            "name": "hallway",
            "queue_depth": 0,
            "direct_health": "unconfigured",
            "firmware": None,
            "last_ring": None,
        },
    ])

    await bridge._publish_discovery(client)

    publishes = {call.args[0]: json.loads(call.args[1])
                 for call in client.publish.await_args_list
                 if call.args[0].startswith("homeassistant/")}
    for name in ("kitchen", "hallway"):
        prefix = "homeassistant"
        assert f"{prefix}/button/unifi_announcer/{name}_buzzer/config" in publishes
        assert f"{prefix}/button/unifi_announcer/{name}_default/config" in publishes
        assert f"{prefix}/sensor/unifi_announcer/{name}_direct_health/config" in publishes
        assert f"{prefix}/sensor/unifi_announcer/{name}_queue_depth/config" in publishes
        assert f"{prefix}/sensor/unifi_announcer/{name}_firmware/config" in publishes
        assert f"{prefix}/sensor/unifi_announcer/{name}_last_ring/config" in publishes
        buzzer = publishes[f"{prefix}/button/unifi_announcer/{name}_buzzer/config"]
        assert buzzer["command_topic"] == f"unifi-announcer/chime/{name}/play"
        assert json.loads(buzzer["payload_press"]) == {"buzzer": True, "target": name}

    state_topics = {call.args[0] for call in client.publish.await_args_list
                    if call.args[0].startswith("unifi-announcer/chime/")}
    assert "unifi-announcer/chime/kitchen/queue_depth" in state_topics
    assert "unifi-announcer/chime/kitchen/direct_health" in state_topics
