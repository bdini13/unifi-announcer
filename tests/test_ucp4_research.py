import pytest

from app.experimental.ucp4_research import (
    ResearchCommandDenied,
    ResearchDisabled,
    ResearchTransportUnavailable,
    Ucp4ResearchClient,
)


def test_ucp4_research_is_default_off(monkeypatch):
    monkeypatch.delenv("UCP4_RESEARCH_ENABLED", raising=False)
    client = Ucp4ResearchClient.from_env()

    with pytest.raises(ResearchDisabled):
        client.request("getStatus")

    assert client.status() == {
        "enabled": False,
        "connected": False,
        "transport": "unavailable",
        "protocol": "research_only",
    }


@pytest.mark.parametrize(
    "command",
    [
        "playSpeaker",
        "playBuzzer",
        "adopt",
        "factoryReset",
        "changePassword",
        "deleteRingtone",
        "uploadRingtone",
        "reboot",
    ],
)
def test_ucp4_research_permanently_denies_side_effect_commands(command):
    client = Ucp4ResearchClient(enabled=True)

    with pytest.raises(ResearchCommandDenied):
        client.request(command)


@pytest.mark.parametrize("command", ["sendRequest", "sendSafe", "unknownCommand"])
def test_ucp4_research_denies_unclassified_commands(command):
    client = Ucp4ResearchClient(enabled=True)

    with pytest.raises(ResearchCommandDenied):
        client.request(command)


def test_ucp4_research_has_no_transport_even_when_enabled():
    client = Ucp4ResearchClient(enabled=True)

    with pytest.raises(ResearchTransportUnavailable):
        client.request("getStatus")

    assert client.status()["connected"] is False
