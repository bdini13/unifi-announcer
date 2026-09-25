"""Regression coverage for the shareable diagnostic support bundle."""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.diagnostics import build_support_bundle


def _sample_bundle():
    return build_support_bundle(
        release={
            "version": "2.2.0-beta.5",
            "git_sha": "abc123",
            "tested_firmware": {
                "protect": ["7.2.105"],
                "smart_chime": ["1.7.20"],
            },
            "protocols": {
                "protect_rest": "production_private_api",
                "direct_device_http": "production_owned_tts_slot_overwrite",
            },
            "private_url": "https://controller.local",
        },
        health={
            "status": "degraded",
            "components": {
                "protect": {"status": "ok", "detail": "private detail"},
                "direct_device": {
                    "status": "degraded",
                    "detail": "192.168.10.55 secret-device-id",
                },
            },
        },
        target_catalog={
            "targets": [
                {
                    "name": "Kitchen Chime",
                    "id": "secret-chime-uuid",
                    "type": "chime",
                    "queue_depth": 2,
                    "capabilities": {"announce": True, "buzzer": True},
                },
                {
                    "name": "Family Room Camera",
                    "id": "secret-camera-uuid",
                    "type": "camera",
                    "queue_depth": 0,
                    "status": "available",
                    "model": "UVC G4 Instant",
                    "compatibility": "experimental_opt_in",
                    "capabilities": {"announce": True, "volume": False},
                },
            ],
            "groups": [
                {
                    "name": "Downstairs Private Group",
                    "members": ["Kitchen Chime", "Family Room Camera"],
                    "capabilities": {"announce": True, "buzzer": False},
                }
            ],
        },
        slot_status={
            "ready": True,
            "mode": "two_slot_overwrite",
            "slot_count": 2,
            "busy_slots": [2],
            "legacy_orphans": 1,
            "last_error": "RuntimeError: secret-chime-uuid at 192.168.10.55",
            "slots": {
                "1": {
                    "protect_name": "UA-TTS-private",
                    "protect_ringtone_id": "secret-ringtone-id",
                    "bindings": {
                        "secret-chime-uuid": {
                            "device_slot": 4,
                            "filename": "private-file.mp3",
                        }
                    },
                },
                "2": {
                    "bindings": {
                        "secret-chime-uuid": {
                            "device_slot": 5,
                            "filename": "another-private-file.mp3",
                        }
                    },
                },
            },
            "content_reuse": {
                "trusted_bindings": 1,
                "assignments": {
                    "1": {
                        "secret-chime-uuid": {
                            "trusted": True,
                            "content_key_prefix": "deadbeefcafe",
                            "filename": "private-file.mp3",
                        }
                    }
                },
                "last_prepare": {
                    "slot_prepare_ms": 150.5,
                    "slot_sync_ms": 20.0,
                    "logical_slot": 1,
                    "target_count": 1,
                    "content_hit": True,
                    "content_md5_prefix": "deadbeefcafe",
                    "content_size": 12345,
                },
            },
        },
        cache_stats={
            "files": 12,
            "bytes": 4000,
            "evicted": 1,
            "max_files": 256,
            "max_bytes": 268435456,
            "cache_path": "/private/cache/path",
        },
        metrics={
            "counters": {
                "dispatch_played": 5,
                "tts_slot_sync_timeouts": 1,
                "bad_non_numeric": "secret-token",
            },
            "histograms": {
                "announce_total_ms": {
                    "count": 2,
                    "sum": 100.0,
                    "min": 40.0,
                    "max": 60.0,
                    "avg": 50.0,
                },
                "camera_prepare_ms": {
                    "count": 1,
                    "sum": 31.0,
                    "min": 31.0,
                    "max": 31.0,
                    "avg": 31.0,
                },
                "caller_controlled_secret_stage": {
                    "count": 1,
                    "sum": 1.0,
                    "min": 1.0,
                    "max": 1.0,
                    "avg": 1.0,
                },
            },
        },
        media_limits=SimpleNamespace(
            max_input_bytes=4194304,
            max_output_bytes=1048576,
            max_duration_seconds=30.0,
            normalize_timeout_seconds=15.0,
        ),
    )


