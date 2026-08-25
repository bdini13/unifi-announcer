import asyncio
import json
import struct
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.protect.events import parse_update_frame


def envelope(payload):
    encoded = json.dumps(payload).encode()
    return bytes((1, 1, 0, 0)) + struct.pack(">I", len(encoded)) + encoded


def test_parse_update_frame_accepts_action_and_data_arguments_regression():
    action = envelope({"action": "update", "modelKey": "camera", "id": "cam-1"})
    data = envelope({"modelKey": "camera", "id": "cam-1", "lastRing": 42})

    parsed_action, parsed_data = parse_update_frame(action, data)

    assert parsed_action["id"] == "cam-1"
    assert parsed_data["lastRing"] == 42


def test_event_stream_parser_callback_keeps_module_function_signature(main_module):
    raw = envelope({"action": "update", "modelKey": "camera", "id": "cam-1"})

    action, data = main_module.ProtectEventStream()._parse_frame(raw)

    assert action["id"] == "cam-1"
    assert data is None


def test_parse_update_frame_decodes_linked_zlib_json_frames():
    import zlib

    def compressed_envelope(payload):
        encoded = zlib.compress(json.dumps(payload).encode())
        return bytes((1, 1, 1, 0)) + struct.pack(">I", len(encoded)) + encoded

    action, data = parse_update_frame(
        compressed_envelope({"action": "update", "modelKey": "camera"})
        + compressed_envelope({"modelKey": "camera", "lastRing": 43})
    )

    assert action["action"] == "update"
    assert data["lastRing"] == 43


@pytest.mark.asyncio
async def test_camera_ring_emits_only_when_last_ring_advances(main_module, monkeypatch):
    stream = main_module.ProtectEventStream()
    normalized = AsyncMock()
    monkeypatch.setattr(main_module, "_on_normalized_event", normalized)
    monkeypatch.setattr(main_module.mqtt_bridge, "publish_event", AsyncMock())
    action = {"action": "update", "modelKey": "camera", "id": "cam-1"}

    await stream._handle(action, {"modelKey": "camera", "id": "cam-1", "lastRing": 100})
    await stream._handle(action, {"modelKey": "camera", "id": "cam-1", "lastRing": 100})
    await stream._handle(action, {"modelKey": "camera", "id": "cam-1", "lastRing": 101})
    await asyncio.gather(*stream._rule_tasks)

    assert [call.args[0]["event"] for call in normalized.await_args_list] == [
        "doorbell_ring", "doorbell_ring"
    ]


@pytest.mark.asyncio
async def test_rule_playback_does_not_block_subsequent_websocket_events(
    main_module, monkeypatch
):
    release = asyncio.Event()
    entered = []

    async def slow_rule(event):
        entered.append(event["last_ring"])
        await release.wait()

    monkeypatch.setattr(main_module, "_on_normalized_event", slow_rule)
    monkeypatch.setattr(main_module.mqtt_bridge, "publish_event", AsyncMock())
    stream = main_module.ProtectEventStream()
    action = {"action": "update", "modelKey": "camera", "id": "cam-1"}

    await asyncio.wait_for(stream._handle(
        action, {"modelKey": "camera", "id": "cam-1", "lastRing": 100}), timeout=0.05)
    await asyncio.wait_for(stream._handle(
        action, {"modelKey": "camera", "id": "cam-1", "lastRing": 101}), timeout=0.05)
    await asyncio.sleep(0)

    assert entered == [100, 101]
    assert len(stream._rule_tasks) == 2
    release.set()
    await asyncio.gather(*stream._rule_tasks)


@pytest.mark.asyncio
async def test_event_stream_stop_awaits_main_and_rule_tasks(main_module):
    stream = main_module.ProtectEventStream()

    async def pending():
        await asyncio.Event().wait()

    main_task = asyncio.create_task(pending())
    stream._task = main_task
    rule = asyncio.create_task(pending())
    stream._rule_tasks.add(rule)
    await asyncio.sleep(0)

    await stream.stop()

    assert main_task.done()
    assert stream._task is None
    assert rule.done()
    assert stream._rule_tasks == set()


@pytest.mark.asyncio
async def test_protect_ws_fixture_parses_camera_last_ring(main_module, monkeypatch):
    fixture_dir = Path(__file__).parent / "fixtures"
    json.loads((fixture_dir / "protect_ws_camera_last_ring.json").read_text())
    # Captured-like Protect action+data bytes with the real 8-byte envelope;
    # device IDs, update IDs, timestamps, addresses, and auth were sanitized.
    raw = (fixture_dir / "protect_ws_camera_last_ring.bin").read_bytes()
    action, data = main_module.ProtectEventStream._parse_frame(raw)

    stream = main_module.ProtectEventStream()
    monkeypatch.setattr(main_module.mqtt_bridge, "publish_event", AsyncMock())
    await stream._handle(action, data)
    await asyncio.sleep(0)

    assert action["modelKey"] == "camera"
    assert data["lastRing"] == 1700000000000
    assert stream.recent[-1]["model"] == "camera"
    assert stream.recent[-1]["last_ring"] == 1700000000000
