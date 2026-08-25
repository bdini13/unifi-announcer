import asyncio
from dataclasses import is_dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_phase2_modules_are_importable():
    from app.config import Settings
    from app.chime.credentials import StaticEnvCredentialProvider
    from app.chime.capabilities import DirectDeviceCapabilities
    from app.protect.client import PROTOCOL_NOTES
    from app.audio.tts import normalized_cache_key
    from app.audio.cache import RingtoneIndex
    from app.protect.events import NormalizedProtectEvent
    from app.rules.engine import RuleAction
    from app.playback.arbitration import QueueDisposition
    from app.integrations.mqtt import mqtt_command
    from app.routes.commands import announce_command

    assert Settings.from_env().app_port > 0
    assert StaticEnvCredentialProvider("fixture").name == "static-env"
    assert is_dataclass(DirectDeviceCapabilities)
    assert "v1.7.20" in PROTOCOL_NOTES
    assert normalized_cache_key(" Hello ") == normalized_cache_key("hello")
    assert RingtoneIndex
    assert is_dataclass(NormalizedProtectEvent)
    assert is_dataclass(RuleAction)
    assert QueueDisposition.PLAYED.value == "played"
    assert mqtt_command({"buzzer": True}).action == "buzzer"
    assert announce_command("hello").text == "hello"


def test_app_exposes_services_container(main_module):
    assert hasattr(main_module, "AppServices")
    assert hasattr(main_module.app.state, "services")
    assert main_module.app.state.services.protect is main_module.protect


def test_chime_runtime_owns_direct_client_and_capability_state():
    from app.playback.arbitration import ChimeDescriptor, ChimeRuntime

    direct = object()
    runtime = ChimeRuntime(ChimeDescriptor("three", "id-three"), direct_client=direct)

    assert runtime.direct_client is direct
    assert runtime.capability_state == "not_yet_probed"


def test_runtime_uses_modular_implementations(main_module):
    from app.audio.cache import RingtoneIndex
    from app.chime.capabilities import DirectDeviceCapabilities
    from app.chime.credentials import StaticEnvCredentialProvider
    from app.integrations.mqtt import MqttBridge
    from app.playback.arbitration import ArbitrationQueue
    from app.rules.engine import RulesEngine

    assert isinstance(main_module.ringtone_index, RingtoneIndex)
    assert main_module.DirectDeviceCapabilities is DirectDeviceCapabilities
    assert main_module.StaticEnvCredentialProvider is StaticEnvCredentialProvider
    assert main_module.MqttBridge is MqttBridge
    assert main_module.RulesEngine is RulesEngine
    assert all(isinstance(runtime.queue, ArbitrationQueue)
               for runtime in main_module.chime_runtimes.values())


def test_import_does_not_construct_http_clients(main_module):
    assert main_module.protect._client_instance is None
    assert main_module._direct_http.instance is None
    assert main_module.build_services().dispatcher is main_module.dispatcher


def test_services_container_owns_all_runtime_resources(main_module):
    services = main_module.build_services()

    assert services.events is main_module.events
    assert services.chime_runtimes is main_module.chime_runtimes
    assert services.track_registry is main_module.track_registry
    assert services.metrics is main_module.metrics
    assert services.direct_http is main_module._direct_http
    assert services.synthesize is main_module.synthesize_tts_cached


