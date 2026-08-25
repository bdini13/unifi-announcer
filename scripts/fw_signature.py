#!/usr/bin/env python3
"""Offline Level-1 firmware string signatures with offset evidence.

Usage: python3 scripts/fw_signature.py <firmware.bin> > signature.json
This tool reports clues only. String presence does not prove handler behavior.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

KNOWN_HTTP_ENDPOINTS = [
    "/api/info", "/api/adopt", "/api/support",
    "/api/factoryResetWithoutWiFi", "/api/uploadRingtone/*",
]
UCP4_COMMANDS = [
    "playSpeaker", "playBuzzer", "setLEDState", "setTimezone",
    "updateFirmware", "factoryReset", "reboot", "changeUserPassword",
    "getInfo", "getAudioInfo", "getSupportInfo", "networkStatus",
    "changeUplinkAP",
]
FEATURE_FLAGS = ["hasWifi", "hasHttpsClientOTA", "supportCustomRingtone"]
WATCH_STRINGS = [
    "Disable ucp4_wss responst and trnafer to https client",
    "uploadRingtone",
    "remove ringtone",
]


def _strings(data: bytes, minimum: int = 4) -> list[tuple[int, str]]:
    pattern = re.compile(rb"[\x20-\x7e]{%d,}" % minimum)
    return [(match.start(), match.group().decode("ascii", "replace"))
            for match in pattern.finditer(data)]


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _literal_evidence(data: bytes, phrase: str, *, wildcard_suffix: bool = False) -> dict:
    needle = phrase.removesuffix("/*") if wildcard_suffix else phrase
    encoded = needle.encode()
    offsets = []
    start = 0
    while True:
        found = data.find(encoded, start)
        if found < 0:
            break
        offsets.append(found); start = found + 1
    return {"offsets": offsets,
            "contexts": [_context(data, offset, len(encoded)) for offset in offsets]}


def _phrase_evidence(strings: list[tuple[int, str]], phrase: str) -> dict:
    exact_offsets, exact_contexts = [], []
    normalized_offsets, normalized_contexts = [], []
    wanted = _normalized(phrase)
    for offset, text in strings:
        if phrase in text:
            exact_offsets.append(offset + text.index(phrase))
            exact_contexts.append(text[:240])
        elif wanted in _normalized(text):
            # Whitespace/case normalization loses a byte-perfect inner index;
            # report the containing printable-string offset and full context.
            normalized_offsets.append(offset)
            normalized_contexts.append(text[:240])
    if exact_offsets:
        return {"phrase": phrase, "match": "exact", "offsets": exact_offsets,
                "contexts": exact_contexts}
    if normalized_offsets:
        return {"phrase": phrase, "match": "normalized", "offsets": normalized_offsets,
                "contexts": normalized_contexts}
    return {"phrase": phrase, "match": "absent", "offsets": [], "contexts": []}


def _context(data: bytes, offset: int, size: int, radius: int = 48) -> str:
    start = max(0, offset - radius); end = min(len(data), offset + size + radius)
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in data[start:end])


def extract(binary_path: str) -> dict:
    data = Path(binary_path).read_bytes()
    strings = _strings(data)
    blob = "\n".join(text for _, text in strings)

    string_evidence = {}
    endpoints = []
    for endpoint in KNOWN_HTTP_ENDPOINTS:
        evidence = _literal_evidence(data, endpoint, wildcard_suffix=True)
        string_evidence[endpoint] = evidence
        if evidence["offsets"]:
            endpoints.append(endpoint)

    all_api = set(re.findall(r"/api/[a-zA-Z][a-zA-Z0-9_/*]*", blob))
    sdk_noise = {"/api/api_lib", "/api/api_msg", "/api/netbuf", "/api/sockets", "/api/tcpip"}
    known_literals = {item.removesuffix("/*") for item in KNOWN_HTTP_ENDPOINTS}
    extra_endpoints = sorted(all_api - known_literals - sdk_noise)

    for clue in UCP4_COMMANDS + FEATURE_FLAGS:
        string_evidence[clue] = _literal_evidence(data, clue)
    watch_evidence = [_phrase_evidence(strings, phrase) for phrase in WATCH_STRINGS]
    watch = {item["phrase"]: item["match"] != "absent" for item in watch_evidence}

    match = re.search(r"up[_-]chime[\w-]*-(\d+\.\d+\.\d+)", binary_path)
    flags = {flag: bool(string_evidence[flag]["offsets"]) for flag in FEATURE_FLAGS}
    commands = [command for command in UCP4_COMMANDS
                if string_evidence[command]["offsets"]]
    return {
        "analysis_level": "level1-strings",
        "binary": binary_path,
        "sha256": hashlib.sha256(data).hexdigest()[:16],
        "firmware_guess": match.group(1) if match else None,
        "http_endpoints_confirmed": endpoints,
        "http_endpoints_unknown": extra_endpoints,
        "ucp4_commands_present": commands,
        "feature_flags": flags,
        "watch_strings": watch,
        "watch_evidence": watch_evidence,
        "string_evidence": string_evidence,
        "evidence_caveat": "printable-string presence is a clue, not proof of handler behavior",
        "direct_write_safe": (set(endpoints) == set(KNOWN_HTTP_ENDPOINTS)
                              and not extra_endpoints
                              and flags.get("supportCustomRingtone", False)),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__); raise SystemExit(1)
    print(json.dumps(extract(sys.argv[1]), indent=2))
