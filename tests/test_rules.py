import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.rules.engine import RulesEngine


@pytest.mark.asyncio
async def test_rule_resolves_existing_preset_without_creating(main_module, monkeypatch):
    engine = main_module.RulesEngine()
    engine.rules = [{
        "name": "fixture-ring-rule",
        "when": {"event": "doorbell_ring", "model": "camera"},
        "then": {"preset": "fixture-tone", "volume": 35},
        "cooldown_ms": 0,
    }]
    resolve = AsyncMock(return_value="ringtone-fixture-1")
    create = AsyncMock(side_effect=AssertionError("rules must not create presets"))
    play = AsyncMock(return_value={"played": True})
    monkeypatch.setattr(main_module, "resolve_preset_id", resolve, raising=False)
    monkeypatch.setattr(main_module, "create_or_update_preset", create, raising=False)
    monkeypatch.setattr(main_module.protect, "play", play)

    await engine.evaluate({
        "action": "add", "model": "camera", "is_event": True
    })

    resolve.assert_awaited_once_with("fixture-tone")
    create.assert_not_awaited()
    play.assert_awaited_once_with("ringtone-fixture-1", volume=35, repeat_times=1,
                                  chime_id="chime-fixture")


@pytest.mark.asyncio
async def test_rule_missing_preset_never_synthesizes_or_uploads(main_module, monkeypatch):
    engine = main_module.RulesEngine()
    engine.rules = [{
        "name": "missing-fixture-rule",
        "when": {"event": "doorbell_ring", "model": "camera"},
        "then": {"preset": "missing-fixture-tone"},
        "cooldown_ms": 0,
    }]
    monkeypatch.setattr(
        main_module, "resolve_preset_id",
        AsyncMock(side_effect=KeyError("preset not uploaded")),
    )
    synthesize = AsyncMock(side_effect=AssertionError("must not synthesize"))
    upload = AsyncMock(side_effect=AssertionError("must not upload"))
    play = AsyncMock()
    monkeypatch.setattr(main_module, "synthesize_tts_cached", synthesize)
    monkeypatch.setattr(main_module.chime_client, "upload_ringtone", upload)
    monkeypatch.setattr(main_module.protect, "play", play)

    await engine.evaluate({
        "action": "add", "model": "camera", "is_event": True
    })

    synthesize.assert_not_awaited()
    upload.assert_not_awaited()
    play.assert_not_awaited()


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"when": "doorbell_ring"}, "when must be an object"),
        ({"when": {"event": "motion"}}, "unsupported event: motion"),
        ({"when": {"event": "doorbell_ring", "camera": 42}}, "camera must be a string"),
        ({"when": {"event": "doorbell_ring", "unexpected": "x"}}, "unsupported when field: unexpected"),
        ({"then": {"preset": "tone", "repeat": 0}}, "repeat must be an integer from 1..6"),
        ({"then": {"preset": "tone", "repeat": "2"}}, "repeat must be an integer from 1..6"),
        ({"cooldown_ms": -1}, "cooldown_ms must be a nonnegative number"),
        ({"cooldown_ms": "250"}, "cooldown_ms must be a nonnegative number"),
        ({"then": {"preset": "tone", "target": 7}}, "target must be a nonempty string"),
        ({"then": {"preset": "tone", "target": "missing"}}, "unknown target: missing"),
        ({"then": {"preset": "tone", "volume": True}}, "volume must be an integer from 0..100"),
        ({"then": {"preset": "tone", "priority": 101}}, "priority must be an integer from 0..100"),
    ],
)
def test_malformed_rules_are_disabled_with_clear_reason(tmp_path, patch, reason):
    valid = {
        "name": "valid", "when": {"event": "doorbell_ring", "camera": "front"},
        "then": {"preset": "tone", "target": "downstairs", "repeat": 1,
                 "volume": 25, "priority": 10},
        "cooldown_ms": 0,
    }
    malformed = {**valid, "name": "malformed", **patch}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps([valid, malformed]))
    engine = RulesEngine()
    engine._path = str(path)

    engine.load(presets={"tone"}, targets={"downstairs"})

    assert [rule["name"] for rule in engine.rules] == ["valid"]
    assert engine.status()["disabled_rules"] == [{"name": "malformed", "reason": reason}]


def test_rules_compile_disables_invalid_actions_with_status(tmp_path, caplog):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps([
        {"name": "valid", "when": {"event": "doorbell_ring"},
         "then": {"preset": "tone", "target": "downstairs", "volume": 25,
                  "priority": 10}},
        {"name": "missing-preset", "when": {"event": "doorbell_ring"},
         "then": {"preset": "absent"}},
        {"name": "bad-volume", "when": {"event": "doorbell_ring"},
         "then": {"preset": "tone", "volume": 101}},
    ]))
    engine = RulesEngine()
    engine._path = str(path)

    engine.load(presets={"tone"}, targets={"downstairs"})

    assert [rule["name"] for rule in engine.rules] == ["valid"]
    assert engine.status()["disabled"] == 2
    assert "disabled rule" in caplog.text


@pytest.mark.asyncio
async def test_rules_status_is_read_only_and_reload_is_protected(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "APP_API_KEY", "fixture-key")
    main_module._rules_engine.rules = [{"name": "active"}]
    main_module._rules_engine.disabled = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        status = await client.get("/rules/status", headers={"X-API-Key": "fixture-key"})
        forbidden = await client.post("/rules/reload")

    assert status.status_code == 200
    assert status.json()["active"] == 1
    assert forbidden.status_code == 403