@pytest.mark.asyncio
async def test_lifespan_uses_injected_services_container(main_module, monkeypatch):
    monkeypatch.setenv("EVENTS_ENABLED", "true")
    runtime = SimpleNamespace(start=MagicMock(), stop=AsyncMock())
    services = SimpleNamespace(
        events=SimpleNamespace(start=AsyncMock(), stop=AsyncMock()),
        track_registry=SimpleNamespace(load=MagicMock()),
        rules=SimpleNamespace(load=MagicMock()),
        chime_runtimes={"fixture": runtime},
        mqtt=SimpleNamespace(start=AsyncMock(), stop=AsyncMock()),
        health=SimpleNamespace(start=MagicMock(), stop=AsyncMock()),
        ringtone_index=SimpleNamespace(load=AsyncMock(), refresh=AsyncMock(), _by_name={}),
        track_reconciler=SimpleNamespace(startup=AsyncMock(return_value={
            "reconciled": {}, "evicted": [],
        })),
        synthesize=AsyncMock(),
        direct_http=SimpleNamespace(aclose=AsyncMock()),
        protect=SimpleNamespace(_client_instance=SimpleNamespace(aclose=AsyncMock())),
    )
    main_module.app.state.services = services

    async with main_module._lifespan(main_module.app):
        pass

    services.events.start.assert_awaited_once()
    services.track_registry.load.assert_called_once()
    services.rules.load.assert_called_once()
    runtime.start.assert_called_once()
    services.mqtt.start.assert_awaited_once()
    services.health.start.assert_called_once()
    services.ringtone_index.load.assert_awaited_once()
    services.synthesize.assert_not_awaited()
    runtime.stop.assert_awaited_once()
    services.mqtt.stop.assert_awaited_once()
    services.health.stop.assert_awaited_once()
    services.events.stop.assert_awaited_once()
    services.direct_http.aclose.assert_awaited_once()
    services.protect._client_instance.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_gc_refreshes_ringtone_index(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "TTS_ENGINE", "none")
    services = main_module.app.state.services
    services.events.start = AsyncMock()
    services.events.stop = AsyncMock()
    services.mqtt.start = AsyncMock()
    services.mqtt.stop = AsyncMock()
    services.health.start = MagicMock()
    services.health.stop = AsyncMock()
    services.direct_http.aclose = AsyncMock()
    services.protect._client_instance = None
    services.ringtone_index.load = AsyncMock()
    services.ringtone_index.refresh = AsyncMock()
    services.ringtone_index.force_refresh = AsyncMock()
    services.track_reconciler.startup = AsyncMock(return_value={
        "reconciled": {}, "evicted": [{"logical_key": "old"}],
    })

    async with main_module._lifespan(main_module.app):
        pass

    services.ringtone_index.force_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_warmup_calls_piper_directly_not_cached_mp3(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "TTS_ENGINE", "piper")
    services = main_module.app.state.services
    services.events.start = AsyncMock()
    services.events.stop = AsyncMock()
    services.mqtt.start = AsyncMock()
    services.mqtt.stop = AsyncMock()
    services.health.start = MagicMock()
    services.health.stop = AsyncMock()
    services.direct_http.aclose = AsyncMock()
    services.protect._client_instance = None
    services.synthesize = AsyncMock(side_effect=AssertionError("cached warmup used"))
    monkeypatch.setattr(main_module.piper_tts, "start", AsyncMock())
    pcm = AsyncMock()
    monkeypatch.setattr(main_module.piper_tts, "synthesize_pcm", pcm)
    monkeypatch.setattr(main_module.piper_tts, "stop", AsyncMock())

    async with main_module._lifespan(main_module.app):
        pass

    pcm.assert_awaited_once_with("warmup")
    services.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_piper_startup_failure_does_not_prevent_app_lifespan(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "TTS_ENGINE", "piper")
    monkeypatch.setattr(main_module.piper_tts, "start", AsyncMock(
        side_effect=ConnectionError("Piper offline")))
    monkeypatch.setattr(main_module.piper_tts, "synthesize_pcm", AsyncMock(
        side_effect=ConnectionError("Piper offline")))
    monkeypatch.setattr(main_module.piper_tts, "stop", AsyncMock())
    services = main_module.app.state.services
    services.events.start = AsyncMock()
    services.events.stop = AsyncMock()
    services.mqtt.start = AsyncMock()
    services.mqtt.stop = AsyncMock()
    services.health.start = MagicMock()
    services.health.stop = AsyncMock()
    services.direct_http.aclose = AsyncMock()
    services.protect._client_instance = None

    async with main_module._lifespan(main_module.app):
        assert services.health.start.called


@pytest.mark.asyncio
async def test_hung_piper_connect_cannot_block_lifespan(main_module, monkeypatch):
    monkeypatch.setattr(main_module, "TTS_ENGINE", "piper")
    main_module.piper_tts.timeout_seconds = 0.01
    async def hang(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(main_module.piper_tts, "start", AsyncMock(side_effect=hang))
    monkeypatch.setattr(main_module.piper_tts, "synthesize_pcm", AsyncMock(side_effect=hang))
    monkeypatch.setattr(main_module.piper_tts, "stop", AsyncMock())
    services = main_module.app.state.services
    services.events.start = AsyncMock()
    services.events.stop = AsyncMock()
    services.mqtt.start = AsyncMock()
    services.mqtt.stop = AsyncMock()
    services.health.start = MagicMock()
    services.health.stop = AsyncMock()
    services.direct_http.aclose = AsyncMock()
    services.protect._client_instance = None

    async with asyncio.timeout(0.1):
        async with main_module._lifespan(main_module.app):
            assert services.health.start.called


def test_runtime_has_one_source_of_truth_for_extracted_classes(main_module):
    import inspect

    expected_modules = {
        "DirectDeviceCapabilities": "app.chime.capabilities",
        "StaticEnvCredentialProvider": "app.chime.credentials",
        "FileCredentialProvider": "app.chime.credentials",
        "MqttBridge": "app.integrations.mqtt",
        "ChimeRuntime": "app.playback.arbitration",
        "RulesEngine": "app.rules.engine",
    }
    for name, module_name in expected_modules.items():
        runtime_class = getattr(main_module, name)
        assert runtime_class.__module__ == module_name
        assert inspect.getmodule(runtime_class).__name__ == module_name
