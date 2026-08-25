#!/usr/bin/env python3
"""Benchmark preset playback latency. WARNING: this produces audible sound."""
from __future__ import annotations

import argparse
import json
import math
import time
import httpx


def percentile(values: list[float], pct: int) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("no samples")
    return ordered[max(0, math.ceil(len(ordered) * pct / 100) - 1)]


def summarize(values: list[float]) -> dict:
    return {"count": len(values), "min": min(values), "p50": percentile(values, 50), "p90": percentile(values, 90), "p95": percentile(values, 95), "p99": percentile(values, 99), "max": max(values)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--api-key")
    parser.add_argument("--confirm-sound", action="store_true", help="acknowledge each request plays the physical chime")
    args = parser.parse_args()
    if not args.confirm_sound:
        parser.error("benchmark produces audible sound; rerun with --confirm-sound after warning occupants")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    samples = []
    with httpx.Client(base_url=args.url, headers=headers, timeout=30) as client:
        for _ in range(args.count):
            started = time.perf_counter_ns()
            response = client.post(f"/presets/{args.preset}/play")
            response.raise_for_status()
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
    print(json.dumps(summarize(samples), indent=2))


if __name__ == "__main__":
    main()
