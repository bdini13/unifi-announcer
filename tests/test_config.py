import pytest


def test_chime_config_only_recovers_from_expected_json_errors(main_module, monkeypatch):
    monkeypatch.setattr(
        main_module.json, "loads", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        main_module._load_chime_runtimes()


def test_track_registry_load_does_not_hide_programming_errors(
    main_module, monkeypatch, tmp_path
):
    path = tmp_path / "track_registry.json"
    path.write_text("{}")
    registry = main_module.TrackRegistry()
    registry._path = str(path)
    monkeypatch.setattr(
        main_module.json, "load", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        registry.load()
