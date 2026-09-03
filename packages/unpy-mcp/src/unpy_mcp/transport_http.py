"""HTTP transport for npy-mcp — Streamable HTTP with Bearer token auth.

Two modes:
  1. NO auth (NOTION_MCP_AUTH_TOKEN unset): open access, for local testing
  2. Bearer token (NOTION_MCP_AUTH_TOKEN set): requests must send
     `Authorization: Bearer <token>` matching the env var

Per-request Notion token: clients can send `X-Notion-Token` header to use
their own Notion session token. Falls back to NOTION_TOKEN_V2 env var.

The Streamable HTTP app runs in stateless mode so each request re-resolves
its own token. In stateful mode the SDK froze the token captured on the
`initialize` request for the whole session, so a later `X-Notion-Token` was
ignored and a client that omitted it on the first request silently acted as
the server's own NOTION_TOKEN_V2 identity (a confused-deputy).
"""

from __future__ import annotations

import hmac
import os

from pydantic import AnyHttpUrl
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from .server import notion_token_var

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _transport_security() -> TransportSecuritySettings | None:
    """DNS-rebinding protection for the Streamable HTTP app.

    Returns None unless NOTION_MCP_ALLOWED_HOSTS is set, so the SDK default
    applies: loopback binds get automatic protection with localhost-only
    allowed hosts; other binds are open (they rely on Bearer auth). When the
    server is reachable under a real hostname, set NOTION_MCP_ALLOWED_HOSTS
    to a comma-separated list such as ``mcp.example.com:*,10.0.0.5:*`` to
    keep the protection on for that bind.
    """
    raw = os.environ.get("NOTION_MCP_ALLOWED_HOSTS", "")
    allowed = [h.strip() for h in raw.split(",") if h.strip()]
    if not allowed:
        return None
    origins = [f"{scheme}://{h}" for h in allowed for scheme in ("http", "https")]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed,
        allowed_origins=origins,
    )


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
        loopback = host in LOOPBACK_HOSTS
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

    # Build the Starlette app and inject our NotionTokenMiddleware.
    # `host` must be passed through: without it the SDK assumes 127.0.0.1 and
    # enables DNS-rebinding protection that only accepts localhost Host
    # headers, so a 0.0.0.0 bind answered 421 to every real hostname.
    # `stateless_http=True` re-runs the server per request in the request's
    # context, so the X-Notion-Token set by the middleware binds per request
    # instead of being frozen at session initialize.
    app = server.streamable_http_app(
        host=host,
        transport_security=_transport_security(),
        stateless_http=True,
    )

    # Wrap with NotionTokenMiddleware so X-Notion-Token is extracted per-request
    wrapped_app = NotionTokenMiddleware(app)

    import uvicorn

    uvicorn.run(wrapped_app, host=host, port=port)


def _build_authenticated_server(base_server: MCPServer, host: str, port: int) -> MCPServer:
    """Build a fresh MCPServer with Bearer auth, copying all tools from base_server."""
    resource_url = AnyHttpUrl(f"http://{host}:{port}/mcp")
    auth = AuthSettings(
        issuer_url=AnyHttpUrl("https://unpy-mcp.local"),
        resource_server_url=resource_url,
        required_scopes=["notion:read"],
    )
    new_mcp = MCPServer(
        "unpy-mcp",
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