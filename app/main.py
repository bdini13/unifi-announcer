"""UniFi Announcer — TTS + preset tones on your UniFi Protect Chime, on demand.

Pipeline (latency-optimized):
    text --> TTS engine (Piper local / edge-tts cloud) --> MP3 (<1MB)
          --> POST /proxy/protect/api/ringtones  (upload, "TTS slot")
          --> POST /proxy/protect/api/chimes/{id}/play-speaker {ringtoneId}
          --> chime plays

Named presets ("package-delivered", etc.) are uploaded once and cached by ID,
so replaying a preset is a single play-speaker call (~200ms).
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any
import hashlib

from app.audio.cache import RingtoneIndex as ModularRingtoneIndex
from app.observability import MetricsRegistry
from app.health import BackgroundHealth
from app.dispatcher import AnnouncementDispatcher, StaleRingtoneError
from app.routes.commands import announce_command, buzzer_command, default_command, preset_command
import io
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration (all overridable via .env)
# ---------------------------------------------------------------------------

from app.config import Settings

_settings = Settings.from_env()
UNIFI_HOST = _settings.unifi_host
UNIFI_USERNAME = os.getenv("UNIFI_USERNAME", "")
UNIFI_PASSWORD = os.getenv("UNIFI_PASSWORD", "")
CHIME_ID = _settings.chime_id                    # chime UUID from /api/chimes
TTS_ENGINE = os.getenv("TTS_ENGINE", "piper")     # "piper" | "edge" | "none"
PIPER_URL = os.getenv("PIPER_URL", "tcp://piper:10200")
PIPER_VOICE = os.getenv("PIPER_VOICE", "default")
TTS_RATE = os.getenv("TTS_RATE", "1.0")
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", "22050"))
TTS_ENCODER_PROFILE = os.getenv("TTS_ENCODER_PROFILE", "mp3-mono-64k")
TTS_TRIM_LEADING_SILENCE = os.getenv("TTS_TRIM_LEADING_SILENCE", "false").lower() == "true"
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural")
VOLUME_DEFAULT = _settings.volume_default
REPEAT_DEFAULT = _settings.repeat_default
API_PORT = _settings.app_port
PRESETS_DIR = Path(os.getenv("PRESETS_DIR", "/data/presets"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "/data/cache"))
MAX_MP3_BYTES = int(os.getenv("MAX_MP3_BYTES", str(1024 * 1024)))  # Protect limit: 1MB
VERIFY_SSL = os.getenv("UNIFI_VERIFY_SSL", "false").lower() == "true"
# --- WebSocket live-event settings -------------------------------------------
# The NVR pushes real-time device events over a websocket at
# /proxy/protect/ws/updates?lastUpdateId=<bootstrap lastUpdateId>. We reconnect
# with exponential backoff; events are fanned out to any subscribed SSE clients
# and kept in a bounded ring buffer for GET /events/recent.
WS_VERIFY_SSL = os.getenv("WS_VERIFY_SSL", "false").lower() == "true"
EVENTS_BUFFER_MAX = int(os.getenv("EVENTS_BUFFER_MAX", "100"))
# --- Direct device API settings (primary path) --------------------------------
# The chime exposes its own TLS API on :8080 with JSON-body auth
# (username "ubnt" + per-device password provisioned at adoption). The password
# lives on the NVR's Postgres (chimes.password column). We read it once via the
# NVR API bootstrap flow below rather than storing it in .env.
CHIME_DIRECT_IP = os.getenv("CHIME_DIRECT_IP", "")     # auto-discovered if empty
CHIME_DIRECT_USER = os.getenv("CHIME_DIRECT_USER", "ubnt")
# Per-device password from NVR Postgres (see README "Direct device API" for
# the one-liner to fetch it). If unset, the direct path disables itself and
# all traffic rides the NVR standby route.
CHIME_DIRECT_PASSWORD = os.getenv("CHIME_DIRECT_PASSWORD", "")
CHIME_VERIFY_SSL = os.getenv("CHIME_VERIFY_SSL", "false").lower() == "true"
DIRECT_TIMEOUT = float(os.getenv("DIRECT_TIMEOUT", "8"))
# --- Security (Phase 0 hardening) ---------------------------------------------
# Bearer token required on all write/diagnostic routes. GET /health stays public.
# Generate one: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
APP_API_KEY = os.getenv("APP_API_KEY", "")

# Endpoints that must NEVER be called by this service (device-destructive).
# The direct client refuses these paths before any network I/O.
DESTRUCTIVE_ENDPOINTS = (
    "/api/adopt",
    "/api/factoryResetWithoutWiFi",
)
# ucp4 password change has no HTTP path, but block the name defensively too.
DESTRUCTIVE_MARKERS = ("adopt", "factoryreset", "changepassword", "modify_password")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("unifi-announcer")


from contextlib import asynccontextmanager as _acl


@_acl
async def _lifespan(app):
    """Start and stop only the resources owned by the active container."""
    services = app.state.services
    if os.getenv("EVENTS_ENABLED", "true").lower() == "true":
        await services.events.start()
    services.track_registry.load()
    try:
        await services.ringtone_index.load()
        log.info("RingtoneIndex ready: %d tones", len(services.ringtone_index._by_name))
        reconciliation = await services.track_reconciler.startup(
            load_nvr=lambda: services.ringtone_backend.list_ringtones(),
            load_chimes=lambda: services.protect_state.list_chimes(),
        )
        log.info("Track reconciliation complete: %d known, %d evicted",
                 len(reconciliation["reconciled"]), len(reconciliation["evicted"]))
        if reconciliation["evicted"]:
            await services.ringtone_index.force_refresh()
    except Exception as e:
        log.warning("Ringtone index/reconciliation failed (%s) - lazy fallback", e)
    services.rules.load(
        presets=set(services.ringtone_index._by_name),
        targets=set(services.chime_runtimes) | set(GROUPS) | {"default"},
    )
    for rt in services.chime_runtimes.values():
        rt.start()
    await services.mqtt.start()
    services.health.start()
    if TTS_ENGINE == "piper":
        try:
            async with asyncio.timeout(piper_tts.timeout_seconds):
                await piper_tts.start()
        except Exception as e:
            log.warning("Piper unavailable at startup; TTS will retry on demand: %s", e)
        try:
            async with asyncio.timeout(piper_tts.timeout_seconds):
                await piper_tts.synthesize_pcm("warmup")
            log.info("Piper warmed")
        except Exception as e:
            log.warning("Piper warmup skipped: %s", e)
    yield
    await services.health.stop()
    for rt in services.chime_runtimes.values():
        await rt.stop()
    await services.mqtt.stop()
    await piper_tts.stop()
    await services.events.stop()
    await services.direct_http.aclose()
    if services.protect._client_instance is not None:
        await services.protect._client_instance.aclose()



app = FastAPI(lifespan=_lifespan, title="UniFi Announcer", version="2.0.0",
              description="On-demand TTS and preset tones for UniFi Protect Chimes")


@dataclass
class AppServices:
    """Explicit dependency container shared through ``app.state``."""
    protect: Any
    protect_state: Any
    playback_backend: Any
    ringtone_backend: Any
    chime: Any
    direct_http: Any
    events: Any
    chime_runtimes: Any
    track_registry: Any
    track_reconciler: Any
    ringtone_index: Any
    metrics: Any
    rules: Any
    mqtt: Any
    dispatcher: Any
    synthesize: Any
    health: Any

# ---------------------------------------------------------------------------
# UniFi Protect client (session-cached login, CSRF handled)
# ---------------------------------------------------------------------------

class ProtectClient:
    """Minimal authenticated client for the undocumented ringtones API.

    Auth: POST /api/auth/login sets session cookie; responses carry an
    x-csrf-token header that must be echoed back on subsequent calls.
    """

    def __init__(self) -> None:
        self._client_instance: httpx.AsyncClient | None = None
        self._csrf: str = ""
        self._logged_in = False
        self._login_lock = asyncio.Lock()

    @property
    def _client(self) -> httpx.AsyncClient:
        """Construct network resources lazily, never during module import."""
        if self._client_instance is None:
            self._client_instance = httpx.AsyncClient(verify=VERIFY_SSL, timeout=30.0)
        return self._client_instance

    async def _ensure_login(self) -> None:
        """Login once per process; re-login transparently on 401."""
        if self._logged_in:
            return
        async with self._login_lock:
            if self._logged_in:
                return
            r = await self._client.post(
                f"{UNIFI_HOST}/api/auth/login",
                json={"username": UNIFI_USERNAME, "password": UNIFI_PASSWORD,
                      "remember": False, "strict": True},
            )
            if r.status_code != 200:
                raise RuntimeError(f"UniFi login failed: HTTP {r.status_code}")
            self._csrf = r.headers.get("x-csrf-token", "")
            self._logged_in = True

    async def _headers(self) -> dict:
        await self._ensure_login()
        return {"X-CSRF-Token": self._csrf}

    async def _do(self, method: str, path: str, **kw) -> httpx.Response:
        """Request wrapper that retries once after re-login on 401/CSRF expiry."""
        for attempt in range(2):
            headers = await self._headers()
            r = await self._client.request(method, f"{UNIFI_HOST}{path}",
                                           headers=headers, **kw)
            if r.status_code == 401 and attempt == 0:
                self._logged_in = False
                continue
            return r
        return r

    # -- Ringtone operations -------------------------------------------------

    async def list_ringtones(self) -> list[dict]:
        r = await self._do("GET", "/proxy/protect/api/ringtones")
        r.raise_for_status()
        return r.json()

    async def upload_ringtone(self, name: str, mp3: bytes) -> dict:
        """Upload an MP3 (<1MB) as a named ringtone; returns ringtone dict with id."""
        if len(mp3) > MAX_MP3_BYTES:
            raise ValueError(f"MP3 too large: {len(mp3)} > {MAX_MP3_BYTES} bytes")
        files = {"file": (f"{name}.mp3", mp3, "audio/mpeg")}
        r = await self._do("POST", "/proxy/protect/api/ringtones",
                           files=files, data={"name": name})
        if r.status_code != 200:
            raise RuntimeError(f"Ringtone upload failed: HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    async def delete_ringtone(self, ringtone_id: str) -> bool:
        r = await self._do("DELETE", f"/proxy/protect/api/ringtones/{ringtone_id}")
        return r.status_code in (200, 204)

    async def find_ringtone_by_name(self, name: str) -> Optional[dict]:
        """Deprecated compatibility lookup; never used by normal playback.

        Full-list reads are control-plane operations. Callers should use
        ``RingtoneIndex.get`` and refresh only on startup/admin/not-found.
        """
        log.warning("deprecated find_ringtone_by_name full-list lookup")
        name_l = name.lower()
        for rt in await self.list_ringtones():
            if str(rt.get("name", "")).lower() == name_l:
                return rt
        return None

    # -- Playback ------------------------------------------------------------

    async def play(self, ringtone_id: Optional[str] = None,
                   volume: int = VOLUME_DEFAULT,
                   repeat_times: int = REPEAT_DEFAULT, *,
                   chime_id: Optional[str] = None) -> dict:
        """Trigger playback on the configured chime (optionally a specific tone)."""
        payload: dict = {"volume": volume, "repeatTimes": repeat_times}
        if ringtone_id:
            payload["ringtoneId"] = ringtone_id
        r = await self._do("POST", f"/proxy/protect/api/chimes/{chime_id or CHIME_ID}/play-speaker",
                           json=payload)
        if r.status_code not in (200, 204):
            detail = r.text[:200]
            lowered = detail.lower()
            stale_markers = (
                "ringtone not found", "ringtone missing", "ringtone invalid",
                "ringtoneid not found", "ringtoneid missing", "ringtoneid invalid",
                "unknown ringtone", "invalid ringtoneid",
            )
            if (r.status_code in (400, 404)
                    and any(marker in lowered for marker in stale_markers)):
                raise StaleRingtoneError(
                    f"play-speaker rejected ringtone {ringtone_id}: HTTP {r.status_code}: {detail}")
            raise RuntimeError(f"play-speaker failed: HTTP {r.status_code}: {r.text[:200]}")
        return {"played": True, "ringtone_id": ringtone_id,
                "volume": volume, "repeat_times": repeat_times}

    async def play_buzzer(self, *, chime_id: Optional[str] = None) -> dict:
        """Trigger the chime's piezo buzzer tone.

        The buzzer is a hardware tone distinct from any ringtone - it needs no
        upload, no TTS, and no request body at all. Fastest possible "someone's
        at the door" ping (~1 API call, zero prep).
        Endpoint: POST /proxy/protect/api/chimes/{id}/play-buzzer
        """
        r = await self._do("POST", f"/proxy/protect/api/chimes/{chime_id or CHIME_ID}/play-buzzer")
        if r.status_code not in (200, 204):
            raise RuntimeError(f"play-buzzer failed: HTTP {r.status_code}: {r.text[:200]}")
        return {"buzzer": True}

    async def reboot(self) -> dict:
        """Reboot the chime (undocumented endpoint discovered 2026-08).

        POST /proxy/protect/api/chimes/{id}/reboot - takes no meaningful body
        and returns the full device object immediately; the device then drops
        offline for ~30-60s. Useful for remote power-cycling without physical
        access. NOTE: probing this endpoint with ANY body triggers the reboot,
        so never call it speculatively.
        """
        r = await self._do("POST", f"/proxy/protect/api/chimes/{CHIME_ID}/reboot")
        if r.status_code != 200:
            raise RuntimeError(f"reboot failed: HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        return {"rebooting": True, "state": d.get("state"), "name": d.get("name")}

    async def play_default(self, volume: Optional[int] = None,
                           repeat_times: Optional[int] = None, *,
                           chime_id: Optional[str] = None) -> dict:
        """Play the ringtone currently assigned as this chime's default track.

        Per uiprotect/hjdhjd docs, play-speaker with NO ringtoneId plays the
        assigned default track. Volume/repeatTimes overrides are only included
        in the payload when explicitly given; otherwise the device uses its own
        saved settings.
        """
        payload: dict = {}
        if volume is not None or repeat_times is not None:
            # Protect quirk (found live): play-speaker returns 400 when
            # `volume` is sent without `repeatTimes` - overrides come as a
            # pair. Default missing pieces so partial overrides still work.
            payload["volume"] = volume if volume is not None else VOLUME_DEFAULT
            payload["repeatTimes"] = (repeat_times if repeat_times is not None
                                      else REPEAT_DEFAULT)
        r = await self._do("POST", f"/proxy/protect/api/chimes/{chime_id or CHIME_ID}/play-speaker",
                           json=payload)
        if r.status_code not in (200, 204):
            raise RuntimeError(f"play-default failed: HTTP {r.status_code}: {r.text[:200]}")
        return {"played": True, "source": "default-track",
                "volume": volume, "repeat_times": repeat_times}

    # -- Chime configuration ---------------------------------------------------

    async def get_chime(self, *, chime_id: Optional[str] = None) -> dict:
        """Fetch the raw configured-chime object from the NVR.

        Useful fields: name, volume (default), repeatTimes, speakerTrackList
        (tracks pushed to device flash, md5-keyed), ringSettings (per-camera
        tone assignments), state.
        """
        r = await self._do("GET", f"/proxy/protect/api/chimes/{chime_id or CHIME_ID}")
        if r.status_code != 200:
            raise RuntimeError(f"get chime failed: HTTP {r.status_code}")
        return r.json()

    async def patch_chime(self, patch: dict) -> dict:
        """PATCH the chime object (name, default volume, ringSettings, ...).

        Accepts any JSON body the controller accepts; callers are responsible
        for shape. The interesting key is `ringSettings` - per-camera entries:

            [{"cameraId": "<uuid>", "ringtoneId": "<uuid>", "volume": 80,
              "repeatTimes": 1}, ...]

        which assign a distinct tone/volume/repeat per doorbell camera. This is
        config-once and deterministic: the device itself plays that tone when
        that camera's doorbell button is pressed.
        """
        r = await self._do("PATCH", f"/proxy/protect/api/chimes/{CHIME_ID}", json=patch)
        if r.status_code != 200:
            raise RuntimeError(f"patch chime failed: HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    async def list_chimes(self) -> list[dict]:
        r = await self._do("GET", "/proxy/protect/api/chimes")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# DIRECT chime device client (primary path)
#
# The chime runs its own TLS server on :8080 with a small JSON API. For the
# verified JSON endpoints, auth is not HTTP auth: credentials travel in JSON:
#   {"username": "ubnt", "password": "<per-device pw>", ...request fields}
# The password is provisioned at adoption and stored on the NVR (chimes table,
# `password` column). We fetch it lazily through the NVR client so no secret
# needs to live in .env.
#
# Verified endpoints (fw 1.7.20):
#   POST /api/info         - device info + feature flags (safe)
#   POST /api/support      - full log buffer dump (safe)
#   POST /api/uploadRingtone/<slot>/<filename>.mp3 - experimental raw-MP3
#     overwrite route. Authentication research is intentionally unpublished.
#     Generic direct staging is disabled; only the default-off explicit
#     owned-slot research method below can construct this route.
#
# The device presents a self-signed cert; verification is off by default.
# ---------------------------------------------------------------------------

def _make_credential_provider():
    """Forward-declared shim (Phase 4): resolves the real factory defined
    later in this module, avoiding class-ordering issues."""
    return _make_credential_provider_impl()


class DirectChimeClient:
    """Talks straight to the chime hardware, bypassing the NVR relay."""

    def __init__(self, *, chime_id: str = "", direct_ip: str = "") -> None:
        self._chime_id = chime_id or CHIME_ID
        self._base = f"https://{direct_ip}:8080" if direct_ip else ""
        self._lock = asyncio.Lock()
        # All Phase 3/4 objects resolve lazily on first use - their classes
        # are defined later in this module (import-time ordering).
        self._credential_provider = None
        self._breaker = None
        self.capabilities = None
        self.last_401_at: Optional[str] = None

    @property
    def breaker(self):
        """Lazy circuit breaker (Phase 3)."""
        if self._breaker is None:
            self._breaker = CircuitBreaker()
        return self._breaker

    @property
    def credential_provider(self):
        """Lazy provider resolution (Phase 4)."""
        if self._credential_provider is None:
            self._credential_provider = _make_credential_provider_impl()
        return self._credential_provider

    async def _ensure_ready(self) -> None:
        """Resolve the chime IP once (from env or NVR). Credentials flow
        through the provider (Phase 4), not a cached string."""
        if self.credential_provider is not None and self._base:
            return
        async with self._lock:
            if self._base and self.credential_provider is not None:
                return
            # IP: explicit env var wins, else read from NVR chime object (host field).
            # The legacy default IP belongs only to the default chime. Other
            # runtimes discover their own host from their own NVR identity.
            ip = CHIME_DIRECT_IP if self._chime_id == CHIME_ID else ""
            if not ip:
                r = await protect._do(
                    "GET", f"/proxy/protect/api/chimes/{self._chime_id}")
                r.raise_for_status()
                ip = r.json().get("host")
                if not ip:
                    raise RuntimeError("chime IP not resolvable from NVR")
            # Credential comes from the active provider (Phase 4);
            # resolution happens per-request in _post, nothing stored here.
            self._base = f"https://{ip}:8080"

    def _auth_body_sync(self, password: str,
                        extra: Optional[dict] = None) -> dict:
        """Credentials travel inside the JSON body itself (device protocol)."""
        body = {"username": CHIME_DIRECT_USER, "password": password}
        if extra:
            body.update(extra)
        return body

    async def _post(self, path: str, extra: Optional[dict] = None,
                    content: Optional[bytes] = None,
                    content_type: Optional[str] = None) -> httpx.Response:
        """One authenticated POST to the device. Retries once after re-fetching
        credentials. Destructive endpoints are refused BEFORE any network I/O
        (Phase 0 safety gate)."""
        guard_destructive(path)
        # Circuit breaker: fail fast to the NVR fallback while open.
        self.breaker.check()
        for attempt in range(2):
            await self._ensure_ready()
            headers = {"Content-Type": content_type or "application/json"}
            kw: dict = {}
            try:
                password = await self.credential_provider.get(
                    force_refresh=(attempt > 0))
            except RuntimeError:
                self.breaker.record_failure()
                raise
            if content is not None:
                kw["content"] = content
            else:
                kw["json"] = self._auth_body_sync(password, extra)
            try:
                r = await _direct_http.post(f"{self._base}{path}",
                                            timeout=DIRECT_TIMEOUT,
                                            headers=headers, **kw)
            except Exception:
                self.breaker.record_failure()
                raise
            if r.status_code == 401 and attempt == 0 and \
                    self.credential_provider.refreshable:
                # Rotation suspected: force the provider to re-read, retry once.
                from datetime import datetime, timezone
                self.last_401_at = datetime.now(timezone.utc).isoformat()
                metrics.inc("direct_401")
                await self.credential_provider.invalidate()
                continue
            if r.status_code == 200:
                self.breaker.record_success()
            elif r.status_code == 401:
                metrics.inc("direct_401")
                self.breaker.record_failure()
            return r
        return r

    # -- High-level operations -------------------------------------------

    async def info(self) -> dict:
        """Device identity + feature flags. Doubles as a health check and
        refreshes the capability model (Phase 3)."""
        r = await self._post("/api/info")
        if r.status_code != 200:
            raise RuntimeError(f"direct /api/info failed: HTTP {r.status_code}")
        data = r.json()
        self.capabilities = DirectDeviceCapabilities(data)
        return data

    async def upload_ringtone(self, name: str, mp3_bytes: bytes) -> dict:
        """Refuse generic direct staging; the verified route needs owned-slot metadata.

        Direct slot writes do not provide enough ownership evidence for generic
        staging. The facade therefore falls back to the authenticated Protect/NVR
        upload rather than guessing a device slot.
        """
        raise RuntimeError("direct upload requires explicit owned-slot metadata")

    async def overwrite_owned_slot(
        self, *, slot: int, filename: str, mp3_bytes: bytes,
        owner: str, builtin: bool = False, experiment_enabled: bool = False,
    ) -> dict:
        """Overwrite one explicitly service-owned, non-built-in device slot.

        This method models the exact verified firmware-1.7.20 request: raw MP3
        body at ``/api/uploadRingtone/<slot>/<filename>.mp3`` with HTTP Basic
        credentials. Callers must prove ownership and retain rollback bytes before
        invoking it. It is intentionally not wired to production and refuses calls
        unless the default-off experiment is explicitly enabled.
        """
        if not experiment_enabled:
            raise RuntimeError("DYNAMIC_SLOT_EXPERIMENT is false")
        if owner != "unifi_announcer" or builtin:
            raise RuntimeError("direct overwrite requires a service-owned non-built-in slot")
        if not isinstance(slot, int) or slot < 1:
            raise ValueError("slot must be a positive integer")
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}\.mp3", filename):
            raise ValueError("invalid owned-slot filename")
        if self.capabilities is None:
            await self.info()
        if not self.capabilities.allows_upload():
            raise RuntimeError(
                f"direct upload blocked by capability gate "
                f"(firmware={self.capabilities.firmware})")
        await self._ensure_ready()
        password = await self.credential_provider.get()
        path = f"/api/uploadRingtone/{slot}/{filename}"
        guard_destructive(path)
        r = await _direct_http.post(
            f"{self._base}{path}", timeout=DIRECT_TIMEOUT,
            headers={"Content-Type": "audio/mpeg"}, content=mp3_bytes,
            auth=httpx.BasicAuth(CHIME_DIRECT_USER, password),
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"direct owned-slot overwrite failed: HTTP {r.status_code}: "
                f"{r.text[:150]}")
        return {"uploaded": True, "via": "direct-owned-slot", "slot": slot,
                "filename": filename}

    async def support_log(self) -> str:
        """Device log buffer (diagnostics), credential-redacted (Phase 3)."""
        r = await self._post("/api/support")
        if r.status_code != 200:
            raise RuntimeError(f"direct support failed: HTTP {r.status_code}")
        return redact_support_log(r.text)

    async def info_wrapped(self) -> dict:
        """info() wrapped with path tag for the facade layer."""
        info = await self.info()
        return {"via": "direct", "info": info}


# Direct-device TLS verification is configurable (Phase 1 fix): the chime uses
# a self-signed cert so default is off, but CHIME_VERIFY_SSL=true enables it.
from app.protect.client import LazyAsyncClient

_direct_http = LazyAsyncClient(verify=CHIME_VERIFY_SSL, timeout=DIRECT_TIMEOUT)


class ChimeClient:
    """Facade choosing between direct-device (primary) and NVR-relay (standby).

    Every result includes a `via` key ("direct" or "nvr") so callers and logs
    always show which path served the request. If the direct path errors -
    device offline, firmware change closing the endpoint, bad creds - we fall
    back to the NVR route transparently rather than failing.
    """

    def __init__(self) -> None:
        self.direct = DirectChimeClient()
        self.last_direct_error: Optional[str] = None

    async def _with_fallback(self, direct_fn, fallback_fn) -> dict:
        """Run primary path; on any exception, run the NVR standby path."""
        try:
            result = await direct_fn()
            self.last_direct_error = None
            return result
        except Exception as e:
            self.last_direct_error = f"{type(e).__name__}: {e}"
            metrics.inc("direct_fallback")
            log.warning("direct path failed (%s); falling back to NVR",
                        self.last_direct_error)
            return await fallback_fn()

    async def play(self, ringtone_id: Optional[str], volume: int,
                   repeat_times: int) -> dict:
        """Play a tone by NVR ringtone ID. Direct path can't address arbitrary
        NVR ringtone IDs, so playback always rides the NVR relay (the device
        only accepts play commands from its paired controller via ucp4 wss)."""
        return await protect.play(ringtone_id, volume, repeat_times)

    async def buzzer(self) -> dict:
        """Buzzer via NVR relay (ucp4 command, direct HTTP equivalent unknown)."""
        return await protect.play_buzzer()

    async def info(self) -> dict:
        """Direct-first device info; NVR /chimes fallback."""
        async def fb():
            c = await protect.get_chime()
            return {"via": "nvr", "info": {"name": c.get("name"),
                    "state": c.get("state"), "firmware": c.get("firmwareVersion")}}
        return await self._with_fallback(self.direct.info_wrapped, fb)

    async def upload_ringtone(self, name: str, mp3: bytes, *,
                              direct_clients: Optional[list] = None) -> dict:
        """Create the authenticated Protect/NVR identity only.

        Direct staging is experimental and remains disabled, even when callers
        pass discovered direct clients. The separate explicit
        owned-slot method remains disconnected from this production facade.
        """
        self.last_direct_error = None
        created = await protect.upload_ringtone(name, mp3)
        return {
            "uploaded": True,
            "via": "nvr",
            "direct_targets_uploaded": 0,
            **created,
        }


chime_client = ChimeClient()


# ---------------------------------------------------------------------------
# Phase 3: capability-driven direct-device protocol
#
# The chime's API varies by firmware. Capabilities are captured from /api/info
# at startup and gate every operation; unknown firmware fails closed for
# writes while read-only info remains available.
# ---------------------------------------------------------------------------

# Runtime source of truth lives in the focused module.
from app.chime.capabilities import DirectDeviceCapabilities


class CircuitBreaker:
    """Stops hammering a dead/unauthorized direct path on every request.

    States: closed (normal), open (failing fast), half_open (probing).
    After FAILURE_THRESHOLD consecutive failures it opens for COOLDOWN_S,
    then lets one probe through (/api/info). Success closes it again.
    """

    def __init__(self, failure_threshold: int = 3, cooldown_s: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at: Optional[float] = None

    @property
    def state(self) -> str:
        import time as _t
        if self._opened_at is None:
            return "closed"
        if _t.monotonic() - self._opened_at >= self.cooldown_s:
            return "half_open"
        return "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = time.monotonic()
            log.warning("direct-path circuit OPENED after %d failures",
                        self._failures)

    def check(self) -> None:
        """Raise if currently open (caller should use the fallback path)."""
        if self.state == "open":
            raise RuntimeError("circuit open - direct path cooling down")


# ---------------------------------------------------------------------------
# Phase 3: support-log redaction
# ---------------------------------------------------------------------------

_REDACT_PATTERNS = [
    # WiFi credentials logged during connect flows
    (re.compile(r"(password|passwd|psk)[:=]\s*\S+", re.I), r"\1=[REDACTED]"),
    # Authorization headers / tokens
    (re.compile(r"(authorization|x-token|x-api-key)[:=]\s*\S+", re.I), r"\1=[REDACTED]"),
    # Long base64/hex blobs (cert/key material)
    (re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"), "[REDACTED-BLOB]"),
]


def redact_support_log(text: str) -> str:
    """Strip credential-like material from device logs before exposing them
    through the public service API."""
    for pat, repl in _REDACT_PATTERNS:
        text = pat.sub(repl, text)
    return text


# ---------------------------------------------------------------------------
# Phase 4: credential provider abstraction
#
# UniFi rotates the chime's per-device password (~daily). A static env var can
# go stale; providers make the refresh story honest instead of pretending.
# ---------------------------------------------------------------------------

# Runtime source of truth lives in the focused module.
from app.chime.credentials import FileCredentialProvider, StaticEnvCredentialProvider


def _make_credential_provider_impl():
    """Choose provider from config: file path wins over static env."""
    file_path = os.getenv("CHIME_CREDENTIAL_FILE", "")
    if file_path:
        return FileCredentialProvider(file_path)
    return StaticEnvCredentialProvider(CHIME_DIRECT_PASSWORD)


# ---------------------------------------------------------------------------
# RingtoneIndex (Phases 2/6): one-time NVR ringtone snapshot at startup.
#
# Removes the per-request GET /ringtones from the playback hot path. Lookups
# hit RAM; the index refreshes transactionally after upload/delete or on an
# explicit cache-miss recovery path.
# ---------------------------------------------------------------------------

ringtone_index = ModularRingtoneIndex()


# ---------------------------------------------------------------------------
# Phase 5: TrackRegistry
#
# Models the THREE distinct identities the old code conflated:
#   1. logical_key  - what the caller asks for (text slug / preset name)
#   2. device track - an MP3 in chime flash (/lfs/track/N)
#   3. NVR ringtone - Protect's database object with a play ID
#
# A track may exist on the device only, NVR only, or both. The registry is
# persisted to /data so restarts don't lose the mapping.
# ---------------------------------------------------------------------------

from app.tracks import TrackRecord, TrackRegistry, TrackReconciler

MAX_DYNAMIC_TRACKS = int(os.getenv("MAX_DYNAMIC_TRACKS", "32"))
track_registry = TrackRegistry(max_dynamic=MAX_DYNAMIC_TRACKS)
track_reconciler = TrackReconciler(track_registry)


# ---------------------------------------------------------------------------
# Phase 13: optional MQTT bridge + Home Assistant discovery
#
# Enable with MQTT_URL=mqtt://host:1883 (+MQTT_USERNAME/MQTT_PASSWORD).
# REST/SSE remain fully functional when MQTT is off or broker is down.
# ---------------------------------------------------------------------------

MQTT_URL = os.getenv("MQTT_URL", "")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")


from app.integrations.mqtt import MqttBridge

mqtt_bridge = MqttBridge()


# ---------------------------------------------------------------------------
# Phases 11 + 12: multi-chime registry & playback arbitration
#
# Today's deployment has one chime; everything below degrades to identical
# behavior while making the service multi-chime-ready:
#   - CHIMES_CONFIG env (JSON) can define additional chimes + groups later
#   - target=chime-or-group on play APIs fans out concurrently
#   - a per-chime priority queue arbitrates overlapping automations
# ---------------------------------------------------------------------------

PRIORITY_EMERGENCY = 0
PRIORITY_DOORBELL = 10
PRIORITY_PACKAGE = 20
PRIORITY_NORMAL = 50
PRIORITY_INFO = 100
QUEUE_MAX_DEPTH = int(os.getenv("PLAY_QUEUE_MAX_DEPTH", "16"))
metrics = MetricsRegistry()


# Runtime arbitration is implemented in the focused module.
from app.playback.arbitration import ChimeDescriptor, ChimeRuntime


def _load_chime_runtimes() -> dict:
    """Build the runtime registry. Default: single chime from env.
    CHIMES_CONFIG='[{"name":"kitchen","id":"...","direct_ip":"..."},...]'
    extends it; GROUPS_CONFIG='{"downstairs":["kitchen","hallway"]}' adds
    groups. Both optional - absent means today's single-chime behavior.
    """
    runtimes = {}
    try:
        extra = json.loads(os.getenv("CHIMES_CONFIG", "[]"))
    except (json.JSONDecodeError, TypeError):
        extra = []
    entries = ([{"name": "default", "id": CHIME_ID,
                 "direct_ip": CHIME_DIRECT_IP}] if CHIME_ID else []) + extra
    for e in entries:
        if e.get("id"):
            direct_client = DirectChimeClient(
                chime_id=e["id"], direct_ip=e.get("direct_ip", ""))
            runtimes[e["name"]] = ChimeRuntime(
                ChimeDescriptor(e["name"], e.get("id", ""), e.get("direct_ip", "")),
                direct_client=direct_client, metrics=metrics,
                max_depth=QUEUE_MAX_DEPTH)
    return runtimes


chime_runtimes = _load_chime_runtimes()
GROUPS = {}
try:
    GROUPS = json.loads(os.getenv("GROUPS_CONFIG", "{}"))
except (json.JSONDecodeError, TypeError):
    pass


def resolve_targets(target: Optional[str]) -> list:
    """target=name|group|None -> list of ChimeRuntime to play on."""
    if not target or target == "default":
        return [chime_runtimes.get("default")] if "default" in chime_runtimes             else list(chime_runtimes.values())
    if target in GROUPS:
        return [chime_runtimes[n] for n in GROUPS[target] if n in chime_runtimes]
    rt = chime_runtimes.get(target)
    return [rt] if rt else []



protect = ProtectClient()
from app.protect.backends import select_protect_backends
protect_backends = select_protect_backends(
    private=protect,
    official_api_key=os.getenv("PROTECT_API_KEY", ""),
    official_base_url=os.getenv("PROTECT_API_BASE_URL", ""),
)
track_reconciler.delete_nvr = protect_backends.ringtone.delete_ringtone
ringtone_index.bind(protect_backends.ringtone.list_ringtones)
from app.audio.tts import PiperTTS
piper_tts = PiperTTS(PIPER_URL)

# ---------------------------------------------------------------------------
# TTS synthesis (latency-optimized)
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """Stable cache key from text content."""
    h = hashlib.md5(text.encode()).hexdigest()[:12]
    safe = re.sub(r"[^a-z0-9]+", "-", text.lower())[:24].strip("-")
    return f"{safe or 'tts'}-{h}"


_tts_cache_locks: dict[str, asyncio.Lock] = {}


async def synthesize_tts_cached(text: str) -> bytes:
    """Phase 7: disk-backed MP3 cache keyed by normalized text. A repeated
    phrase bypasses Piper synthesis AND ffmpeg encoding entirely."""
    from app.audio.tts import normalized_cache_key
    voice = EDGE_TTS_VOICE if TTS_ENGINE == "edge" else PIPER_VOICE
    key = normalized_cache_key(text, engine=TTS_ENGINE, voice=voice,
                               rate=TTS_RATE, sample_rate=TTS_SAMPLE_RATE,
                               encoder_profile=TTS_ENCODER_PROFILE)
    cache_dir = os.path.join(os.getenv("CACHE_DIR", "/data/cache"), "tts")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{key}.mp3")
    lock = _tts_cache_locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                with open(path, "rb") as f:
                    return f.read()
            mp3 = await synthesize_tts(text)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(mp3)
            os.replace(tmp, path)
            return mp3
    finally:
        if not lock.locked() and not getattr(lock, "_waiters", None):
            _tts_cache_locks.pop(key, None)


async def synthesize_tts(text: str) -> bytes:
    """Render text to MP3 bytes via the configured engine.

    - piper: Wyoming protocol (TCP) to the wyoming-piper container (LAN, lowest
      latency). Returns WAV; converted to MP3 via ffmpeg.
    - edge: Microsoft Edge TTS (cloud, better voices, needs internet).
    """
    t0 = time.monotonic()
    tts_started = time.perf_counter_ns()
    if TTS_ENGINE == "edge":
        # edge-tts is a tiny CLI; import lazily so piper-only installs work
        import edge_tts
        communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE)
        out_tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        await _edge_save(communicate, out_tmp.name)
        encoded = Path(out_tmp.name).read_bytes()
        Path(out_tmp.name).unlink(missing_ok=True)
        from app.audio.tts import EncodedAudio
        data = EncodedAudio(
            encoded,
            tts_ms=(time.perf_counter_ns() - tts_started) / 1_000_000,
        )
    elif TTS_ENGINE == "piper":
        pcm_result = await piper_tts.synthesize_pcm(text)
        from app.audio.tts import trim_leading_pcm_silence
        pcm_started = time.perf_counter_ns()
        pcm, _removed_ms = trim_leading_pcm_silence(
            pcm_result.pcm, sample_rate=pcm_result.sample_rate,
            sample_width=pcm_result.sample_width, channels=pcm_result.channels,
            enabled=TTS_TRIM_LEADING_SILENCE)
        wav = _pcm_to_wav(pcm, rate=pcm_result.sample_rate,
                          width=pcm_result.sample_width,
                          channels=pcm_result.channels)
        pcm_ms = (time.perf_counter_ns() - pcm_started) / 1_000_000
        tts_ms = pcm_result.inference_ms
        # Piper returns WAV; track encoding separately from synthesis.
        encode_started = time.perf_counter_ns()
        encoded = await asyncio.to_thread(_wav_to_mp3, wav)
        from app.audio.tts import EncodedAudio
        data = EncodedAudio(
            encoded,
            encode_ms=(time.perf_counter_ns() - encode_started) / 1_000_000,
            tts_ms=tts_ms,
            pcm_ms=pcm_ms,
        )
    else:
        raise RuntimeError(f"Unsupported TTS_ENGINE={TTS_ENGINE!r}")
    log.info("TTS synthesized %dB in %.2fs", len(data), time.monotonic() - t0)
    return data


def _pcm_to_wav(pcm: bytes, *, rate: int, width: int, channels: int) -> bytes:
    """Package processed PCM for the existing ffmpeg encoder."""
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


async def _edge_save(communicate, path: str) -> None:
    await communicate.save(path)


def _wav_to_mp3(wav: bytes) -> bytes:
    """Convert WAV bytes to mono 64kbps MP3 via ffmpeg (fast, small)."""
    proc_out = subprocess_run_ffmpeg(wav)
    return proc_out


def subprocess_run_ffmpeg(audio_in: bytes) -> bytes:
    import subprocess
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-codec:a", "libmp3lame", "-b:a", "64k",
         "-ac", "1", "-ar", "22050", "-f", "mp3", "pipe:1"],
        input=audio_in, capture_output=True, check=True)
    return p.stdout


# ---------------------------------------------------------------------------
# Preset management (upload-once, replay-fast)
# ---------------------------------------------------------------------------

async def resolve_preset_id(name: str) -> str:
    """Resolve from RingtoneIndex; refresh only as not-found recovery."""
    found = ringtone_index.get(name)
    if not found:
        found = await ringtone_index.resolve_or_refresh(name)
    if found:
        return found["id"]
    raise KeyError(f"Preset '{name}' not uploaded yet")


async def create_or_update_preset(
        name: str, mp3: bytes, force: bool = False
) -> str:
    """Upload a preset tone if missing (or force=True to replace); returns its ID."""
    existing = ringtone_index.get(name)
    if not existing and not ringtone_index.loaded:
        existing = await ringtone_index.resolve_or_refresh(name)
    if existing and not force:
        return existing["id"]
    if existing and force:
        await protect.delete_ringtone(existing["id"])
        ringtone_index.invalidate(name)
    # Upload via facade: direct-to-device primary, NVR relay as standby.
    await chime_client.upload_ringtone(name, mp3)
    # Resolve the NVR ringtone ID via the RAM index (one refresh fallback).
    # Playback itself remains NVR-relay: the device only accepts play commands
    # from its paired controller over ucp4 wss.
    created = await ringtone_index.resolve_or_refresh(name)
    if not created:
        raise RuntimeError(f"upload ok but tone '{name}' not found on NVR")

    # Phase 5: register the identity mapping (NVR id known; device filename
    # stays unknown until the storage-mapping experiment).
    rec = track_registry.get(name.lower()) or TrackRecord(name.lower(), "preset")
    rec.nvr_ringtone_id = created["id"]
    track_registry.put(rec)
    return created["id"]


# ---------------------------------------------------------------------------
# WebSocket live-event client (real-time doorbell ring / motion / smart detect)
#
# Wire format (documented from sanitized captured fixtures):
#   - Each websocket message is binary and may link action + data frames.
#   - Each frame has an 8-byte header: type, format, compressed, reserved,
#     then a big-endian u32 payload length. See docs/PROTECT_WEBSOCKET.md.
#   - The observed JSON payload is a change record:
#       {"action": "add|update|remove", "newUpdateId": "...",
#        "modelKey": "event|camera|chime|...", "id": "...", ...}
#   - modelKey=="event" frames are motion/smart-detect/ring events; their `id`
#     can be resolved via GET /proxy/protect/api/events/{id} for full details.
#
# Reconnects forever with capped exponential backoff (2s -> 60s). Events are
# stored in a bounded ring buffer and fanned out to SSE subscribers.
# ---------------------------------------------------------------------------

import json as _json
import ssl as _ssl

import websockets


class ProtectEventStream:
    """Maintains a resilient websocket connection to the NVR event feed."""

    # modelKey values we surface to consumers. Everything else is dropped
    # early to keep memory/CPU flat. Device-state updates are ignored by
    # default but easy to add here if needed.
    INTERESTING_MODELS = ("event", "camera")

    def __init__(self) -> None:
        self.recent: deque = deque(maxlen=EVENTS_BUFFER_MAX)
        self.subscribers: set = set()
        self.connected = False
        self.last_event_at: float = 0.0
        self._last_ring_by_camera: dict[str, int] = {}
        self._task = None
        self._stop = False
        self._rule_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Launch the background keepalive task (idempotent)."""
        if not self._task or self._task.done():
            self._stop = False
            self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        """Signal the background task to exit."""
        self._stop = True
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        for task in tuple(self._rule_tasks):
            task.cancel()
        if self._rule_tasks:
            await asyncio.gather(*self._rule_tasks, return_exceptions=True)
        self._rule_tasks.clear()

    def _rule_task_done(self, task: asyncio.Task) -> None:
        self._rule_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("local rule task failed")

    async def subscribe(self):
        """Register an SSE consumer; returns its dedicated queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q) -> None:
        """Detach a consumer queue."""
        self.subscribers.discard(q)

    async def _get_ws_url(self):
        """Log in over HTTP, read bootstrap.lastUpdateId, build ws URL + auth headers.

        The websocket endpoint authenticates purely via the session cookie
        (plus CSRF header for good measure) captured from the httpx client jar.
        """
        r = await protect._do("GET", "/proxy/protect/api/bootstrap")
        r.raise_for_status()
        last_id = r.json().get("lastUpdateId", "")
        ws_base = UNIFI_HOST.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{ws_base}/proxy/protect/ws/updates?lastUpdateId={last_id}"
        cookies = "; ".join(f"{k}={v}" for k, v in protect._client.cookies.items())
        return url, {"Cookie": cookies}

    async def _run_forever(self) -> None:
        """Keepalive loop: connect, consume, reconnect with backoff."""
        backoff = 2
        while not self._stop:
            try:
                url, headers = await self._get_ws_url()
                # TLS context that skips cert verification (controller uses a
                # self-signed cert). Only used for wss:// hosts.
                ssl_ctx = None
                if UNIFI_HOST.startswith("https://"):
                    ssl_ctx = _ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = _ssl.CERT_NONE
                # websockets>=14 renamed extra_headers -> additional_headers.
                # Pick by version so a requirements bump doesn't break us (a
                # try/except here would fail late with a confusing error).
                from websockets import __version__ as _wsver
                _hdr_key = ("additional_headers"
                            if int(_wsver.split(".")[0]) >= 14 else "extra_headers")
                kw = {"ssl": ssl_ctx, "open_timeout": 10, "compression": None,
                      _hdr_key: headers}
                async with websockets.connect(url, **kw) as ws:
                    log.info("event stream connected")
                    self.connected = True
                    backoff = 2
                    async for raw in ws:
                        action, data = self._parse_frame(raw)
                        if action or data:
                            await self._handle(action, data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("event stream error: %s; retrying in %ss", e, backoff)
            finally:
                self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    from app.protect.events import parse_update_frame as _parse_update_frame
    _parse_frame = staticmethod(_parse_update_frame)

    async def _handle(self, action: dict, data: Optional[dict]) -> None:
        """Phase 9: normalized internal Event handling.

        `action` carries {action, id, modelKey...}; `data` (when parsed) is
        the full changed object including lastRing for doorbells. Legacy
        single-frame sends arrive with data=None and everything in action.
        """
        msg = data if isinstance(data, dict) and data.get("modelKey") else action
        if not isinstance(msg, dict):
            return
        model = msg.get("modelKey", "")
        if model not in self.INTERESTING_MODELS:
            return
        if model == "camera" and not (
            isinstance(data, dict) and data.get("lastRing") is not None
        ):
            return
        merged = dict(data) if isinstance(data, dict) else {}
        merged.update({k: v for k, v in action.items()
                       if k not in merged} if isinstance(action, dict) else {})
        camera_id = merged.get("id") or (action or {}).get("id")
        last_ring = merged.get("lastRing")
        event_name = None
        if model == "camera" and isinstance(last_ring, int) and camera_id:
            previous = self._last_ring_by_camera.get(camera_id)
            if previous is None or last_ring > previous:
                event_name = "doorbell_ring"
                self._last_ring_by_camera[camera_id] = last_ring
        item = {
            "action": merged.get("action") or (action or {}).get("action"),
            "at": time.time(),
            "model": model,
            "event_id": merged.get("id") or (action or {}).get("id"),
            "event": event_name,
            "camera_id": camera_id if model == "camera" else merged.get("camera"),
            "is_event": bool(merged.get("_isEvent")),
            "update_id": merged.get("newUpdateId"),
            "last_ring": last_ring,
        }
        self.recent.append(item)
        self.last_event_at = item["at"]
        # History event objects remain useful enrichment, but camera lastRing is
        # the sole ring gate. Duplicate camera state never re-fires a rule.
        if model == "event" or event_name:
            task = asyncio.create_task(_on_normalized_event(item))
            self._rule_tasks.add(task)
            task.add_done_callback(self._rule_task_done)
        asyncio.get_event_loop().create_task(mqtt_bridge.publish_event(item))
        for q in list(self.subscribers):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass  # slow SSE consumer: drop rather than block the stream
        if item["is_event"] and item["action"] == "add":
            log.info("EVENT: id=%s", item["event_id"])


events = ProtectEventStream()


# ---------------------------------------------------------------------------
# Phase 10: local fast rules engine
#
# Reacts to normalized Protect events INSIDE this process - no HA round trip.
# Rules live in ${DATA_DIR}/rules.json:
#   [{"name": "front-door-ring",
#     "when": {"event": "doorbell_ring", "model": "camera"},
#     "then": {"preset": "front-door"},
#     "cooldown_ms": 250}]
#
# Actions are limited to safe announcement operations (no generic exec).
# ---------------------------------------------------------------------------

from app.rules.engine import RulesEngine

_rules_engine = RulesEngine()


async def _on_normalized_event(event: dict) -> None:
    """Hook called by the event stream for every interesting event."""
    if _rules_engine.rules:
        await _rules_engine.evaluate(event)



# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Security (Phase 0)
# ---------------------------------------------------------------------------

from fastapi import Security, HTTPException as _HTTPException
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(x_api_key: str = Security(_api_key_header)) -> None:
    """Dependency guarding write/diagnostic routes.

    If APP_API_KEY is unset the service runs in OPEN mode (LAN trust) and logs
    a warning at startup; when set, every protected route demands the header
    `X-API-Key: <key>`. Bearer-style Authorization headers are also accepted
    for curl friendliness.
    """
    if not APP_API_KEY:
        return  # open mode - explicitly configured
    provided = x_api_key or ""
    # constant-time compare to avoid timing side-channels
    import hmac as _hmac
    if not _hmac.compare_digest(provided, APP_API_KEY):
        raise _HTTPException(status_code=403, detail="invalid or missing API key")


def guard_destructive(path: str) -> None:
    """Refuse device-destructive endpoints before any network I/O."""
    low = path.lower()
    for d in DESTRUCTIVE_ENDPOINTS:
        if low.startswith(d.lower()):
            raise RuntimeError(f"blocked destructive endpoint: {path}")
    for m in DESTRUCTIVE_MARKERS:
        if m in low:
            raise RuntimeError(f"blocked endpoint matching denylist marker '{m}': {path}")

# Public paths that never require the API key (read-only health/status).
DEBUG_TIMINGS = _settings.debug_timings


@app.middleware("http")
async def timing_middleware(request, call_next):
    """Phase 2 observability: attach X-Process-Time-ms to every response;
    log structured stage timings for announce-family endpoints."""
    import time as _time
    t0 = _time.monotonic()
    response = await call_next(request)
    ms = (_time.monotonic() - t0) * 1000.0
    if DEBUG_TIMINGS:
        response.headers["X-Process-Time-ms"] = f"{ms:.1f}"
    if DEBUG_TIMINGS and request.url.path in ("/announce", "/buzzer",
                                              "/play-default"):
        log.info("TIMING %s %s -> %.1fms", request.method,
                 request.url.path, ms)
    return response


PUBLIC_PATHS = {"/health", "/chime", "/chime/settings", "/chime/direct-info",
                "/events/recent", "/events/stream", "/openapi.json", "/docs",
                "/openapi.json"}


@app.middleware("http")
async def api_key_guard(request, call_next):
    """Phase 0 security gate: when APP_API_KEY is set, every mutating request
    (POST/PUT/PATCH/DELETE) and the sensitive /chime/direct-log diagnostic must
    present header X-API-Key matching the configured value. Read-only status
    endpoints stay open for dashboards. If APP_API_KEY is empty the service
    runs in trusted-LAN open mode.
    """
    path = request.url.path
    is_sensitive = request.method != "GET" or path == "/chime/direct-log"
    if APP_API_KEY and is_sensitive:
        import hmac as _hmac2
        provided = request.headers.get("x-api-key", "")
        if not _hmac2.compare_digest(provided, APP_API_KEY):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "invalid or missing API key"},
                                status_code=403)
    return await call_next(request)




class AnnounceRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    volume: Optional[int] = Field(None, ge=0, le=100)
    repeat_times: Optional[int] = Field(None, ge=1, le=6)
    profile: Optional[str] = None
    target: Optional[str] = None
    priority: int = Field(PRIORITY_NORMAL, ge=0, le=100)
    dedupe_key: Optional[str] = None


def request_services(request: Request) -> AppServices:
    """Resolve dependencies from the active application service container."""
    return request.app.state.services


def dispatch_response(result) -> JSONResponse:
    """Translate canonical dispatch dispositions to REST semantics."""
    status = {
        "suppressed": 202,
        "failed": 502,
        "partial": 207,
    }.get(result.disposition, 200)
    return JSONResponse(content=result.response(), status_code=status)


def command_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RuntimeError) and str(exc) == "no chime targets are configured":
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


class PresetCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-z0-9][a-z0-9\-]{1,48}$",
                      description="kebab-case preset name, e.g. package-delivered")
    text: Optional[str] = Field(None, max_length=500,
                                description="Text to synthesize (if no audio provided)")
    force: bool = False


# ---------------------------------------------------------------------------
# Routes — ordered by expected call frequency
# ---------------------------------------------------------------------------

@app.get("/health")
async def health(request: Request) -> dict:
    """Cached component health; performs no external calls on the probe path."""
    return request_services(request).health.snapshot()


@app.get("/version")
async def version() -> dict:
    """Build identity and evidence-backed protocol compatibility."""
    return {
        "service": "unifi-announcer",
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "tested_firmware": {
            "protect": ["7.2.105"],
            "smart_chime": ["1.7.20"],
        },
        "protocols": {
            "protect_rest": "production_private_api",
            "event_stream": "experimental",
            "direct_device_http": "experimental_read_only_and_staging",
            "direct_ucp4": "research_disconnected",
            "mqtt": "optional",
        },
    }


@app.get("/metrics/json")
async def metrics_json(request: Request) -> dict:
    """Process-local counters and stage histograms; no external I/O."""
    return request_services(request).metrics.snapshot()


@app.get("/cache/ringtones/status")
async def ringtone_cache_status(request: Request) -> dict:
    return request_services(request).ringtone_index.status()


@app.post("/cache/ringtones/refresh")
async def ringtone_cache_refresh(request: Request) -> dict:
    """Admin-only refresh; disabled rather than open when no key is set."""
    if not APP_API_KEY:
        raise HTTPException(status_code=503, detail="admin API key is not configured")
    index = request_services(request).ringtone_index
    await index.refresh()
    return index.status()


@app.post("/announce")
async def announce(req: AnnounceRequest, request: Request):
    """Synthesize text and play it immediately through the chime's TTS slot.

    Latency path: TTS render → slot overwrite upload → play. Typically 2–5s
    depending on engine. The same text is served instantly from the slot
    cache if unchanged (md5-keyed).
    """
    try:
        result = await request_services(request).dispatcher.dispatch(announce_command(
            req.text, volume=req.volume, repeat_times=req.repeat_times,
            profile=req.profile, target=req.target, priority=req.priority,
            dedupe_key=req.dedupe_key, source="api",
        ))
        return dispatch_response(result)
    except Exception as e:
        log.exception("announce failed")
        raise command_error(e)


@app.post("/presets/{name}/play")
async def play_preset(request: Request, name: str,
                      volume: Optional[int] = Query(None, ge=0, le=100),
                      repeat_times: Optional[int] = Query(None, ge=1, le=6),
                      profile: Optional[str] = Query(None),
                      priority: int = Query(PRIORITY_NORMAL, ge=0, le=100),
                      target: Optional[str] = Query(None)):
    """Play a named preset tone on the optional chime/group target."""
    try:
        result = await request_services(request).dispatcher.dispatch(preset_command(
            name, volume=volume, repeat_times=repeat_times, profile=profile,
            priority=priority, target=target,
            source="api"))
        return dispatch_response(result)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise command_error(e)


@app.put("/presets/{name}")
async def create_preset(name: str, body: PresetCreate) -> dict:
    """Create/update a preset: synthesizes `text` and uploads it under this name."""
    if body.name != name:
        raise HTTPException(status_code=400, detail="name mismatch with URL")
    try:
        mp3 = await synthesize_tts_cached(body.text or name.replace("-", " "))
        rid = await create_or_update_preset(name, mp3, force=body.force)
        return {"preset": name, "ringtone_id": rid}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/presets")
async def list_presets() -> dict:
    """List custom (non-default) ringtones registered on the NVR."""
    try:
        tones = [t for t in await protect.list_ringtones() if not t.get("isDefault")]
        return {"presets": tones}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/chime")
async def chime_info() -> dict:
    """Chime diagnostics (device state, tracks)."""
    try:
        chimes = await protect.list_chimes()
        target = next((c for c in chimes if c.get("_id") == CHIME_ID or c.get("id") == CHIME_ID), None)
        if not target:
            return {"configured_chime_found": False, "chimes": [
                {"id": c.get("_id") or c.get("id"), "name": c.get("name")} for c in chimes]}
        return {"configured_chime_found": True,
                "name": target.get("name"), "state": target.get("state"),
                "volume": target.get("volume"),
                "tracks": target.get("speakerTrackList")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# Buzzer, default-track playback, and chime configuration routes
# ---------------------------------------------------------------------------

@app.post("/buzzer")
async def buzzer(request: Request, target: Optional[str] = Query(None)):
    """Fire the chime's piezo buzzer on the optional chime/group target."""
    try:
        result = await request_services(request).dispatcher.dispatch(
            buzzer_command(target=target, source="api"))
        return dispatch_response(result)
    except Exception as e:
        raise command_error(e)


