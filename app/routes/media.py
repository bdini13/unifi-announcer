"""Bounded binary-media route that reuses the canonical announcement dispatcher."""
from __future__ import annotations

import hmac
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.audio.media_ingest import (
    AudioMediaNormalizer,
    InvalidMedia,
    MediaIngestError,
    MediaTooLarge,
    UnsupportedMediaType,
    canonical_media_type,
)
from app.routes.commands import announce_command


_MEDIA_SENTINEL = "\x00unifi-announcer-media-ingress\x00"
_media_payload: ContextVar[bytes | None] = ContextVar("unifi_announcer_media_payload", default=None)


class MediaIngress:
    """Authorize, bound, normalize, then dispatch uploaded audio as an announcement."""

    def __init__(self, core: Any, normalizer: AudioMediaNormalizer | None = None) -> None:
        self.core = core
        self.normalizer = normalizer or AudioMediaNormalizer()

    def wrap_synthesize(
        self, delegate: Callable[[str], Awaitable[bytes]]
    ) -> Callable[[str], Awaitable[bytes]]:
        """Return a task-local media passthrough while preserving normal TTS calls."""

        async def synthesize(text: str) -> bytes:
            payload = _media_payload.get()
            if text == _MEDIA_SENTINEL and payload is not None:
                return payload
            return await delegate(text)

        return synthesize

    async def endpoint(self, request: Request) -> JSONResponse:
        """POST raw audio to the same dispatcher used by text announcements."""
        if denied := self._authorize(request):
            return denied

        try:
            content_encoding = request.headers.get("content-encoding", "").strip().lower()
            if content_encoding not in {"", "identity"}:
                return JSONResponse(
                    {"detail": "compressed request bodies are not supported"},
                    status_code=415,
                )

            content_type = canonical_media_type(request.headers.get("content-type", ""))
            if not content_type:
                return JSONResponse({"detail": "Content-Type is required"}, status_code=415)

            volume = self._optional_int(request, "volume", 0, 100)
            repeat_times = self._optional_int(request, "repeat_times", 1, 6)
            priority = self._optional_int(request, "priority", 0, 100, default=50)
            target = self._optional_text(request, "target", 128)
            profile = self._optional_text(request, "profile", 128)
            dedupe_key = self._optional_text(request, "dedupe_key", 256)

            raw = await self._read_body(request)
            normalized = await self.normalizer.normalize(raw, content_type)
            token = _media_payload.set(normalized)
            try:
                result = await self.core.dispatcher.dispatch(
                    announce_command(
                        _MEDIA_SENTINEL,
                        volume=volume,
                        repeat_times=repeat_times,
                        profile=profile,
                        target=target,
                        priority=priority if priority is not None else 50,
                        dedupe_key=dedupe_key,
                        source="media_api",
                    )
                )
            finally:
                _media_payload.reset(token)

            response = result.response()
            response["media"] = {
                "input_content_type": content_type,
                "normalized_content_type": "audio/mpeg",
                "input_bytes": len(raw),
                "normalized_bytes": len(normalized),
            }
            status = {
                "suppressed": 202,
                "failed": 502,
                "partial": 207,
            }.get(result.disposition, 200)
            return JSONResponse(response, status_code=status)
        except MediaTooLarge as exc:
            return JSONResponse({"detail": str(exc)}, status_code=413)
        except UnsupportedMediaType as exc:
            return JSONResponse({"detail": str(exc)}, status_code=415)
        except (InvalidMedia, MediaIngestError, ValueError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except Exception as exc:
            self.core.log.exception("media announcement failed")
            return JSONResponse({"detail": str(exc)}, status_code=502)

    def _authorize(self, request: Request) -> JSONResponse | None:
        if not self.core._api_key_is_configured():
            return JSONResponse(
                {"detail": "APP_API_KEY is not configured"}, status_code=503
            )
        if not hmac.compare_digest(
            request.headers.get("x-api-key", ""), self.core.APP_API_KEY
        ):
            return JSONResponse(
                {"detail": "invalid or missing API key"}, status_code=403
            )
        return None

    async def _read_body(self, request: Request) -> bytes:
        limit = self.normalizer.limits.max_input_bytes
        declared = request.headers.get("content-length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                raise ValueError("Content-Length must be an integer") from exc
            if declared_size < 0:
                raise ValueError("Content-Length cannot be negative")
            if declared_size > limit:
                raise MediaTooLarge(f"media payload exceeds {limit} byte input limit")

        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                raise MediaTooLarge(f"media payload exceeds {limit} byte input limit")
            chunks.append(chunk)
        payload = b"".join(chunks)
        if not payload:
            raise InvalidMedia("media payload cannot be empty")
        return payload

    @staticmethod
    def _optional_int(
        request: Request,
        name: str,
        minimum: int,
        maximum: int,
        *,
        default: int | None = None,
    ) -> int | None:
        raw = request.query_params.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _optional_text(request: Request, name: str, maximum: int) -> str | None:
        raw = request.query_params.get(name)
        if raw is None:
            return None
        value = raw.strip()
        if not value:
            return None
        if len(value) > maximum:
            raise ValueError(f"{name} exceeds {maximum} character limit")
        return value
