"""Compiled in-memory rules for the Protect realtime fast path."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Collection


@dataclass(frozen=True)
class RuleAction:
    preset: str
    volume: int | None = None
    repeat_times: int = 1
    priority: int = 10

from app.dispatcher import AnnouncementCommand

log = logging.getLogger("unifi-announcer")


class RulesEngine:
    def __init__(self, dispatch: Callable[[AnnouncementCommand], Awaitable[Any]] | None = None,
                 metrics: Any = None) -> None:
        self.rules: list[dict[str, Any]] = []
        self.disabled: list[dict[str, str]] = []
        self._last_fired: dict[str, float] = {}
        self._path = os.path.join(os.getenv("DATA_DIR", "/data"), "rules.json")
        self.hits = 0
        self.misses = 0
        self.loaded_at: float | None = None
        self._dispatch = dispatch
        self._metrics = metrics
        self._presets: set[str] = set()
        self._targets: set[str] = set()

    def bind(self, dispatch: Callable[[AnnouncementCommand], Awaitable[Any]], metrics: Any) -> None:
        self._dispatch = dispatch
        self._metrics = metrics

    def load(self, *, presets: Collection[str] | None = None,
             targets: Collection[str] | None = None) -> dict[str, Any]:
        if presets is not None:
            self._presets = set(presets)
        if targets is not None:
            self._targets = set(targets)
        try:
            with open(self._path) as source:
                raw = json.load(source)
        except FileNotFoundError:
            raw = []
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            log.warning("rules load failed: %s", exc)
            raw = []
        if not isinstance(raw, list):
            log.warning("rules load failed: top-level value must be a list")
            raw = []
        active: list[dict[str, Any]] = []
        disabled: list[dict[str, str]] = []
        for index, rule in enumerate(raw):
            reason = self._invalid_reason(rule)
            if reason:
                name = rule.get("name", f"rule-{index}") if isinstance(rule, dict) else f"rule-{index}"
                disabled.append({"name": str(name), "reason": reason})
                log.warning("disabled rule %s: %s", name, reason)
            else:
                active.append(rule)
        self.rules = active
        self.disabled = disabled
        self.loaded_at = time.time()
        return self.status()

    def _invalid_reason(self, rule: Any) -> str | None:
        if not isinstance(rule, dict) or not isinstance(rule.get("name"), str):
            return "name is required"
        when = rule.get("when")
        if not isinstance(when, dict):
            return "when must be an object"
        unsupported = set(when) - {"event", "model", "camera"}
        if unsupported:
            return f"unsupported when field: {sorted(unsupported)[0]}"
        event = when.get("event")
        if event != "doorbell_ring":
            return f"unsupported event: {event}"
        model = when.get("model")
        if model is not None and model != "camera":
            return f"unsupported model: {model}"
        camera = when.get("camera")
        if camera is not None and (not isinstance(camera, str) or not camera.strip()):
            return "camera must be a string"
        then = rule.get("then")
        if not isinstance(then, dict):
            return "then is required"
        preset = then.get("preset")
        if not isinstance(preset, str) or not preset:
            return "preset is required"
        if self._presets and preset not in self._presets:
            return f"unknown preset: {preset}"
        target = then.get("target")
        if target is not None and (not isinstance(target, str) or not target.strip()):
            return "target must be a nonempty string"
        if target is not None and self._targets and target not in self._targets:
            return f"unknown target: {target}"
        volume = then.get("volume")
        if volume is not None and (not isinstance(volume, int) or isinstance(volume, bool)
                                   or not 0 <= volume <= 100):
            return "volume must be an integer from 0..100"
        repeat = then.get("repeat", 1)
        if (not isinstance(repeat, int) or isinstance(repeat, bool)
                or not 1 <= repeat <= 6):
            return "repeat must be an integer from 1..6"
        priority = then.get("priority", 10)
        if (not isinstance(priority, int) or isinstance(priority, bool)
                or not 0 <= priority <= 100):
            return "priority must be an integer from 0..100"
        cooldown = rule.get("cooldown_ms", 250)
        if (not isinstance(cooldown, (int, float)) or isinstance(cooldown, bool)
                or cooldown < 0):
            return "cooldown_ms must be a nonnegative number"
        return None

    def status(self) -> dict[str, Any]:
        return {
            "active": len(self.rules),
            "disabled": len(self.disabled),
            "disabled_rules": list(self.disabled),
            "hits": self.hits,
            "misses": self.misses,
            "loaded_at": self.loaded_at,
        }

    async def evaluate(self, event: dict[str, Any]) -> None:
        for rule in self.rules:
            when = rule.get("when", {})
            expected_event = when.get("event")
            actual_event = event.get("event")
            legacy_ring = (actual_event is None and expected_event == "doorbell_ring"
                           and event.get("is_event") and event.get("action") == "add"
                           and event.get("model") == "camera")
            if expected_event and expected_event != actual_event and not legacy_ring:
                continue
            if when.get("model") and when["model"] != event.get("model"):
                continue
            if when.get("camera") and when["camera"] != event.get("camera_id"):
                continue
            now = time.monotonic()
            cooldown = rule.get("cooldown_ms", 250) / 1000.0
            if now - self._last_fired.get(rule["name"], 0) < cooldown:
                self.misses += 1
                continue
            self._last_fired[rule["name"]] = now
            then = rule["then"]
            cooldown_ms = int(rule.get("cooldown_ms", 250))
            self.hits += 1
            dispatch = self._dispatch
            if dispatch is None:
                from app import main
                dispatch = main.dispatcher.dispatch
            try:
                result = await dispatch(AnnouncementCommand(
                    action="play_preset", preset=then["preset"], volume=then.get("volume"),
                    repeat_times=then.get("repeat", 1), priority=then.get("priority", 10),
                    target=then.get("target"), dedupe_key=f"rule:{rule['name']}",
                    dedupe_window_ms=cooldown_ms, source="rule"))
                metrics = self._metrics
                if metrics is None:
                    from app import main
                    metrics = main.metrics
                metrics.inc("rules_fired")
                if getattr(result, "disposition", None) == "suppressed":
                    metrics.inc("rules_suppressed")
            except Exception as exc:
                log.warning("rule action failed: %s", exc)
