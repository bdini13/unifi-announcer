from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.dispatcher import (
    AnnouncementCommand,
    AnnouncementDispatcher,
    DispatchResult,
    SuppressedResult,
)
from app.playback.policy import PlaybackPolicy


def test_main_dispatcher_is_wired_to_playback_policy(main_module):
    assert isinstance(main_module.dispatcher.playback_policy, PlaybackPolicy)


def test_playback_policy_resolves_explicit_then_profile_then_default():
    policy = PlaybackPolicy(
        profiles={"night": {"volume": 20, "repeat": 2}},
        volume_default=50,
        repeat_default=1,
    )

    assert policy.resolve(volume=0, repeat_times=None, profile="night") == (0, 2)
    assert policy.resolve(volume=None, repeat_times=None, profile="night") == (20, 2)
    assert policy.resolve(volume=None, repeat_times=None, profile=None) == (50, 1)


def test_suppressed_result_is_a_deep_dispatch_result():
    result = SuppressedResult("announce", "quiet hours")

    assert isinstance(result, DispatchResult)
    assert result.disposition == "suppressed"
    assert result.response()["detail"] == "quiet hours"


class _Metrics:
    def observe(self, *args):
        pass

    def inc(self, *args):
        pass


class _Queue:
    async def submit(self, request):
        return await request.run()


@pytest.mark.asyncio
async def test_dispatcher_uses_playback_policy_and_priority_before_quiet_hours():
    play = AsyncMock(return_value={"played": True})
    policy = PlaybackPolicy(
        profiles={"night": {"volume": 20, "repeat": 2}},
        volume_default=50,
        repeat_default=1,
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="default", chime_id="chime-1"), queue=_Queue()
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play=play), chime=SimpleNamespace(),
        ringtone_index=SimpleNamespace(), synthesize=AsyncMock(),
        slug=lambda text: text, resolve_preset=AsyncMock(return_value="tone"),
        resolve_targets=lambda selected: [target], playback_policy=policy,
        profile=lambda values: values, quiet=lambda: True, metrics=_Metrics(),
        volume_default=50, repeat_default=1, debug_timings=False,
    )

    urgent = await dispatcher.dispatch(AnnouncementCommand(
        action="play_preset", preset="tone", profile="night", volume=0,
        priority=10,
    ))
    suppressed = await dispatcher.dispatch(AnnouncementCommand(
        action="play_preset", preset="tone", profile="night", priority=50,
    ))

    assert urgent.disposition == "played"
    play.assert_awaited_once_with("tone", 0, 2, chime_id="chime-1")
    assert isinstance(suppressed, SuppressedResult)


@pytest.mark.asyncio
async def test_play_default_uses_resolved_profile_values():
    play_default = AsyncMock(return_value={"played": True})
    policy = PlaybackPolicy(
        profiles={"night": {"volume": 20, "repeat": 2}},
        volume_default=50,
        repeat_default=1,
    )
    target = SimpleNamespace(
        desc=SimpleNamespace(name="default", chime_id="chime-1"), queue=_Queue()
    )
    dispatcher = AnnouncementDispatcher(
        protect=SimpleNamespace(play_default=play_default), chime=SimpleNamespace(),
        ringtone_index=SimpleNamespace(), synthesize=AsyncMock(),
        slug=lambda text: text, resolve_preset=AsyncMock(),
        resolve_targets=lambda selected: [target], playback_policy=policy,
        profile=lambda values: values, quiet=lambda: False, metrics=_Metrics(),
        volume_default=50, repeat_default=1,
    )

    await dispatcher.dispatch(AnnouncementCommand(
        action="play_default", profile="night", priority=10,
    ))

    play_default.assert_awaited_once_with(20, 2, chime_id="chime-1")


@pytest.mark.asyncio
async def test_rest_preset_accepts_same_policy_fields_as_mqtt(main_module):
    dispatch = AsyncMock(return_value=DispatchResult("play_preset", "played"))
    main_module.app.state.services = SimpleNamespace(dispatcher=SimpleNamespace(dispatch=dispatch))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/presets/tone/play?volume=33&repeat_times=2&profile=night&priority=10&target=all"
        )

    assert response.status_code == 200
    command = dispatch.await_args.args[0]
    mqtt = main_module.mqtt_bridge
    mqtt_dispatch = AsyncMock(return_value=DispatchResult("play_preset", "played"))
    mqtt.bind(mqtt_dispatch)
    await mqtt._on_message(SimpleNamespace(
        topic="unifi-announcer/chime/all/play",
        payload=b'{"preset":"tone","volume":33,"repeat_times":2,"profile":"night","priority":10,"target":"all"}',
    ))
    mqtt_command = mqtt_dispatch.await_args.args[0]

    expected = (33, 2, "night", 10, "all")
    assert (command.volume, command.repeat_times, command.profile, command.priority, command.target) == expected
    assert (mqtt_command.volume, mqtt_command.repeat_times, mqtt_command.profile,
            mqtt_command.priority, mqtt_command.target) == expected


@pytest.mark.asyncio
async def test_mqtt_publishes_and_logs_dispatch_disposition(main_module, caplog):
    result = SuppressedResult("announce", "suppressed during quiet hours")
    dispatch = AsyncMock(return_value=result)
    publish = AsyncMock()
    mqtt = main_module.MqttBridge(dispatch)
    mqtt.publish_disposition = publish

    with caplog.at_level("INFO", logger="unifi-announcer"):
        await mqtt._on_message(SimpleNamespace(
            topic="unifi-announcer/announce",
            payload=b'{"text":"quiet"}',
        ))

    publish.assert_awaited_once_with(result)
    assert "MQTT command disposition=suppressed action=announce" in caplog.text
