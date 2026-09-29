"""Tests for triage fixes: issues #18, #19, #20, #21, #22 (v1.3.1)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-core", "src"))
_CORE = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from unpy.block import TodoBlock, CodeBlock, TextBlock
from unpy.operations import build_block_property_update
from unpy.records import Record


# ---- issue #18: non-title block property sets use updateBlockPropertyValue ----


class FakeClient:
    def __init__(self):
        self.submitted = []

    def submit_transaction(self, ops):
        if isinstance(ops, dict):
            ops = [ops]
        self.submitted.extend(ops)


class TestIssue18BlockPropertyOps:
    def _record(self, client, table="block"):
        rec = Record.__new__(Record)
        object.__setattr__(rec, "_client", client)
        object.__setattr__(rec, "_id", "blk1")
        object.__setattr__(rec, "_table", table)
        object.__setattr__(rec, "_callbacks", [])
        return rec

    def test_block_property_set_uses_high_level_op(self):
        client = FakeClient()
        rec = self._record(client)
        rec.set(["properties", "checked"], [["Yes"]])
        assert len(client.submitted) == 1
        op = client.submitted[0]
        assert op["command"] == "updateBlockPropertyValue"
        assert op["path"] == ["properties", "checked"]
        assert op["args"] == {"primitiveOp": {"command": "set", "args": [["Yes"]]}}

    def test_block_title_property_keeps_plain_set(self):
        """title stays a plain set — it is the one path the server still accepts."""
        client = FakeClient()
        rec = self._record(client)
        rec.set(["properties", "title"], [["Hello"]])
        assert len(client.submitted) == 1
        op = client.submitted[0]
        assert op["command"] == "set"
        assert op["path"] == ["properties", "title"]

    def test_non_properties_path_keeps_plain_set(self):
        client = FakeClient()
        rec = self._record(client)
        rec.set(["format", "page_icon"], "📄")
        assert client.submitted[0]["command"] == "set"

    def test_non_block_table_keeps_plain_set(self):
        client = FakeClient()
        rec = self._record(client, table="collection")
        rec.set(["schema", "prop.options"], [])
        assert client.submitted[0]["command"] == "set"

    def test_string_path_keeps_plain_set(self):
        client = FakeClient()
        rec = self._record(client)
        rec.set("format.page_icon", "📄")
        assert client.submitted[0]["command"] == "set"

    def test_todo_checked_via_property_map(self):
        """TodoBlock.checked setter routes through the high-level op."""
        client = FakeClient()
        todo = TodoBlock.__new__(TodoBlock)
        object.__setattr__(todo, "_client", client)
        object.__setattr__(todo, "_id", "blk1")
        todo.checked = True
        assert client.submitted[0]["command"] == "updateBlockPropertyValue"
        assert client.submitted[0]["args"]["primitiveOp"]["args"] == [["Yes"]]

    def test_build_block_property_update_unchanged(self):
        op = build_block_property_update("b1", "p1", [["x"]])
        assert op["command"] == "updateBlockPropertyValue"


# ---- issue #20: CodeBlock.title reads back verbatim text, not the raw list ----


class TestIssue20CodeBlockTitle:
    def _code_block(self, stored_props):
        client = FakeClient()

        class FakeStore:
            _values = {"block": {}}

        cb = CodeBlock.__new__(CodeBlock)
        object.__setattr__(cb, "_client", client)
        object.__setattr__(cb, "_id", "code1")
        cb.__dict__["_store"] = FakeStore()
        return cb

    def test_code_title_reads_plain_text(self):
        from unpy.markdown import notion_to_plaintext

        raw = [["print('hi')"]]
        # api_to_python now flattens the rich-text list
        assert notion_to_plaintext(raw) == "print('hi')"

    def test_code_title_read_via_block(self):
        client = FakeClient()
        cb = CodeBlock.__new__(CodeBlock)
        object.__setattr__(cb, "_client", client)
        object.__setattr__(cb, "_id", "code1")
        cb.__dict__["_caches"] = {}
        # stub the store read
        object.__setattr__(
            cb, "_get_record_data",
            lambda force_refresh=False: {
                "type": "code",
                "properties": {"title": [["  indented = True"]], "language": [["Python"]]},
            },
        )
        assert cb.title == "  indented = True"

    def test_code_title_leading_whitespace_preserved(self):
        from unpy.markdown import notion_to_plaintext

        assert notion_to_plaintext([["    keep"]]) == "    keep"


# ---- issue #19: partial-success reporting in _add_blocks_from_specs -----------

class _FakeChildren:
    def __init__(self, fail_on=None, exc=None):
        self.fail_on = fail_on or set()
        self.exc = exc or RuntimeError("boom")
        self.added = []

    def add_new(self, cls, **kwargs):
        btype = getattr(cls, "_type", str(cls))
        if btype in self.fail_on:
            raise self.exc
        self.added.append((btype, kwargs))


class _FakeParent:
    def __init__(self, children):
        self.children = children


class TestIssue19PartialSuccess:
    def _spec_fn(self):
        from unpy_mcp.server import _add_blocks_from_specs_core

        TYPE_MAP = {
            "text": TextBlock,
            "todo": TodoBlock,
        }
        return lambda parent, specs: _add_blocks_from_specs_core(parent, specs, TYPE_MAP)

    def test_all_success(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(
            parent,
            [{"type": "text", "text": "a"}, {"type": "todo", "text": "b", "checked": True}],
        )
        assert count == 2
        assert failures == []

    def test_one_failure_reports_partial(self):
        fn = self._spec_fn()
        children = _FakeChildren(fail_on={"to_do"}, exc=RuntimeError("400: nope"))
        parent = _FakeParent(children)
        count, failures = fn(
            parent,
            [
                {"type": "text", "text": "one"},
                {"type": "todo", "text": "two", "checked": True},
                {"type": "text", "text": "three"},
            ],
        )
        assert count == 2
        assert len(failures) == 1
        assert "block 2 (todo) failed" in failures[0]
        assert "400: nope" in failures[0]

    def test_unknown_type_falls_back_to_text(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(
            parent,
            [
                {"type": "mystery", "text": "x"},
                {"type": "text", "text": "ok"},
            ],
        )
        assert count == 2
        assert failures == []
        # unknown type rendered with the TextBlock fallback
        assert children.added[0][0] == "to_do" or children.added[0][1]["title"] == "x"


# ---- issue #21: _block_summary defines title_markdown -------------------------


class _FakeBlockForSummary:
    def __init__(self, title_md, title_plain, btype="text", icon=""):
        self.id = "blk1"
        self._title_md = title_md
        self._title_plain = title_plain
        self._btype = btype
        self._icon = icon

    def get_browseable_url(self):
        return "https://notion.so/blk"

    def get(self, path, default=None):
        if path == "format.page_icon":
            return self._icon or default
        if path == "type":
            return self._btype or default
        return default

    @property
    def title(self):
        return self._title_md

    @property
    def title_plaintext(self):
        return self._title_plain


class TestIssue21BlockSummary:
    def test_title_markdown_assigned(self):
        from unpy_mcp.server import _block_summary

        b = _FakeBlockForSummary("**bold**", "bold")
        s = _block_summary(b)
        assert s["title_markdown"] == "**bold**"
        assert s["title"] == "bold"

    def test_no_name_error_on_plain_block(self):
        from unpy_mcp.server import _block_summary

        s = _block_summary(_FakeBlockForSummary("plain", "plain"))
        assert s["title_markdown"] == "plain"

    def test_icon_stripped_from_title(self):
        from unpy_mcp.server import _block_summary

        s = _block_summary(_FakeBlockForSummary("🔥 Title", "🔥 Title", icon="🔥"))
        assert s["title"] == "Title"
        assert s["icon"] == "🔥"

    def test_collection_view_uses_db_name(self):
        import unpy_mcp.server as srv

        b = _FakeBlockForSummary("", "", btype="collection_view")

        def fake_db_name(block):
            return "My DB"

        old = srv._get_inline_db_name
        srv._get_inline_db_name = fake_db_name
        try:
            s = srv._block_summary(b)
        finally:
            srv._get_inline_db_name = old
        assert s["title"] == "My DB"

    def test_exception_tolerant(self):
        from unpy_mcp.server import _block_summary

        class Boom(_FakeBlockForSummary):
            @property
            def title(self):
                raise RuntimeError("nope")

        s = _block_summary(Boom("x", "x"))
        assert s["title_markdown"] == ""


# ---- issue #22: read refresh params ------------------------------------------


class TestIssue22RefreshParams:
    def test_get_page_has_refresh_param(self):
        import inspect
        from unpy_mcp.server import get_page

        sig = inspect.signature(get_page.fn if hasattr(get_page, "fn") else get_page)
        assert "refresh" in sig.parameters
        assert sig.parameters["refresh"].default is True

    def test_get_block_has_refresh_param(self):
        import inspect
        from unpy_mcp.server import get_block

        sig = inspect.signature(get_block.fn if hasattr(get_block, "fn") else get_block)
        assert "refresh" in sig.parameters
        assert sig.parameters["refresh"].default is True

    def test_get_database_has_refresh_param(self):
        import inspect
        from unpy_mcp.server import get_database

        sig = inspect.signature(get_database.fn if hasattr(get_database, "fn") else get_database)
        assert "refresh" in sig.parameters
        assert sig.parameters["refresh"].default is True

    def test_query_database_has_refresh_param(self):
        import inspect
        from unpy_mcp.server import query_database

        sig = inspect.signature(query_database.fn if hasattr(query_database, "fn") else query_database)
        assert "refresh" in sig.parameters
        assert sig.parameters["refresh"].default is True

    def test_export_forces_refresh(self):
        import inspect
        import unpy_mcp.server as srv

        fn = getattr(srv.export, "fn", srv.export)
        src = inspect.getsource(fn)
        assert "force_refresh=True" in src

# ---- issue #23: renderers read properties.checked via the accessor ------------


class _FakeTodoForRender:
    def __init__(self, checked, title="todo text", btype="to_do"):
        self._checked = checked
        self._title_md = title
        self._btype = btype

    def get(self, path, default=None):
        if path == "type":
            return self._btype or default
        return default

    @property
    def checked(self):
        if self._checked == "boom":
            raise RuntimeError("nope")
        return self._checked

    @property
    def title(self):
        return self._title_md


class TestIssue23TodoRender:
    def test_mcp_checked_todo_renders_x(self):
        from unpy_mcp.server import _block_to_markdown

        out = _block_to_markdown(_FakeTodoForRender(True))
        assert out == "- [x] todo text"

    def test_mcp_unchecked_todo_renders_space(self):
        from unpy_mcp.server import _block_to_markdown

        out = _block_to_markdown(_FakeTodoForRender(False))
        assert out == "- [ ] todo text"

    def test_mcp_checked_error_renders_unchecked(self):
        from unpy_mcp.server import _block_to_markdown

        out = _block_to_markdown(_FakeTodoForRender("boom"))
        assert out == "- [ ] todo text"

    def test_cli_checked_todo_renders_x(self):
        from unpy_cli.render import _block_to_markdown as cli_md

        out = cli_md(_FakeTodoForRender(True))
        assert out == "- [x] todo text"

    def test_cli_unchecked_todo_renders_space(self):
        from unpy_cli.render import _block_to_markdown as cli_md

        out = cli_md(_FakeTodoForRender(False))
        assert out == "- [ ] todo text"
