"""Home Assistant media-source resolution for UniFi Announcer playback."""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
from homeassistant.components import media_source
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UniFiAnnouncerError

MAX_MEDIA_BYTES = 4 * 1024 * 1024
MEDIA_FETCH_TIMEOUT_SECONDS = 15.0


class MediaSourceFetchError(UniFiAnnouncerError):
    """Home Assistant could not resolve or read a bounded audio media source."""


def _canonical_content_type(value: str | None) -> str:
    return (value or "").partition(";")[0].strip().lower()


def _validated_audio_type(value: str | None) -> str:
    content_type = _canonical_content_type(value)
    if not content_type.startswith("audio/"):
        raise MediaSourceFetchError(
            f"Resolved media must be audio; got {content_type or 'unknown content type'}"
        )
    return content_type


def _check_size(size: int) -> None:
    if size > MAX_MEDIA_BYTES:
        raise MediaSourceFetchError(
            f"Resolved media exceeds {MAX_MEDIA_BYTES} byte input limit"
        )


async def _read_local_media(hass, path: Path) -> bytes:
    try:
        size = (await hass.async_add_executor_job(path.stat)).st_size
        _check_size(size)
        payload = await hass.async_add_executor_job(path.read_bytes)
    except (OSError, ValueError) as exc:
        raise MediaSourceFetchError("Could not read resolved local media") from exc
    _check_size(len(payload))
    if not payload:
        raise MediaSourceFetchError("Resolved media is empty")
    return payload


async def _download_media(hass, url: str) -> tuple[bytes, str | None]:
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(MEDIA_FETCH_TIMEOUT_SECONDS):
            async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                if response.status >= 400:
                    raise MediaSourceFetchError(
                        f"Resolved media request failed with HTTP {response.status}"
                    )
                declared = response.headers.get("Content-Length")
                if declared:
                    try:
                        _check_size(int(declared))
                    except ValueError as exc:
                        raise MediaSourceFetchError(
                            "Resolved media returned an invalid Content-Length"
                        ) from exc
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    _check_size(total)
                    chunks.append(chunk)
                payload = b"".join(chunks)
                if not payload:
                    raise MediaSourceFetchError("Resolved media is empty")
                return payload, response.headers.get("Content-Type")
    except MediaSourceFetchError:
        raise
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise MediaSourceFetchError("Could not download resolved media") from exc


async def async_resolve_media_bytes(
    hass, media_id: str, target_media_player: str | None
) -> tuple[bytes, str]:
    """Resolve one media-source URI to bounded audio bytes and its MIME type."""
    if not media_source.is_media_source_id(media_id):
        raise MediaSourceFetchError("media_content_id must be a media-source URI")
    try:
        resolved = await media_source.async_resolve_media(
            hass, media_id, target_media_player
        )
    except Exception as exc:
        raise MediaSourceFetchError("Could not resolve Home Assistant media source") from exc

    resolved_type = _validated_audio_type(resolved.mime_type)
    if resolved.path is not None:
        payload = await _read_local_media(hass, Path(resolved.path))
        return payload, resolved_type

    url = async_process_play_media_url(hass, resolved.url)
    payload, response_type = await _download_media(hass, url)
    response_type = _canonical_content_type(response_type)
    if response_type.startswith("audio/"):
        return payload, response_type
    return payload, resolved_type
