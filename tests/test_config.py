import pytest

from app.playback.camera_hardening import load_validated_groups


def test_chime_config_only_recovers_from_expected_json_errors(main_module, monkeypatch):
    monkeypatch.setattr(
        main_module.json, "loads", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        main_module._load_chime_runtimes()


def test_camera_config_is_explicit_unique_and_not_an_implicit_default(
    main_module, monkeypatch
):
    monkeypatch.setenv(
        "CAMERAS_CONFIG",
        '[{"name":"family_room_camera","id":"camera-one"}]',
    )
    cameras = main_module._load_camera_runtimes()
    assert cameras["family_room_camera"].desc.kind == "camera"
    assert cameras["family_room_camera"].desc.camera_id == "camera-one"

    monkeypatch.setattr(main_module, "camera_runtimes", cameras)
    monkeypatch.setattr(
        main_module,
        "target_runtimes",
        {**main_module.chime_runtimes, **cameras},
    )
    assert all(target.desc.kind == "chime" for target in main_module.resolve_targets(None))
    assert main_module.resolve_targets("family_room_camera") == [
        cameras["family_room_camera"]
    ]


@pytest.mark.parametrize(
    "value",
    [
        "{}",
        '[{"name":"default","id":"camera-one"}]',
        '[{"name":"missing-id"}]',
        '[{"id":"missing-name"}]',
        '[{"name":"duplicate","id":"one"},{"name":"duplicate","id":"two"}]',
        '[{"name":"one","id":"duplicate"},{"name":"two","id":"duplicate"}]',
    ],
)
def test_camera_config_rejects_malformed_duplicate_or_reserved_entries(
    main_module, monkeypatch, value
):
    monkeypatch.setenv("CAMERAS_CONFIG", value)
    with pytest.raises(
        RuntimeError, match="CAMERAS_CONFIG|duplicate or reserved|duplicate camera target id"
    ):
        main_module._load_camera_runtimes()


def test_group_can_explicitly_mix_chime_and_camera_targets(main_module, monkeypatch):
    monkeypatch.setenv(
        "CAMERAS_CONFIG", '[{"name":"family_room_camera","id":"camera-one"}]'
    )
    cameras = main_module._load_camera_runtimes()
    target_runtimes = {**main_module.chime_runtimes, **cameras}
    groups = load_validated_groups(
        '{"mixed":["default","family_room_camera"]}',
        target_names=target_runtimes,
    )
    monkeypatch.setattr(main_module, "target_runtimes", target_runtimes)
    monkeypatch.setattr(main_module, "GROUPS", groups)
    resolved = main_module.resolve_targets("mixed")
    assert [target.desc.kind for target in resolved] == ["chime", "camera"]


def test_group_validation_rejects_unknown_member(main_module):
    with pytest.raises(RuntimeError, match="unknown target"):
        load_validated_groups(
            '{"mixed":["default","missing"]}',
            target_names=main_module.target_runtimes,
        )


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
