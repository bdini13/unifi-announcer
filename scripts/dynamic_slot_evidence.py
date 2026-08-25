#!/usr/bin/env python3
"""Summarize a bounded dynamic-slot retest evidence JSON file offline."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Iterable

_PLAY_START = re.compile(r"playSpeaker\s+start", re.IGNORECASE)
_MAPPING_FAILURE = re.compile(
    r"(?:playSpeaker|track\[?7\]?|load|UCP4|ringtone|mapping).{0,120}"
    r"(?:fail|error|invalid|not found)",
    re.IGNORECASE,
)


def added_occurrences(before: Iterable[str], after: Iterable[str]) -> list[str]:
    """Return new line occurrences while preserving order and duplicates."""
    remaining = Counter(before)
    added = []
    for line in after:
        if remaining[line]:
            remaining[line] -= 1
        else:
            added.append(line)
    return added


def staged_slot_matches(tracks: list[dict], *, slot: int, md5: str, size: int) -> bool:
    """Require an exact one-based slot, MD5, and byte-size match."""
    if slot < 1 or slot > len(tracks):
        return False
    track = tracks[slot - 1]
    return track.get("md5") == md5 and track.get("size") == size


def staged_device_proof_matches(proof: dict, tone: dict) -> bool:
    """Verify direct-device route/length/save evidence against local MP3 hashes."""
    return (
        proof.get("logged_save_track") == 7
        and proof.get("logged_bytes") == tone.get("size")
        and proof.get("local_mp3_md5") == tone.get("md5")
        and proof.get("local_mp3_sha256") == tone.get("sha256")
        and proof.get("logged_route", "").startswith("/api/uploadRingtone/7/")
    )


def classify_verdict(play_http_status: int | None, new_log_lines: Iterable[str]) -> str:
    """Apply the experiment's validated/rejected/inconclusive categories."""
    lines = list(new_log_lines)
    if play_http_status not in (200, 204):
        return "rejected" if play_http_status is not None else "inconclusive"
    if any(_MAPPING_FAILURE.search(line) for line in lines):
        return "rejected"
    if any(_PLAY_START.search(line) for line in lines):
        return "validated"
    return "inconclusive"


def summarize(evidence: dict) -> dict:
    tone = evidence.get("test_tone") or {}
    staged = evidence.get("staged_chime_retry") or evidence.get("staged_chime") or {}
    play = evidence.get("play") or {}
    postplay = evidence.get("postplay_support") or {}
    proof = evidence.get("staged_device_proof") or {}
    tracks = staged.get("speakerTrackList") or []
    return {
        "recorded_verdict": evidence.get("verdict"),
        "derived_verdict": classify_verdict(play.get("http_status"), postplay.get("new_relevant") or []),
        "staged_device_proof_exact": staged_device_proof_matches(proof, tone),
        "protect_metadata_stale": proof.get("protect_metadata_stale"),
        "staged_slot7_exact": staged_slot_matches(
            tracks, slot=7, md5=tone.get("md5", ""), size=tone.get("size", -1)
        ),
        "direct_overwrite_http": (evidence.get("direct_overwrite") or {}).get("http_status"),
        "direct_overwrite_ms": (evidence.get("direct_overwrite") or {}).get("elapsed_ms"),
        "play_http": play.get("http_status"),
        "play_ms": play.get("elapsed_ms"),
        "restored_verified": evidence.get("restored_verified"),
        "test_error": evidence.get("test_error"),
        "new_stage_log_lines": (evidence.get("staged_support") or {}).get("new_relevant") or [],
        "new_postplay_log_lines": postplay.get("new_relevant") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="sanitized retest evidence JSON")
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text())
    print(json.dumps(summarize(evidence), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
