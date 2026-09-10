#!/usr/bin/env python3
"""Run the audible multi-Chime validation sequence.

WARNING: every playback phase produces physical sound. The script validates API
routing/ordering only; a human must record whether the expected device(s) were
actually heard.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class Phase:
    name: str
    target_alias: str
    target: str
    text: str


def _suffix() -> str:
    return datetime.now(timezone.utc).strftime("%H%M%S")


def build_phases(target_a: str, target_b: str, group: str, suffix: str) -> list[Phase]:
    """Build deterministic spoken phases with no device IDs in the report."""
    return [
        Phase(
            "target_a_single",
            "target_a",
            target_a,
            f"Multi chime test A {suffix}",
        ),
        Phase(
            "target_b_single",
            "target_b",
            target_b,
            f"Multi chime test B {suffix}",
        ),
        Phase(
            "group_single",
            "group",
            group,
            f"Multi chime group test {suffix}",
        ),
        Phase(
            "group_repeat_same_content",
            "group",
            group,
            f"Multi chime group test {suffix}",
        ),
    ]


def _catalog_indexes(payload: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict]]:
    if payload.get("schema_version") != 1:
        raise RuntimeError("/targets did not return schema_version=1")
    targets = {
        str(item.get("name")): item
        for item in payload.get("targets", [])
        if isinstance(item, dict) and item.get("name")
    }
    groups = {
        str(item.get("name")): item
        for item in payload.get("groups", [])
        if isinstance(item, dict) and item.get("name")
    }
    return targets, groups


def validate_catalog(
    payload: dict[str, Any], target_a: str, target_b: str, group: str
) -> None:
    """Fail before sound unless two distinct Chimes and the requested group exist."""
    if target_a == target_b:
        raise RuntimeError("target A and target B must be different configured targets")
    targets, groups = _catalog_indexes(payload)
    for label, name in (("target A", target_a), ("target B", target_b)):
        item = targets.get(name)
        if item is None:
            raise RuntimeError(f"{label} is not present in /targets")
        if item.get("type") != "chime":
            raise RuntimeError(f"{label} must be a Smart Chime target")
        if not (item.get("capabilities") or {}).get("announce"):
            raise RuntimeError(f"{label} does not currently advertise announce capability")

    group_item = groups.get(group)
    if group_item is None:
        raise RuntimeError("requested group is not present in /targets")
    members = group_item.get("members") or []
    if target_a not in members or target_b not in members:
        raise RuntimeError("requested group must contain both validation Chimes")
    if not (group_item.get("capabilities") or {}).get("announce"):
        raise RuntimeError("requested group does not currently advertise announce capability")


async def _announce(
    client: httpx.AsyncClient, phase: str, target_alias: str, target: str, text: str
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    response = await client.post(
        "/announce",
        json={"text": text, "target": target, "priority": 80},
    )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    disposition = None
    try:
        payload = response.json()
        if isinstance(payload, dict):
            disposition = payload.get("disposition")
    except ValueError:
        pass
    return {
        "phase": phase,
        "target": target_alias,
        "http_status": response.status_code,
        "disposition": disposition or "unknown",
        "request_ms": round(elapsed_ms, 2),
    }


async def _announce_after(
    delay: float,
    client: httpx.AsyncClient,
    phase: str,
    target_alias: str,
    target: str,
    text: str,
) -> dict[str, Any]:
    """Stagger one concurrent submission enough to make enqueue order explicit."""
    await asyncio.sleep(delay)
    return await _announce(client, phase, target_alias, target, text)


def _require_played(result: dict[str, Any]) -> None:
    if result["http_status"] != 200 or result["disposition"] != "played":
        raise RuntimeError(
            f"phase {result['phase']} did not fully play: "
            f"HTTP {result['http_status']} / {result['disposition']}"
        )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.getenv("UNIFI_ANNOUNCER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "set UNIFI_ANNOUNCER_API_KEY in the environment; do not pass secrets on the command line"
        )
    base_url = args.url.rstrip("/")
    headers = {"X-API-Key": api_key}
    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": "scripts/validate_multi_chime.py",
        "targets": {"target_a": "pseudonymized", "target_b": "pseudonymized"},
        "group": "pseudonymized",
        "results": [],
        "acoustic_observation": "REQUIRES_HUMAN_CONFIRMATION",
    }

    async with httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=httpx.Timeout(45.0),
    ) as client:
        target_response = await client.get("/targets")
        target_response.raise_for_status()
        catalog = target_response.json()
        validate_catalog(catalog, args.target_a, args.target_b, args.group)

        suffix = _suffix()
        for phase in build_phases(args.target_a, args.target_b, args.group, suffix):
            result = await _announce(
                client, phase.name, phase.target_alias, phase.target, phase.text
            )
            report["results"].append(result)
            _require_played(result)
            await asyncio.sleep(args.pause)

        # Separate physical Chimes should be able to progress independently.
        different = await asyncio.gather(
            _announce(
                client,
                "different_targets_concurrent_a",
                "target_a",
                args.target_a,
                f"Concurrent A {suffix}",
            ),
            _announce(
                client,
                "different_targets_concurrent_b",
                "target_b",
                args.target_b,
                f"Concurrent B {suffix}",
            ),
        )
        report["results"].extend(different)
        for result in different:
            _require_played(result)
        await asyncio.sleep(args.pause)

        # Same-target requests overlap in-flight, but the second enqueue is
        # deliberately delayed 50 ms so the acoustic order is deterministic.
        same_target = await asyncio.gather(
            _announce(
                client,
                "same_target_serialized_first",
                "target_a",
                args.target_a,
                f"Serialize first {suffix}",
            ),
            _announce_after(
                0.05,
                client,
                "same_target_serialized_second",
                "target_a",
                args.target_a,
                f"Serialize second {suffix}",
            ),
        )
        report["results"].extend(same_target)
        for result in same_target:
            _require_played(result)

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="UniFi Announcer base URL")
    parser.add_argument("--target-a", required=True, help="first configured Chime target name")
    parser.add_argument("--target-b", required=True, help="second configured Chime target name")
    parser.add_argument("--group", required=True, help="configured group containing both Chimes")
    parser.add_argument(
        "--pause",
        type=float,
        default=3.0,
        help="seconds between audible phases (default: 3)",
    )
    parser.add_argument(
        "--confirm-sound",
        action="store_true",
        help="acknowledge that this test intentionally produces repeated audible announcements",
    )
    args = parser.parse_args()
    if not args.confirm_sound:
        parser.error(
            "this validation produces repeated physical sound; warn occupants and rerun with --confirm-sound"
        )
    if args.pause < 0 or args.pause > 30:
        parser.error("--pause must be between 0 and 30 seconds")
    return args


def main() -> None:
    args = parse_args()
    try:
        report = asyncio.run(run(args))
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"validation aborted: {type(exc).__name__}: {exc}") from exc
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
