"""Regression tests for server-side hardening: file-root confinement,
the bounded/hashed client cache, and the _block_to_markdown `md` fix."""
import pytest

from unpy_mcp import server as srv


class TestResolveLocalPath:
    def test_path_inside_root_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTION_MCP_FILE_ROOT", str(tmp_path))
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        assert srv._resolve_local_path(str(f)) == str(f.resolve())

    def test_path_outside_root_rejected(self, tmp_path, monkeypatch):
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("NOTION_MCP_FILE_ROOT", str(root))
        outside = tmp_path / "secret.txt"
        outside.write_text("token")
        with pytest.raises(PermissionError):
            srv._resolve_local_path(str(outside))

    def test_traversal_escape_rejected(self, tmp_path, monkeypatch):
        root = tmp_path / "root"
        root.mkdir()
        monkeypatch.setenv("NOTION_MCP_FILE_ROOT", str(root))
        with pytest.raises(PermissionError):
            srv._resolve_local_path(str(root / ".." / "etc_passwd"))

    def test_default_root_is_cwd(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NOTION_MCP_FILE_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "in_cwd.csv"
        f.write_text("x")
        assert srv._resolve_local_path("in_cwd.csv") == str(f.resolve())
        with pytest.raises(PermissionError):
            srv._resolve_local_path(str(tmp_path.parent / "elsewhere"))

    def test_root_slash_allows_anything(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NOTION_MCP_FILE_ROOT", "/")
        f = tmp_path / "anywhere.csv"
        f.write_text("x")
        assert srv._resolve_local_path(str(f)) == str(f.resolve())


class TestClientCache:
    def test_cache_key_is_token_digest(self):
        import hashlib

        assert srv._client_cache_key("abc") == hashlib.sha256(b"abc").hexdigest()
        # raw token must never be usable as a key
        assert "abc" != srv._client_cache_key("abc")

    def test_cache_is_bounded(self, monkeypatch):
        srv._client_cache.clear()
        monkeypatch.setattr(srv, "_CLIENT_CACHE_MAX", 3)

        class _Dummy:
            pass

        # Emulate _get_client's insert+evict discipline.
        for i in range(10):
            key = srv._client_cache_key(f"tok{i}")
            srv._client_cache[key] = _Dummy()
            srv._client_cache.move_to_end(key)
            while len(srv._client_cache) > srv._CLIENT_CACHE_MAX:
                srv._client_cache.popitem(last=False)
        assert len(srv._client_cache) == 3
        srv._client_cache.clear()


class _FakeBlock:
    def __init__(self, btype, title=""):
        self._btype = btype
        self._title = title
        self.id = "blk-1"

    def get(self, key, default=None):
        return self._btype if key == "type" else default

    @property
    def title_plaintext(self):
        return self._title


def test_block_to_markdown_factory_and_link_no_nameerror():
    # Regression: `md` was referenced in the factory / link_to_page branches
    # before assignment, raising NameError on those block types.
    assert srv._block_to_markdown(_FakeBlock("factory", "T")) == "[template factory] T"
    assert srv._block_to_markdown(_FakeBlock("factory", "")) == "[template factory]"
    assert srv._block_to_markdown(_FakeBlock("link_to_page", "P")) == "[link to page] P"
    assert srv._block_to_markdown(_FakeBlock("header", "H")) == "# H"
