"""Home Assistant test fixtures for UniFi Announcer."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components integrations in Home Assistant tests."""
    yield
