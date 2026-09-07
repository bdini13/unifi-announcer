from types import SimpleNamespace

from custom_components.unifi_announcer.entity import (
    configured_announcement_targets,
    target_supports,
)


def _coordinator(camera_available: bool):
    return SimpleNamespace(
        data={
            "chimes": {
                "chimes": [
                    {
                        "name": "kitchen",
                        "id": "chime-one",
                        "capabilities": {"announce": True},
                    }
                ],
                "cameras": [
                    {
                        "name": "family_camera",
                        "id": "camera-one",
                        "capabilities": {"announce": camera_available},
                        "capability_state": {
                            "status": "available" if camera_available else "unavailable"
                        },
                    }
                ],
                "groups": {"mixed": ["kitchen", "family_camera"]},
                "group_capabilities": {
                    "mixed": {"announce": camera_available}
                },
            }
        }
    )


def test_configured_camera_and_group_entities_survive_temporary_unavailability():
    coordinator = _coordinator(False)
    targets = configured_announcement_targets(coordinator)

    assert ("family_camera", "camera-one", False, "camera") in targets
    assert ("mixed", None, True, "group") in targets
    assert target_supports(coordinator, "family_camera", "announce") is False
    assert target_supports(coordinator, "mixed", "announce") is False

    coordinator.data["chimes"]["cameras"][0]["capabilities"]["announce"] = True
    coordinator.data["chimes"]["group_capabilities"]["mixed"]["announce"] = True

    assert target_supports(coordinator, "family_camera", "announce") is True
    assert target_supports(coordinator, "mixed", "announce") is True
