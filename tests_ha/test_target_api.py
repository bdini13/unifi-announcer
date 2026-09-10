from unittest.mock import AsyncMock

import pytest

from custom_components.unifi_announcer.api import (
    InvalidResponse,
    UniFiAnnouncerClient,
)


def _client_with_requests(*responses):
    client = object.__new__(UniFiAnnouncerClient)
    client._request = AsyncMock(side_effect=responses)
    return client


@pytest.mark.asyncio
async def test_target_catalog_is_translated_for_existing_entity_consumers():
    client = _client_with_requests((
        200,
        {
            "schema_version": 1,
            "targets": [
                {
                    "name": "kitchen",
                    "id": "chime-one",
                    "type": "chime",
                    "queue_depth": 1,
                    "capabilities": {"announce": True, "buzzer": True},
                },
                {
                    "name": "family_camera",
                    "id": "camera-one",
                    "type": "camera",
                    "model": "UVC G3 Instant",
                    "compatibility": "experimental_opt_in",
                    "status": "available",
                    "queue_depth": 0,
                    "capabilities": {"announce": True, "buzzer": False},
                },
            ],
            "groups": [
                {
                    "name": "mixed",
                    "type": "group",
                    "members": ["kitchen", "family_camera"],
                    "capabilities": {"announce": True, "buzzer": False},
                }
            ],
        },
    ))

    result = await client.async_get_chimes()

    assert result["chimes"][0]["id"] == "chime-one"
    assert result["cameras"][0]["id"] == "camera-one"
    assert result["cameras"][0]["capability_state"]["model"] == "UVC G3 Instant"
    assert (
        result["cameras"][0]["capability_state"]["compatibility"]
        == "experimental_opt_in"
    )
    assert result["groups"] == {"mixed": ["kitchen", "family_camera"]}
    assert result["group_capabilities"]["mixed"]["buzzer"] is False
    client._request.assert_awaited_once_with("GET", "/targets")


@pytest.mark.asyncio
async def test_target_catalog_discards_unknown_compatibility_labels():
    client = _client_with_requests((
        200,
        {
            "schema_version": 1,
            "targets": [{
                "name": "camera",
                "id": "camera-one",
                "type": "camera",
                "compatibility": "untrusted_future_value",
                "capabilities": {"announce": False},
            }],
            "groups": [],
        },
    ))

    result = await client.async_get_chimes()

    assert "compatibility" not in result["cameras"][0]["capability_state"]


@pytest.mark.asyncio
async def test_target_catalog_falls_back_to_legacy_chimes_only_on_404():
    legacy = {
        "chimes": [{"name": "default", "id": "chime-one", "queue_depth": 0}],
        "groups": {"all": ["default"]},
    }
    client = _client_with_requests((404, {"detail": "missing"}), (200, legacy))

    result = await client.async_get_targets()

    assert result["schema_version"] == 1
    assert result["targets"][0]["type"] == "chime"
    assert result["targets"][0]["capabilities"]["play_default"] is True
    assert result["groups"][0]["name"] == "all"
    assert [call.args for call in client._request.await_args_list] == [
        ("GET", "/targets"),
        ("GET", "/chimes"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500])
async def test_target_catalog_does_not_hide_non_404_failures(status):
    client = _client_with_requests((status, {"detail": "failed"}))

    with pytest.raises(InvalidResponse, match="Invalid targets response"):
        await client.async_get_targets()

    assert client._request.await_count == 1


@pytest.mark.asyncio
async def test_support_bundle_client_requires_redacted_v1_contract():
    payload = {
        "schema_version": 1,
        "redaction": {"device_identifiers": "omitted"},
        "targets": [],
    }
    client = _client_with_requests((200, payload))

    assert await client.async_get_support_bundle() == payload
    client._request.assert_awaited_once_with("GET", "/diagnostics/support")

    invalid = _client_with_requests((200, {"schema_version": 1}))
    with pytest.raises(InvalidResponse, match="Invalid support bundle response"):
        await invalid.async_get_support_bundle()


@pytest.mark.asyncio
async def test_media_announce_uploads_raw_audio_with_bounded_request_timeout():
    client = _client_with_requests((200, {"disposition": "played"}))

    result = await client.async_announce_media(
        b"audio-bytes", "audio/mpeg", target="kitchen", repeat_times=2
    )

    assert result.disposition == "played"
    call = client._request.await_args
    assert call.args == ("POST", "/media/announce")
    assert call.kwargs["params"] == {"target": "kitchen", "repeat_times": 2}
    assert call.kwargs["data"] == b"audio-bytes"
    assert call.kwargs["headers"] == {"Content-Type": "audio/mpeg"}
    assert call.kwargs["timeout"].total == 60.0
