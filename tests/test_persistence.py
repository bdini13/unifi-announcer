import json
import os

import pytest

from app.persistence import atomic_json


def test_atomic_json_flushes_file_before_replace_and_directory_after(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    events = []
    real_replace = os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: events.append("fsync"))
    def replace(source, destination):
        assert json.loads(source.read_text()) == {"ready": False}
        events.append("replace")
        real_replace(source, destination)
    monkeypatch.setattr(os, "replace", replace)
    atomic_json(path, {"ready": False})
    assert events == ["fsync", "replace", "fsync"]
    assert json.loads(path.read_text()) == {"ready": False}
    assert list(tmp_path.iterdir()) == [path]


def test_failed_file_sync_keeps_previous_state_and_removes_temporary(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"old": true}')
    def fail(_):
        raise OSError("disk failure")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="disk failure"):
        atomic_json(path, {"new": True})
    assert json.loads(path.read_text()) == {"old": True}
    assert list(tmp_path.iterdir()) == [path]
