from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.unifi_announcer.entity import get_entry_device


def test_registry_lookup_supports_minimum_home_assistant():
    lookup = Mock(return_value="device")
    registry = SimpleNamespace(async_get_device=lookup)
    assert get_entry_device(registry, ("unifi_announcer", "fixture"), "entry") == "device"
    lookup.assert_called_once_with(identifiers={("unifi_announcer", "fixture")})


def test_registry_lookup_prefers_current_scoped_api():
    scoped = Mock(return_value="device")
    legacy = Mock(side_effect=AssertionError("deprecated API must not be used"))
    registry = SimpleNamespace(async_get_device_by_identifier=scoped, async_get_device=legacy)
    assert get_entry_device(registry, ("unifi_announcer", "fixture"), "entry") == "device"
    scoped.assert_called_once_with(("unifi_announcer", "fixture"), "entry")
