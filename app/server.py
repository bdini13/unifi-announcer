"""Production ASGI composition for REST + optional MCP + fixed dynamic TTS slots."""
from __future__ import annotations

import asyncio
import hmac
import io
import os
import wave
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import Header, HTTPException, Response
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app import main as core
from app.audio.bounded_cache import BoundedTtsSynthesizer
from app.audio.tts import normalized_cache_key
from app.playback.fixed_slots import DynamicTtsSlotManager
from app.version import APP_VERSION

# Keep FastAPI/OpenAPI metadata aligned with the released container even though
# the legacy core module is intentionally not a packaging/version source.
core.app.version = APP_VERSION


@core.app.get("/auth/check", include_in_schema=True)
async def auth_check(x_api_key: str | None = Header(None, alias="X-API-Key")) -> Response:
    """Harmless API-key validation for client configuration flows."""
    if core.APP_API_KEY and not hmac.compare_digest(x_api_key or "", core.APP_API_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return Response(status_code=204)


async def version_check(_request) -> JSONResponse:
    """Return the core compatibility payload plus semantic release version."""
    payload = await core.version()
    return JSONResponse({"version": APP_VERSION, **payload})


def _tts_cache_key(text: str) -> str:
    voice = core.EDGE_TTS_VOICE if core.TTS_ENGINE == "edge" else core.PIPER_VOICE
    return normalized_cache_key(
        text,
        engine=core.TTS_ENGINE,
        voice=voice,
        rate=core.TTS_RATE,
        sample_rate=core.TTS_SAMPLE_RATE,
        encoder_profile=core.TTS_ENCODER_PROFILE,
    )


tts_cache = BoundedTtsSynthesizer(
    core.synthesize_tts_cached,
    cache_dir=Path(os.getenv("CACHE_DIR", "/data/cache")) / "tts",
    key_factory=_tts_cache_key,
    max_files=int(os.getenv("TTS_CACHE_MAX_FILES", "256")),
    max_bytes=int(os.getenv("TTS_CACHE_MAX_BYTES", str(256 * 1024 * 1024))),
    metrics=core.metrics,
)


async def _ensure_capacity(snapshot, needed: int):
    return await core.track_reconciler.ensure_capacity(snapshot, needed=needed)


async def _resolve_ringtone(name: str):
    return await core.ringtone_index.resolve_or_refresh(name)


async def _get_chime(chime_id: str):
    return await core.protect.get_chime(chime_id=chime_id)


async def _bootstrap_audio(number: int) -> bytes:
    """Create two distinct, inaudible MP3 fingerprints for slot provisioning."""
    sample_rate = 22050
    duration_ms = 120 + (number * 40)
    frames = max(1, int(sample_rate * duration_ms / 1000))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frames)
    return await asyncio.to_thread(core._wav_to_mp3, buf.getvalue())


dynamic_slots = DynamicTtsSlotManager(
    data_dir=os.getenv("DATA_DIR", "/data"),
    list_ringtones=core.protect_backends.ringtone.list_ringtones,
    upload_ringtone=core.protect.upload_ringtone,
    delete_ringtone=core.protect_backends.ringtone.delete_ringtone,
    resolve_ringtone=_resolve_ringtone,
    refresh_index=core.ringtone_index.force_refresh,
    get_chime=_get_chime,
    play_ringtone=core.protect_backends.playback.play,
    ensure_capacity=_ensure_capacity,
    metrics=core.metrics,
    reuse_margin_ms=int(os.getenv("TTS_SLOT_REUSE_MARGIN_MS", "1250")),
    minimum_guard_ms=int(os.getenv("TTS_SLOT_MIN_GUARD_MS", "1750")),
    provisioning_timeout_s=float(os.getenv("TTS_SLOT_PROVISION_TIMEOUT", "15")),
)

# Production uses the bounded host cache and the fixed-slot device path. The
# lower-level core module remains import-compatible for unit tests and tooling.
core.dispatcher.synthesize = tts_cache
core.dispatcher.dynamic_slots = dynamic_slots
setattr(core.app.state.services, "dynamic_slots", dynamic_slots)
setattr(core.app.state.services, "tts_cache", tts_cache)


async def filtered_presets(_request) -> JSONResponse:
    """Hide internal UA-TTS slot identities from user-visible preset lists."""
    try:
        tones = [
            tone for tone in await core.protect_backends.ringtone.list_ringtones()
            if not tone.get("isDefault")
            and not DynamicTtsSlotManager.is_slot_name(str(tone.get("name", "")))
        ]
        return JSONResponse({"presets": tones})
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


async def slot_status(_request) -> JSONResponse:
    return JSONResponse(dynamic_slots.status())


async def cache_status(_request) -> JSONResponse:
    return JSONResponse(tts_cache.stats())


MCP_ENABLED = os.getenv("MCP_ENABLED", "false").lower() == "true"
MCP_API_KEY = os.getenv("MCP_API_KEY", "")
MCP_ALLOWED_HOSTS = [
    value.strip() for value in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if value.strip()
]

_mcp_runtime = None
if MCP_ENABLED:
    if not MCP_API_KEY:
        raise RuntimeError("MCP_ENABLED=true requires MCP_API_KEY")
    from app.integrations.mcp import build_mcp_runtime

    _mcp_runtime = build_mcp_runtime(
        lambda: core.app.state.services,
        api_key=MCP_API_KEY,
        allowed_hosts=MCP_ALLOWED_HOSTS,
        groups=lambda: core.GROUPS,
    )


@asynccontextmanager
async def lifespan(_app: Starlette):
    """Run core startup, then prove/provision fixed TTS slots before serving traffic."""
    # Core beta.2 startup garbage collection must not discard legacy ownership
    # evidence before beta.3 migration can inspect it.
    old_dynamic_limit = core.track_registry.max_dynamic
    core.track_registry.max_dynamic = 1_000_000_000
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(core.app.router.lifespan_context(core.app))
        try:
            await tts_cache.startup()
            status = await dynamic_slots.startup(
                core.chime_runtimes.values(),
                bootstrap_audio_factory=_bootstrap_audio,
                legacy_registry=core.track_registry,
            )
            if not status.get("ready"):
                core.log.warning(
                    "fixed dynamic TTS slots unavailable; arbitrary TTS will fail closed: %s",
                    status.get("last_error"),
                )
            core.track_registry.max_dynamic = old_dynamic_limit
            if _mcp_runtime is not None:
                await stack.enter_async_context(_mcp_runtime.server.session_manager.run())
            yield
        finally:
            core.track_registry.max_dynamic = old_dynamic_limit
            await dynamic_slots.shutdown()


routes = [
    Route("/version", version_check, methods=["GET"]),
    Route("/presets", filtered_presets, methods=["GET"]),
    Route("/tts/slots/status", slot_status, methods=["GET"]),
    Route("/tts/cache/status", cache_status, methods=["GET"]),
]
if _mcp_runtime is not None:
    routes.append(Mount("/mcp", app=_mcp_runtime.app))
routes.append(Mount("/", app=core.app))

app = Starlette(routes=routes, lifespan=lifespan)
