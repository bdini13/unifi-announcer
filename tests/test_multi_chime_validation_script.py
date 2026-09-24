"""Contract tests for the audible multi-Chime validation harness."""
from __future__ import annotations

import pytest

from scripts.validate_multi_chime import build_phases, validate_catalog


def _catalog():
    return {
        "schema_version": 1,
        "targets": [
            {
                "name": "chime_a",
                "id": "private-id-a",
                "type": "chime",
                "capabilities": {"announce": True},
            },
            {
                "name": "chime_b",
                "id": "private-id-b",
                "type": "chime",
                "capabilities": {"announce": True},
            },
        ],
        "groups": [
            {
                "name": "two_chimes",
                "members": ["chime_a", "chime_b"],
                "capabilities": {"announce": True},
            }
        ],
    }


def test_multi_chime_harness_preflight_requires_two_real_chime_members():
    validate_catalog(_catalog(), "chime_a", "chime_b", "two_chimes")

    with pytest.raises(RuntimeError, match="must be different"):
        validate_catalog(_catalog(), "chime_a", "chime_a", "two_chimes")

    wrong_type = _catalog()
    wrong_type["targets"][1]["type"] = "camera"
    with pytest.raises(RuntimeError, match="must be a Smart Chime"):
        validate_catalog(wrong_type, "chime_a", "chime_b", "two_chimes")

    missing_member = _catalog()
    missing_member["groups"][0]["members"] = ["chime_a"]
    with pytest.raises(RuntimeError, match="must contain both"):
        validate_catalog(missing_member, "chime_a", "chime_b", "two_chimes")


def test_multi_chime_spoken_phases_are_deterministic_and_repeat_group_content():
    phases = build_phases("private-a", "private-b", "private-group", "123456")

    assert [phase.name for phase in phases] == [
        "target_a_single",
        "target_b_single",
        "group_single",
        "group_repeat_same_content",
    ]
    assert phases[2].text == phases[3].text
    assert phases[0].target_alias == "target_a"
    assert phases[1].target_alias == "target_b"
    assert phases[2].target_alias == "group"