@app.post("/play-default")
async def play_default(request: Request,
                       volume: Optional[int] = Query(None, ge=0, le=100),
                       repeat_times: Optional[int] = Query(None, ge=1, le=6),
                       profile: Optional[str] = Query(None),
                       priority: int = Query(PRIORITY_NORMAL, ge=0, le=100),
                       target: Optional[str] = Query(None)):
    """Play the assigned default ringtone on the optional chime/group target."""
    try:
        result = await request_services(request).dispatcher.dispatch(default_command(
            volume=volume, repeat_times=repeat_times, profile=profile,
            priority=priority, target=target, source="api"))
        return dispatch_response(result)
    except Exception as e:
        raise command_error(e)


@app.get("/chime/settings")
async def chime_settings() -> dict:
    """Full chime config: default track, volume, per-camera ringSettings."""
    try:
        c = await protect.get_chime()
        # Surface the fields that matter for config; speakerTrackId naming varies
        # across Protect versions so we probe both known keys.
        return {"id": c.get("id") or c.get("_id"), "name": c.get("name"),
                "state": c.get("state"),
                "default_volume": c.get("volume"),
                "default_ringtone_id": c.get("speakerTrackId") or c.get("ringtoneId"),
                "camera_ids": c.get("cameraIds"),
                "ring_settings": c.get("ringSettings"),
                "tracks": c.get("speakerTrackList")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class RingSetting(BaseModel):
    """One per-camera ring assignment inside PATCH /chime/settings."""
    cameraId: str = Field(..., description="Protect camera UUID")
    ringtoneId: Optional[str] = Field(None, description="Ringtone UUID; omit/null = default")
    volume: int = Field(50, ge=0, le=100)
    repeatTimes: int = Field(1, ge=1, le=6)


class ChimePatch(BaseModel):
    """Optional-fields PATCH body; anything omitted is left untouched on the device."""
    name: Optional[str] = Field(None, max_length=60)
    volume: Optional[int] = Field(None, ge=0, le=100,
                                  description="Default playback volume")
    ringSettings: Optional[list[RingSetting]] = Field(
        None, description="Per-camera tone assignments (doorbell -> ringtone/volume/repeat)")


@app.patch("/chime/settings")
async def update_chime_settings(patch: ChimePatch) -> dict:
    """Update chime config. Most useful: ringSettings for per-doorbell tones."""
    # Drop keys the caller omitted so we never overwrite device values by accident.
    body = {k: v for k, v in patch.dict(exclude_none=True).items()}
    if not body:
        raise HTTPException(status_code=400, detail="empty patch")
    try:
        updated = await protect.patch_chime(body)
        return {"updated": True, "name": updated.get("name"),
                "volume": updated.get("volume"),
                "ring_settings": updated.get("ringSettings")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# Live-event routes (websocket-backed)
# ---------------------------------------------------------------------------

@app.get("/events/recent")
async def events_recent(limit: int = Query(20, ge=1, le=100)) -> dict:
    """Last N ring/motion/smart-detect events seen on the wire (ring buffer)."""
    items = list(events.recent)[-limit:]
    items.reverse()  # newest first
    return {"connected": events.connected, "count": len(items), "events": items}


@app.get("/events/stream")
async def events_stream():
    """Server-Sent Events feed of live doorbell/doorbell-related events.

    Consume with: `curl -N http://<host>:8095/events/stream`. Each SSE data
    line is one JSON event (same shape as /events/recent items). Home
    Assistant's rest/sse integration or a small shim can turn these into
    instant automations without polling.
    """
    from fastapi.responses import StreamingResponse

    q = await events.subscribe()

    async def gen():
        try:
            # Emit an initial comment so clients see the connection is alive.
            yield ": connected\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {_json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # heartbeat keeps proxies from closing
        finally:
            events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


# (legacy on_event startup removed - handled by lifespan)


@app.post("/reboot")
async def reboot(confirm: bool = Query(False,
                 description="Must be true to actually fire the reboot")) -> dict:
    """Reboot the chime remotely (~30-60s offline). Guarded by ?confirm=true.

    The device-side endpoint accepts any body and reboots unconditionally, so
    this route deliberately requires an explicit query flag to prevent an
    accidental curl from taking the doorbell chime down.
    """
    if not confirm:
        raise HTTPException(status_code=428,
            detail="Refusing to reboot without ?confirm=true (chime goes offline ~60s)")
    try:
        return await protect.reboot()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/chime/direct-info")
async def chime_direct_info() -> dict:
    """Device info straight from the chime hardware (primary direct path).

    Shows which path served the response (`via`) - useful for verifying the
    direct link works without waiting for a play/announce call to fall back.
    """
    try:
        return await chime_client.info()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/chimes")
async def list_chimes() -> dict:
    """Phase 11: multi-chime/group registry (no secrets)."""
    return {
        "chimes": [{"name": n, "id": r.desc.chime_id,
                    "queue_depth": r.queue.depth,
                    "direct_path": bool(r.desc.direct_ip),
                    "capability_state": r.capability_state}
                   for n, r in chime_runtimes.items()],
        "groups": GROUPS,
    }


@app.get("/chime/capabilities")
async def chime_capabilities() -> dict:
    """Return sanitized, isolated capability state for every chime."""
    return {
        "chimes": [
            {
                "name": name,
                "direct_configured": runtime.direct_client is not None,
                "capabilities": runtime.capability_state,
            }
            for name, runtime in chime_runtimes.items()
        ],
        "ringtone_index_loaded": ringtone_index.loaded,
        "track_registry": track_registry.stats(),
    }


@app.get("/chime/direct-log")
async def chime_direct_log(tail: int = Query(200, ge=1, le=5000)) -> dict:
    """Last N lines of the chime's own log buffer (direct device API).

    Great for debugging WiFi issues, firmware chatter, and confirming tone
    uploads landed on device flash.
    """
    try:
        text = await chime_client.direct.support_log()
        lines = text.split("\n")
        return {"via": "direct", "total_lines": len(lines),
                "lines": lines[-tail:]}
    except Exception as e:
        # Fallback: no NVR equivalent for device logs, so surface the error
        # plus the last known direct-path failure reason.
        raise HTTPException(status_code=502,
                            detail=f"{e}; last_direct_error={chime_client.last_direct_error}")


# ---------------------------------------------------------------------------
# Phase 14: quiet hours & named volume profiles
#
# QUIET_HOURS="22:00-06:30" suppresses PRIORITY_INFO and PRIORITY_NORMAL
# announcements during the window (doorbell/emergency still play).
# VOLUME_PROFILES='{"night": {"volume": 25}, "day": {"volume": 60}}' gives
# API callers a shorthand via "profile": "night".
# ---------------------------------------------------------------------------

QUIET_HOURS = os.getenv("QUIET_HOURS", "")   # e.g. "22:00-06:30"


def _in_quiet_hours(now: Optional[time.struct_time] = None) -> bool:
    if not QUIET_HOURS or "-" not in QUIET_HOURS:
        return False
    now = now or time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    start_s, end_s = QUIET_HOURS.split("-")
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    start, end = sh * 60 + sm, eh * 60 + em
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end      # window crosses midnight


def _apply_profile(payload: dict) -> dict:
    """Resolve 'profile': name -> volume/repeat defaults from VOLUME_PROFILES."""
    prof_name = payload.get("profile")
    if not prof_name:
        return payload
    try:
        profiles = json.loads(os.getenv("VOLUME_PROFILES", "{}"))
        prof = profiles.get(prof_name, {})
        if payload.get("volume") is None:
            payload["volume"] = prof.get("volume")
        if payload.get("repeat") is None:
            payload["repeat"] = prof.get("repeat", 1)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return payload


def _load_volume_profiles() -> dict:
    try:
        value = json.loads(os.getenv("VOLUME_PROFILES", "{}"))
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


from app.playback.policy import PlaybackPolicy

playback_policy = PlaybackPolicy(
    profiles=_load_volume_profiles(),
    volume_default=VOLUME_DEFAULT,
    repeat_default=REPEAT_DEFAULT,
)


dispatcher = AnnouncementDispatcher(
    protect=protect_backends.playback,
    chime=chime_client,
    ringtone_index=ringtone_index,
    synthesize=lambda text: synthesize_tts_cached(text),
    slug=_slug,
    resolve_preset=lambda name: resolve_preset_id(name),
    resolve_targets=resolve_targets,
    profile=_apply_profile,
    quiet=_in_quiet_hours,
    metrics=metrics,
    volume_default=VOLUME_DEFAULT,
    repeat_default=REPEAT_DEFAULT,
    debug_timings=DEBUG_TIMINGS,
    playback_policy=playback_policy,
    track_registry=track_registry,
    track_reconciler=track_reconciler,
)


def _mqtt_discovery_chimes() -> list[dict]:
    discovered = []
    for name, runtime in chime_runtimes.items():
        capability = runtime.capability_state
        firmware = None
        if isinstance(capability, dict):
            firmware = capability.get("firmware") or capability.get("version")
        direct_health = ("unconfigured" if runtime.direct_client is None
                         else capability if isinstance(capability, str)
                         else capability.get("status", "available"))
        discovered.append({
            "name": name,
            "queue_depth": runtime.queue.depth,
            "direct_health": direct_health,
            "firmware": firmware,
            "last_ring": None,
        })
    return discovered


async def _protect_health_check() -> int:
    """Read-only check run only by the background health task."""
    return len(await protect_backends.state.list_chimes())


def _local_health_state() -> dict[str, tuple[str, str]]:
    events_enabled = os.getenv("EVENTS_ENABLED", "true").lower() == "true"
    event_state = (
        ("disabled", "not_configured")
        if not events_enabled
        else (("ok", "connected") if events.connected else ("degraded", "reconnecting"))
    )
    mqtt_state = (
        ("disabled", "not_configured")
        if not mqtt_bridge.url
        else (("ok", "connected") if mqtt_bridge.connected else ("degraded", "reconnecting"))
    )
    direct_states = [
        runtime.capability_state
        for runtime in chime_runtimes.values()
        if runtime.direct_client is not None
    ]
    if not direct_states:
        direct_state = ("disabled", "not_configured")
    elif any(
        isinstance(state, dict) and state.get("status") == "unavailable"
        for state in direct_states
    ):
        direct_state = ("degraded", "nvr_fallback")
    elif all(
        isinstance(state, dict) and state.get("status") == "available"
        for state in direct_states
    ):
        direct_state = ("ok", "available")
    else:
        direct_state = ("unknown", "not_yet_probed")
    return {
        "event_stream": event_state,
        "direct_device": direct_state,
        "mqtt": mqtt_state,
    }


mqtt_bridge.bind(lambda command: dispatcher.dispatch(command))
mqtt_bridge.bind_discovery(_mqtt_discovery_chimes)
_rules_engine.bind(lambda command: dispatcher.dispatch(command), metrics)


@app.get("/rules/status")
async def rules_status(request: Request) -> dict:
    """Return compiled rule health without exposing rule payloads."""
    return request_services(request).rules.status()


@app.post("/rules/reload")
async def rules_reload(request: Request) -> dict:
    """Atomically re-read and validate rules against in-memory runtime state."""
    services = request_services(request)
    return services.rules.load(
        presets=set(services.ringtone_index._by_name),
        targets=set(services.chime_runtimes) | set(GROUPS) | {"default"},
    )


def build_services() -> AppServices:
    """Build the dependency container without constructing network clients."""
    return AppServices(
        protect=protect,
        protect_state=protect_backends.state,
        playback_backend=protect_backends.playback,
        ringtone_backend=protect_backends.ringtone,
        chime=chime_client,
        direct_http=_direct_http,
        events=events,
        chime_runtimes=chime_runtimes,
        track_registry=track_registry,
        track_reconciler=track_reconciler,
        ringtone_index=ringtone_index,
        metrics=metrics,
        rules=_rules_engine,
        mqtt=mqtt_bridge,
        dispatcher=dispatcher,
        synthesize=synthesize_tts_cached,
        health=BackgroundHealth(
            protect_check=_protect_health_check,
            local_state=_local_health_state,
            interval_seconds=float(os.getenv("HEALTH_REFRESH_SECONDS", "30")),
        ),
    )


# ASGI transports may skip lifespan; expose the same dependency container for
# compatibility while lifespan reconstructs it for the live process.
app.state.services = build_services()
