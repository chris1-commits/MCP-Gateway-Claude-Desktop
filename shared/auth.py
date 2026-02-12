"""
Opulent Horizons — API Key Authentication Middleware

ASGI middleware that validates Bearer tokens on HTTP transport.
Reads the expected key from the MCP_API_KEY environment variable.

If MCP_API_KEY is not set, authentication is disabled (local dev).

Usage in server entrypoints:
    from shared.auth import apply_auth_middleware

    app = mcp.streamable_http_app()
    app = apply_auth_middleware(app)
    uvicorn.run(app, ...)
"""

import os
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class APIKeyMiddleware:
    """ASGI middleware that enforces Bearer token authentication."""

    def __init__(self, app: ASGIApp, api_key: str) -> None:
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # Allow health-check / readiness probes without auth
        # Allow /webhooks/ paths (ElevenLabs uses its own HMAC-SHA256 auth)
        if (
            request.url.path in ("/health", "/healthz", "/ready")
            or request.url.path.startswith("/webhooks/")
        ):
            await self.app(scope, receive, send)
            return

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            response = JSONResponse(
                {"error": "Missing or invalid Authorization header. Use: Bearer <API_KEY>"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        token = auth_header[7:]  # Strip "Bearer " prefix
        if token != self.api_key:
            response = JSONResponse(
                {"error": "Invalid API key"},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def apply_auth_middleware(app: ASGIApp) -> ASGIApp:
    """
    Wrap an ASGI app with API key auth if MCP_API_KEY is set.
    Returns the original app unchanged if no key is configured.
    """
    api_key = os.getenv("MCP_API_KEY", "")
    if not api_key:
        return app
    return APIKeyMiddleware(app, api_key)
