"""HTTP transport for npy-mcp — Streamable HTTP with Bearer token auth.

Two modes:
  1. NO auth (NOTION_MCP_AUTH_TOKEN unset): open access, for local testing
  2. Bearer token (NOTION_MCP_AUTH_TOKEN set): requests must send
     `Authorization: Bearer <token>` matching the env var

Per-request Notion token: clients can send `X-Notion-Token` header to use
their own Notion session token. Falls back to NOTION_TOKEN_V2 env var.
"""

from __future__ import annotations

import hmac
import os

from pydantic import AnyHttpUrl
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from .server import notion_token_var


class NotionTokenMiddleware:
    """ASGI middleware that extracts X-Notion-Token header and sets contextvar.

    This runs per-request and sets `notion_token_var` so that tool handlers
    can use the client's own Notion token instead of the server's default.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            # X-Notion-Token (case-insensitive — HTTP headers are case-insensitive)
            token = None
            for key, value in headers.items():
                if key == b"x-notion-token":
                    token = value.decode("utf-8")
                    break
            if token:
                notion_token_var.set(token)
        await self.app(scope, receive, send)


class BearerTokenVerifier(TokenVerifier):
    """Verify a Bearer token against NOTION_MCP_AUTH_TOKEN env var."""

    async def verify_token(self, token: str) -> AccessToken | None:
        expected = os.environ.get("NOTION_MCP_AUTH_TOKEN")
        if not expected:
            return AccessToken(
                token=token,
                client_id="anonymous",
                scopes=[],
            )
        if hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
            return AccessToken(
                token=token,
                client_id="notion-client",
                scopes=["notion:read", "notion:write"],
            )
        return None


def run_http(server: MCPServer, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the MCP server over Streamable HTTP transport.

    If NOTION_MCP_AUTH_TOKEN is set, Bearer token auth is enforced.
    Otherwise, the server runs open (no auth) — for local testing.

    Clients can send X-Notion-Token header to use their own Notion session.
    """
    auth_token = os.environ.get("NOTION_MCP_AUTH_TOKEN")

    if not auth_token:
        # Open access + a non-loopback bind would expose full Notion read/write
        # to the network. Refuse unless explicitly overridden.
        loopback = host in ("127.0.0.1", "localhost", "::1")
        allow_open = os.environ.get("NOTION_MCP_ALLOW_OPEN") == "1"
        if not loopback and not allow_open:
            raise SystemExit(
                "Refusing to start unauthenticated MCP server on "
                f"{host}:{port} — this would expose your Notion workspace to "
                "the network.\nSet NOTION_MCP_AUTH_TOKEN to require Bearer "
                "auth, bind to 127.0.0.1 for local-only access, or set "
                "NOTION_MCP_ALLOW_OPEN=1 to accept the risk."
            )

    if auth_token:
        server = _build_authenticated_server(server, host, port)

    # Build the Starlette app and inject our NotionTokenMiddleware
    app = server.streamable_http_app()

    # Wrap with NotionTokenMiddleware so X-Notion-Token is extracted per-request
    wrapped_app = NotionTokenMiddleware(app)

    import uvicorn

    uvicorn.run(wrapped_app, host=host, port=port)


def _build_authenticated_server(base_server: MCPServer, host: str, port: int) -> MCPServer:
    """Build a fresh MCPServer with Bearer auth, copying all tools from base_server."""
    resource_url = AnyHttpUrl(f"http://{host}:{port}/mcp")
    auth = AuthSettings(
        issuer_url=AnyHttpUrl("https://notion-py.local"),
        resource_server_url=resource_url,
        required_scopes=["notion:read"],
    )
    new_mcp = MCPServer(
        "notion-py",
        token_verifier=BearerTokenVerifier(),
        auth=auth,
    )
    base_tm = base_server._tool_manager
    for name, tool in base_tm._tools.items():
        new_mcp.add_tool(
            fn=tool.fn,
            name=name,
            title=tool.title,
            description=tool.description,
            annotations=tool.annotations,
        )
    return new_mcp