"""Regression tests for the v1.0.2 hardening: save_space escaping/perms,
embed.ly key override, and request timeouts on the upload/download paths."""
import os
import stat

import pytest


def test_save_space_escapes_and_locks_perms(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTION_CONFIG_DIR", str(tmp_path))
    import importlib

    import unpy.auth as auth
    importlib.reload(auth)

    auth.save_space('weird" id\\with\\specials')
    text = auth.CONFIG_FILE.read_text()
    # value is escaped and re-parses to the original string
    import tomllib

    assert tomllib.loads(text)["space_id"] == 'weird" id\\with\\specials'
    if os.name == "posix":
        mode = stat.S_IMODE(auth.CONFIG_FILE.stat().st_mode)
        assert mode == 0o600, oct(mode)
    # restore module for other tests that import the default-config auth
    monkeypatch.delenv("NOTION_CONFIG_DIR", raising=False)
    importlib.reload(auth)


def test_embedly_key_is_overridable(monkeypatch):
    import unpy.utils as utils

    captured = {}

    def fake_get(url, **kw):
        captured["url"] = url
        captured["timeout"] = kw.get("timeout")

        class _R:
            @staticmethod
            def json():
                return {}

        return _R()

    monkeypatch.setattr(utils.requests, "get", fake_get)
    monkeypatch.setenv("EMBEDLY_KEY", "MY_KEY")
    utils.get_embed_data("https://example.com")
    assert "key=MY_KEY" in captured["url"]
    assert captured["timeout"] is not None


def test_upload_and_export_calls_pass_a_timeout():
    # Guards against a regression where a requests/​session write is added
    # back without a timeout (bandit B113).
    import pathlib

    core = pathlib.Path("packages/unpy-core/src/unpy")
    block = (core / "block.py").read_text()
    collection = (core / "collection.py").read_text()
    # export-zip download
    assert "session.get(zip_url, timeout=" in block
    # the two signed-PUT uploads
    assert block.count("requests.put(") == 1
    assert "timeout=" in block.split("requests.put(")[1].split(")")[0]
    assert "timeout=" in collection.split("requests.put(")[1].split(")")[0]
