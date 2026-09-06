import pytest

from app.playback.arbitration import ChimeDescriptor, ChimeRuntime


@pytest.mark.asyncio
async def test_legacy_chimes_contract_does_not_include_camera_targets(
    main_module, monkeypatch
):
    camera = ChimeRuntime(
        ChimeDescriptor(name="family_camera", kind="camera", camera_id="camera-one"),
        capability_state={"status": "available"},
    )
    monkeypatch.setattr(main_module, "camera_runtimes", {"family_camera": camera})
    monkeypatch.setattr(
        main_module,
        "target_runtimes",
        {**main_module.chime_runtimes, "family_camera": camera},
    )

    result = await main_module.list_chimes()

    assert set(result) == {"chimes", "groups"}
    assert all(item["id"] != "camera-one" for item in result["chimes"])


@pytest.mark.asyncio
async def test_target_catalog_reports_capabilities_and_intersects_mixed_groups(
    main_module, monkeypatch
):
    chime = ChimeRuntime(ChimeDescriptor(name="kitchen", chime_id="chime-one"))
    camera = ChimeRuntime(
        ChimeDescriptor(name="family_camera", kind="camera", camera_id="camera-one"),
        capability_state={
            "status": "available",
            "model": "UVC G3 Instant",
            "codec": "aac",
        },
    )
    monkeypatch.setattr(main_module, "chime_runtimes", {"kitchen": chime})
    monkeypatch.setattr(main_module, "camera_runtimes", {"family_camera": camera})
    monkeypatch.setattr(
        main_module,
        "target_runtimes",
        {"kitchen": chime, "family_camera": camera},
    )
    monkeypatch.setattr(
        main_module,
        "GROUPS",
        {"mixed": ["kitchen", "family_camera"]},
    )

    result = await main_module.list_targets()

    assert result["schema_version"] == 1
    by_name = {item["name"]: item for item in result["targets"]}
    assert by_name["kitchen"]["capabilities"]["buzzer"] is True
    assert by_name["family_camera"] == {
        "name": "family_camera",
        "id": "camera-one",
        "type": "camera",
        "queue_depth": 0,
        "capabilities": {
            "announce": True,
            "play_preset": False,
            "play_default": False,
            "buzzer": False,
            "volume": False,
            "repeat": True,
        },
        "status": "available",
        "model": "UVC G3 Instant",
    }
    assert result["groups"] == [
        {
            "name": "mixed",
            "type": "group",
            "members": ["kitchen", "family_camera"],
            "capabilities": {
                "announce": True,
                "play_preset": False,
                "play_default": False,
                "buzzer": False,
                "volume": False,
                "repeat": True,
            },
        }
    ]


@pytest.mark.asyncio
async def test_unavailable_camera_is_catalogued_but_not_rule_eligible(
    main_module, monkeypatch
):
    camera = ChimeRuntime(
        ChimeDescriptor(name="offline_camera", kind="camera", camera_id="camera-one"),
        capability_state={"status": "unavailable"},
    )
    monkeypatch.setattr(main_module, "chime_runtimes", {})
    monkeypatch.setattr(main_module, "camera_runtimes", {"offline_camera": camera})
    monkeypatch.setattr(main_module, "target_runtimes", {"offline_camera": camera})
    monkeypatch.setattr(main_module, "GROUPS", {})

    result = await main_module.list_targets()

    assert result["targets"][0]["capabilities"]["announce"] is False
    assert "offline_camera" not in main_module._available_rule_targets()
