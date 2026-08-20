"""Unit tests for auth.py — token and space resolution logic."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_config(monkeypatch, tmp_path):
    """Redirect config dir to a temp directory and reload auth module."""
    monkeypatch.setenv("NOTION_CONFIG_DIR", str(tmp_path / "notion-py"))
    import importlib
    import notion.auth
    importlib.reload(notion.auth)
    return tmp_path


def _get_auth():
    """Re-import auth module to get fresh classes after reload."""
    import notion.auth
    return notion.auth


class TestResolveToken:
    def test_from_arg(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN_V2", raising=False)
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        auth = _get_auth()
        assert auth.resolve_token("my-token") == "my-token"

    def test_from_env_v2(self, temp_config, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN_V2", "env-token-v2")
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        auth = _get_auth()
        assert auth.resolve_token() == "env-token-v2"

    def test_from_legacy_env(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN_V2", raising=False)
        monkeypatch.setenv("NOTION_TOKEN", "legacy-token")
        auth = _get_auth()
        assert auth.resolve_token() == "legacy-token"

    def test_env_v2_takes_priority_over_legacy(self, temp_config, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN_V2", "v2-token")
        monkeypatch.setenv("NOTION_TOKEN", "legacy-token")
        auth = _get_auth()
        assert auth.resolve_token() == "v2-token"

    def test_arg_takes_priority_over_env(self, temp_config, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN_V2", "env-token")
        auth = _get_auth()
        assert auth.resolve_token("arg-token") == "arg-token"

    def test_from_file(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN_V2", raising=False)
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        auth = _get_auth()
        auth.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        auth.TOKEN_FILE.write_text("file-token-123")
        assert auth.resolve_token() == "file-token-123"

    def test_no_token_raises(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN_V2", raising=False)
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        auth = _get_auth()
        with pytest.raises(auth.AuthError, match="No token found"):
            auth.resolve_token()


class TestResolveSpace:
    def test_from_arg(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_SPACE_ID", raising=False)
        auth = _get_auth()
        assert auth.resolve_space("space-123") == "space-123"

    def test_from_env(self, temp_config, monkeypatch):
        monkeypatch.setenv("NOTION_SPACE_ID", "env-space")
        auth = _get_auth()
        assert auth.resolve_space() == "env-space"

    def test_arg_takes_priority(self, temp_config, monkeypatch):
        monkeypatch.setenv("NOTION_SPACE_ID", "env-space")
        auth = _get_auth()
        assert auth.resolve_space("arg-space") == "arg-space"

    def test_from_config_file(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_SPACE_ID", raising=False)
        auth = _get_auth()
        auth.save_space("config-space-id")
        assert auth.resolve_space() == "config-space-id"

    def test_returns_none_when_unset(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_SPACE_ID", raising=False)
        auth = _get_auth()
        assert auth.resolve_space() is None


class TestSaveSpace:
    def test_creates_config_dir(self, temp_config):
        auth = _get_auth()
        auth.save_space("new-space-id")
        assert auth.CONFIG_FILE.exists()
        content = auth.CONFIG_FILE.read_text()
        assert "new-space-id" in content

    def test_overwrites_existing(self, temp_config):
        auth = _get_auth()
        auth.save_space("first-space")
        auth.save_space("second-space")
        content = auth.CONFIG_FILE.read_text()
        assert "second-space" in content
        assert "first-space" not in content


class TestResolveAuth:
    def test_returns_both(self, temp_config, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN_V2", "my-token")
        monkeypatch.setenv("NOTION_SPACE_ID", "my-space")
        auth = _get_auth()
        cfg = auth.resolve_auth()
        assert cfg["token"] == "my-token"
        assert cfg["space_id"] == "my-space"

    def test_token_required_space_optional(self, temp_config, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN_V2", "my-token")
        monkeypatch.delenv("NOTION_SPACE_ID", raising=False)
        auth = _get_auth()
        cfg = auth.resolve_auth()
        assert cfg["token"] == "my-token"
        assert cfg["space_id"] is None

    def test_raises_without_token(self, temp_config, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN_V2", raising=False)
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        auth = _get_auth()
        with pytest.raises(auth.AuthError):
            auth.resolve_auth()