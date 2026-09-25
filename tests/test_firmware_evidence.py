"""Exact-evidence compatibility regressions for runtime Smart Chime firmware."""
from __future__ import annotations

from app.diagnostics import build_support_bundle


def _bundle(runtime_version: str):
    return build_support_bundle(
        release={
            "version": "candidate",
            "git_sha": "abc123",
            "tested_firmware": {"smart_chime": ["1.7.20"]},
        },
        health={"status": "ok", "components": {}},
        target_catalog={
            "targets": [{
                "name": "private-kitchen-name",
                "id": "private-device-id",
                "type": "chime",
                "queue_depth": 0,
                "capabilities": {"announce": True},
            }],
            "groups": [],
        },
        slot_status={"ready": True, "slot_count": 2},
        cache_stats={},
        metrics={},
        runtime_firmware={"private-kitchen-name": runtime_version},
    )


def test_exact_runtime_firmware_matches_physical_evidence_without_name_leak():
    bundle = _bundle("v1.7.20")
    target = bundle["targets"][0]

    assert target["target"] == "target_1"
    assert target["firmware"] == "v1.7.20"
    assert target["firmware_evidence"] == "physically_tested_exact"
    assert "private-kitchen-name" not in str(bundle)
    assert not any(
        warning["code"] == "chime_firmware_not_physically_tested_exact"
        for warning in bundle["compatibility"]["warnings"]
    )


def test_newer_runtime_firmware_is_not_inferred_compatible():
    bundle = _bundle("1.8.0")
    target = bundle["targets"][0]

    assert target["firmware_evidence"] == "not_physically_tested_exact"
    warning = next(
        item
        for item in bundle["compatibility"]["warnings"]
        if item["code"] == "chime_firmware_not_physically_tested_exact"
    )
    assert warning == {
        "code": "chime_firmware_not_physically_tested_exact",
        "severity": "warning",
        "target": "target_1",
    }
