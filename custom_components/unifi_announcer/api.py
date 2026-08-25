"""Async client for the UniFi Announcer REST API.

This module intentionally has no Home Assistant imports so the transport contract
can be unit-tested independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp


class UniFiAnnouncerError(Exception):
    """Base client error."""


class CannotConnect(UniFiAnnouncerError):
    """The service could not be reached."""


class AuthenticationError(UniFiAnnouncerError):
    """The configured API key was rejected."""


class InvalidResponse(UniFiAnnouncerError):
    """The server response did not match the public contract."""


class PlaybackFailed(UniFiAnnouncerError):
    """Playback failed completely."""


@dataclass(frozen=True)
class CommandResult:
    """Canonical command result returned by the service."""

    disposition: str
    payload: dict[str, Any]
    status: int

    @property
    def nonfatal(self) -> bool:
        return self.disposition in {"played", "suppressed", "deduped", "dropped"}


def normalize_base_url(value: str) -> str:
    """Normalize an Announcer base URL for config-entry uniqueness."""
    raw = value.strip().rstrip("/")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL must start with http:// or https:// and include a host")
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


class UniFiAnnouncerClient:
    """Small typed wrapper around UniFi Announcer's stable REST surface."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str,
                 api_key: str = "", timeout: float = 15.0) -> None:
        self._session = session
        self.base_url = normalize_base_url(base_url)
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key} if self._api_key else {}

    async def _request(self, method: str, path: str, *, expect_json: bool = True,
                       **kwargs: Any) -> tuple[int, Any]:
        headers = dict(kwargs.pop("headers", {}))
        headers.update(self.headers)
        try:
            async with self._session.request(
                method, f"{self.base_url}{path}", headers=headers,
                timeout=self._timeout, **kwargs
            ) as response:
                if response.status in {401, 403}:
                    raise AuthenticationError("UniFi Announcer rejected the API key")
                if not expect_json and response.status == 204:
                    return response.status, None
                try:
                    data = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise InvalidResponse(f"Invalid JSON from {path}") from exc
                return response.status, data
        except AuthenticationError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise CannotConnect(str(exc)) from exc

    async def _command(self, method: str, path: str, **kwargs: Any) -> CommandResult:
        status, payload = await self._request(method, path, **kwargs)
        if not isinstance(payload, dict) or not isinstance(payload.get("disposition"), str):
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if status >= 400 and detail:
                raise PlaybackFailed(str(detail))
            raise InvalidResponse("Command response is missing disposition")
        result = CommandResult(payload["disposition"], payload, status)
        if result.disposition == "failed" or status == 502:
            raise PlaybackFailed(str(payload.get("detail") or payload))
        return result

    async def async_check_auth(self) -> None:
        status, _ = await self._request("GET", "/auth/check", expect_json=False)
        if status != 204:
            raise InvalidResponse(f"Unexpected /auth/check status {status}")

    async def async_get_health(self) -> dict[str, Any]:
        status, data = await self._request("GET", "/health")
        if status != 200 or not isinstance(data, dict):
            raise InvalidResponse("Invalid health response")
        return data

    async def async_get_version(self) -> dict[str, Any]:
        status, data = await self._request("GET", "/version")
        if status != 200 or not isinstance(data, dict):
            raise InvalidResponse("Invalid version response")
        return data

    async def async_get_chimes(self) -> dict[str, Any]:
        status, data = await self._request("GET", "/chimes")
        if status != 200 or not isinstance(data, dict):
            raise InvalidResponse("Invalid chimes response")
        return data

    async def async_get_presets(self) -> list[dict[str, Any]]:
        status, data = await self._request("GET", "/presets")
        if status != 200 or not isinstance(data, dict) or not isinstance(data.get("presets"), list):
            raise InvalidResponse("Invalid presets response")
        return data["presets"]

    async def async_announce(self, text: str, **options: Any) -> CommandResult:
        body = {"text": text, **{k: v for k, v in options.items() if v is not None}}
        return await self._command("POST", "/announce", json=body)

    async def async_play_preset(self, name: str, **options: Any) -> CommandResult:
        params = {k: v for k, v in options.items() if v is not None}
        return await self._command("POST", f"/presets/{name}/play", params=params)

    async def async_play_default(self, **options: Any) -> CommandResult:
        params = {k: v for k, v in options.items() if v is not None}
        return await self._command("POST", "/play-default", params=params)

    async def async_buzzer(self, target: str | None = None) -> CommandResult:
        params = {"target": target} if target else None
        return await self._command("POST", "/buzzer", params=params)
