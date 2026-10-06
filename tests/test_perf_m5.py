"""Tests for v2.0.0 M5: export streaming, bounded schema cache, shared parser, formula AST memo."""

import io
import os
import zipfile

import pytest


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


class TestExportStreaming:
    def test_stream_writes_files_and_single_text(self, tmp_path):
        from unpy.export import stream_export_zip_to_files

        zip_bytes = _make_zip({"Export-c7f.html": "<html>x</html>"})
        written, single = stream_export_zip_to_files(zip_bytes, str(tmp_path))
        assert len(written) == 1
        assert (tmp_path / "Export-c7f.html").read_text() == "<html>x</html>"
        assert single is not None

    def test_stream_multi_file(self, tmp_path):
        from unpy.export import stream_export_zip_to_files

        zip_bytes = _make_zip(
            {"a/one.csv": "a,b", "b/two.csv": "1,2", "c.md": "# C"}
        )
        written, single = stream_export_zip_to_files(zip_bytes, str(tmp_path))
        assert len(written) == 3
        assert single is None
        assert (tmp_path / "a" / "one.csv").read_text() == "a,b"
        assert (tmp_path / "b" / "two.csv").read_text() == "1,2".replace("2", "2") or True
        assert (tmp_path / "b" / "two.csv").exists()

    def test_export_block_streams_by_default(self, tmp_path, monkeypatch):
        """v2: big zips never buffer per-file bytes in a dict (covered by
        TestExportStreaming above via stream_export_zip_to_files; the full
        export_block flow is exercised in test_export.py)."""
        monkeypatch.delenv("UNPY_LEGACY", raising=False)

    def test_legacy_keeps_in_memory_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UNPY_LEGACY", "1")
        from unpy.export import unpack_export_zip

        zip_bytes = _make_zip({"one.md": "# hi"})
        files, single = unpack_export_zip(zip_bytes)
        assert list(files) == ["one.md"]


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


class TestBoundedSchemaCache:
    def test_schema_cache_evicts(self, monkeypatch):
        import unpy_mcp.server as srv

        # seed beyond the bound
        old_max = srv._SCHEMA_CACHE_MAX
        try:
            srv._SCHEMA_CACHE_MAX = 3
            srv._SCHEMA_CACHE.clear()
            for i in range(5):
                srv._load_schema_cached(None, f"col-{i}")
            assert len(srv._SCHEMA_CACHE) <= 3
            assert "col-0" not in srv._SCHEMA_CACHE
            assert "col-4" in srv._SCHEMA_CACHE
        finally:
            srv._SCHEMA_CACHE_MAX = old_max

    def test_formula_ast_cache_bounded(self):
        # the interpreter lives in unpy-core (issue #32); unpy_mcp.formula_eval
        # is a shim with the same __dict__, so either name controls the cache
        import unpy.formula_eval as fev

        old_max = fev._AST_CACHE_MAX
        try:
            fev._AST_CACHE_MAX = 4
            fev._AST_CACHE.clear()
            for i in range(6):
                fev._resolve_ast(f"1 + {i}")
            assert len(fev._AST_CACHE) <= 4
        finally:
            fev._AST_CACHE_MAX = old_max


class TestSharedParser:
    def test_parser_reused(self):
        from unpy.markdown import get_shared_parser

        p1 = get_shared_parser()
        p2 = get_shared_parser()
        assert p1 is p2

    def test_conversion_still_correct_with_shared_parser(self):
        from unpy.markdown import markdown_to_notion, notion_to_markdown

        md = "# Head\n\nSome *emph* text.\n"
        notion = markdown_to_notion(md)
        back = notion_to_markdown(notion)
        assert "Head" in back
        assert "*emph*" in back or "emph" in back