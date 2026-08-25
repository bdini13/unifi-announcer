"""Production ASGI composition for REST + optional MCP.

`app.main` remains the existing FastAPI application and source of truth. This
module wraps it so MCP can use a dedicated bearer key and lifecycle without
passing through the REST API-key middleware.
"""
from __future__ import annotations

import hmac
import os
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Header, HTTPException, Response
from starlette.applications import Starlette
from starlette.routing import Mount

from app import main as core


@core.app.get("/auth/check", include_in_schema=True)
async def auth_check(x_api_key: str | None = Header(None, alias="X-API-Key")) -> Response:
    """Harmless API-key validation for client configuration flows."""
    if core.APP_API_KEY and not hmac.compare_digest(x_api_key or "", core.APP_API_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return Response(status_code=204)


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
    )


@asynccontextmanager
async def lifespan(_app: Starlette):
    """Run the existing FastAPI lifespan plus the mounted MCP manager."""
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(core.app.router.lifespan_context(core.app))
        if _mcp_runtime is not None:
            await stack.enter_async_context(_mcp_runtime.server.session_manager.run())
        yield


routes = []
if _mcp_runtime is not None:
    # The MCP app itself uses streamable_http_path="/", so the public URL is
    # exactly /mcp rather than /mcp/mcp.
    routes.append(Mount("/mcp", app=_mcp_runtime.app))
routes.append(Mount("/", app=core.app))

app = Starlette(routes=routes, lifespan=lifespan)
