"""Tests for the comment-only gate (NOTION_ALLOW_COMMENTS, issues lineage:
read-only deployments that still want to post comments without enabling
page-content writes).

Covers the CLI gate helper (_check_comments_enabled) across the three
modes: read-only (reject), comments-only (accept), full write (accept),
plus the config-file paths (comments = true, allow_write = true).
"""

import os

import click
import pytest

FAKE_TOKEN = "test-token-not-real"

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-cli", "src")


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Import unpy_cli with a fake token + isolated config dir."""
    monkeypatch.setenv("NOTION_TOKEN_V2", FAKE_TOKEN)
    monkeypatch.setenv("NOTION_CONFIG_DIR", str(tmp_path))
    for var in ("NOTION_ALLOW_WRITE", "NOTION_ALLOW_COMMENTS"):
        monkeypatch.delenv(var, raising=False)
    from unpy_cli import cli as cli_module

    return cli_module


class TestCommentsGate:
    def test_read_only_rejects(self, cli):
        with pytest.raises(click.exceptions.Exit):
            cli._check_comments_enabled()

    def test_comments_env_accepts(self, cli, monkeypatch):
        monkeypatch.setenv("NOTION_ALLOW_COMMENTS", "1")
        cli._check_comments_enabled()  # no exit

    def test_comments_env_zero_rejects(self, cli, monkeypatch):
        monkeypatch.setenv("NOTION_ALLOW_COMMENTS", "0")
        with pytest.raises(click.exceptions.Exit):
            cli._check_comments_enabled()

    def test_write_env_accepts(self, cli, monkeypatch):
        monkeypatch.setenv("NOTION_ALLOW_WRITE", "1")
        cli._check_comments_enabled()

    def test_config_comments_true_accepts(self, cli, tmp_path):
        (tmp_path / "config.toml").write_text('space_id = "x"\ncomments = true\n')
        cli._check_comments_enabled()

    def test_config_allow_write_true_accepts(self, cli, tmp_path):
        (tmp_path / "config.toml").write_text("allow_write = true\n")
        cli._check_comments_enabled()

    def test_config_without_flags_rejects(self, cli, tmp_path):
        (tmp_path / "config.toml").write_text('space_id = "x"\n')
        with pytest.raises(click.exceptions.Exit):
            cli._check_comments_enabled()

    def test_write_gate_still_rejects_comments_env(self, cli, monkeypatch):
        """The comments opt-in must NOT open full write commands."""
        monkeypatch.setenv("NOTION_ALLOW_COMMENTS", "1")
        assert cli._write_allowed() is False
        with pytest.raises(click.exceptions.Exit):
            cli._check_write_enabled()