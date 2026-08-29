import importlib
import sys

import pytest


@pytest.fixture
def main_module(monkeypatch, tmp_path):
    """Import the app with inert, documentation-only network values."""
    monkeypatch.setenv("EVENTS_ENABLED", "false")
    monkeypatch.setenv("TTS_ENGINE", "none")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("UNIFI_HOST", "https://unifi.invalid")
    monkeypatch.setenv("CHIME_ID", "chime-fixture")
    monkeypatch.setenv("CHIME_DIRECT_IP", "192.0.2.10")
    monkeypatch.setenv("CHIME_DIRECT_PASSWORD", "test-placeholder")
    monkeypatch.setenv("APP_API_KEY", "configured-test-key")
    sys.modules.pop("app.main", None)
    module = importlib.import_module("app.main")
    yield module
