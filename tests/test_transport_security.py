"""Security tests for the HTTP transport auth layer."""
import asyncio
import os

import pytest

from notion_mcp.transport_http import BearerTokenVerifier


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("NOTION_MCP_AUTH_TOKEN", "s3cret-token-value")


def test_correct_token_accepted():
    v = BearerTokenVerifier()
    assert asyncio.run(v.verify_token("s3cret-token-value")) is not None


def test_wrong_token_rejected():
    v = BearerTokenVerifier()
    assert asyncio.run(v.verify_token("wrong")) is None
    assert asyncio.run(v.verify_token("")) is None
    assert asyncio.run(v.verify_token("s3cret-token-valuE")) is None  # case diff


def test_prefix_of_token_rejected():
    v = BearerTokenVerifier()
    assert asyncio.run(v.verify_token("s3cret")) is None


def test_unset_env_means_open_access_verifier():
    # verifier itself stays permissive when env unset (documented local mode);
    # the bind guard in run_http is what prevents network exposure.
    import notion_mcp.transport_http as th

    os.environ.pop("NOTION_MCP_AUTH_TOKEN", None)
    try:
        v = th.BearerTokenVerifier()
        assert asyncio.run(v.verify_token("anything")) is not None
    finally:
        os.environ["NOTION_MCP_AUTH_TOKEN"] = "s3cret-token-value"


def test_bind_guard_refuses_public_open(monkeypatch):
    import notion_mcp.transport_http as th

    monkeypatch.delenv("NOTION_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("NOTION_TOKEN_V2", "dummy")
    with pytest.raises(SystemExit):
        th.run_http(server=None, host="0.0.0.0", port=8000)


def test_bind_guard_allows_loopback_and_override(monkeypatch):
    import notion_mcp.transport_http as th

    monkeypatch.delenv("NOTION_MCP_AUTH_TOKEN", raising=False)

    class FakeServer:
        def streamable_http_app(self):
            return object()

    called = {}

    def fake_run(app, host, port):
        called["host"] = host

    monkeypatch.setattr("uvicorn.run", fake_run)
    th.run_http(server=FakeServer(), host="127.0.0.1", port=8000)
    assert called["host"] == "127.0.0.1"

    monkeypatch.setenv("NOTION_MCP_ALLOW_OPEN", "1")
    th.run_http(server=FakeServer(), host="0.0.0.0", port=8000)
    assert called["host"] == "0.0.0.0"
