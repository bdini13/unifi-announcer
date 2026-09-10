"""Public manifest contract for native Home Assistant media ingestion."""
from __future__ import annotations

import json
from pathlib import Path


def test_home_assistant_manifest_declares_media_source_dependency():
    manifest = json.loads(
        Path("custom_components/unifi_announcer/manifest.json").read_text()
    )

    assert "media_source" in manifest.get("dependencies", [])