def test_support_bundle_pseudonymizes_topology_and_omits_sensitive_values():
    bundle = _sample_bundle()
    encoded = json.dumps(bundle, sort_keys=True)

    for secret in (
        "Kitchen Chime",
        "Family Room Camera",
        "Downstairs Private Group",
        "secret-chime-uuid",
        "secret-camera-uuid",
        "secret-ringtone-id",
        "192.168.10.55",
        "private-file.mp3",
        "another-private-file.mp3",
        "deadbeefcafe",
        "https://controller.local",
        "/private/cache/path",
        "secret-token",
    ):
        assert secret not in encoded

    assert bundle["targets"][0]["target"] == "target_1"
    assert bundle["targets"][1]["target"] == "target_2"
    assert bundle["groups"] == [
        {
            "group": "group_1",
            "members": ["target_1", "target_2"],
            "capabilities": {"announce": True, "buzzer": False},
        }
    ]
    assert bundle["redaction"]["device_identifiers"] == "omitted"


def test_support_bundle_retains_evidence_and_numeric_operational_state():
    bundle = _sample_bundle()

    assert bundle["release"]["version"] == "2.2.0-beta.5"
    assert bundle["release"]["git_sha"] == "abc123"
    assert bundle["release"]["tested_firmware"] == {
        "protect": ["7.2.105"],
        "smart_chime": ["1.7.20"],
    }
    assert bundle["targets"][0]["queue_depth"] == 2
    assert bundle["targets"][1]["model"] == "UVC G4 Instant"
    assert bundle["dynamic_tts"]["slot_count"] == 2
    assert bundle["dynamic_tts"]["slots"] == [
        {"logical_slot": 1, "binding_count": 1, "trusted_binding_count": 1},
        {"logical_slot": 2, "binding_count": 1, "trusted_binding_count": 0},
    ]
    assert bundle["dynamic_tts"]["last_prepare"] == {
        "slot_sync_ms": 20.0,
        "slot_prepare_ms": 150.5,
        "logical_slot": 1,
        "target_count": 1,
        "content_hit": True,
        "content_size": 12345,
    }
    assert bundle["metrics"]["counters"]["dispatch_played"] == 5
    assert "bad_non_numeric" not in bundle["metrics"]["counters"]
    assert bundle["metrics"]["latency_stages"]["camera_prepare_ms"]["avg"] == 31.0
    assert "caller_controlled_secret_stage" not in bundle["metrics"]["latency_stages"]
    assert bundle["media_ingestion"]["max_input_bytes"] == 4194304


def test_support_bundle_warnings_are_capability_and_state_based():
    warnings = _sample_bundle()["compatibility"]["warnings"]

    assert {warning["code"] for warning in warnings} == {
        "service_health_degraded",
        "legacy_orphans_present",
        "camera_experimental_opt_in",
    }
    camera_warning = next(
        warning for warning in warnings
        if warning["code"] == "camera_experimental_opt_in"
    )
    assert camera_warning["target"] == "target_2"


def test_support_bundle_warns_when_build_slots_or_camera_evidence_are_unproven():
    bundle = build_support_bundle(
        release={"version": "x", "git_sha": "unknown"},
        health={"status": "ok", "components": {}},
        target_catalog={
            "targets": [{
                "name": "camera",
                "id": "private-id",
                "type": "camera",
                "status": "available",
                "capabilities": {"announce": False},
            }],
            "groups": [],
        },
        slot_status={"ready": False, "slot_count": 2},
        cache_stats={},
        metrics={},
    )

    assert {warning["code"] for warning in bundle["compatibility"]["warnings"]} == {
        "build_revision_unknown",
        "dynamic_tts_not_ready",
        "camera_compatibility_unproven",
    }
