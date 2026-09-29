"""Tests for triage fixes: issues #18, #19, #20, #21, #22 (v1.3.1)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-core", "src"))
_CORE = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from unpy.block import (
    BulletedListBlock,
    CalloutBlock,
    CodeBlock,
    TodoBlock,
    TextBlock,
)
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
        # issue #24: unknown types are now rejected up front instead of
        # silently falling back to text — zero writes, per-type error
        assert count == 0
        assert children.added == []
        assert len(failures) == 1
        assert "block 1" in failures[0]
        assert "unknown type 'mystery'" in failures[0]


# ---- issue #24: up-front validation of malformed block specs ------------------


class TestIssue24SpecValidation:
    def _spec_fn(self):
        from unpy_mcp.server import _add_blocks_from_specs_core

        TYPE_MAP = {
            "text": TextBlock,
            "todo": TodoBlock,
            "bulleted_list": BulletedListBlock,
            "code": CodeBlock,
            "callout": CalloutBlock,
        }
        return lambda parent, specs: _add_blocks_from_specs_core(parent, specs, TYPE_MAP)

    def test_non_dict_spec_zero_writes(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(
            parent,
            [{"type": "text", "text": "ok"}, "not-an-object", {"type": "text", "text": "after"}],
        )
        # all-or-nothing for input errors: nothing written
        assert count == 0
        assert children.added == []
        assert len(failures) == 1
        assert "block 2" in failures[0]
        assert "expected an object" in failures[0]
        assert "str" in failures[0]

    def test_blocks_not_a_list(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(parent, {"type": "text"})
        assert count == 0
        assert children.added == []
        assert failures and "JSON array of objects" in failures[0]

    def test_unknown_type_rejected(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(parent, [{"type": "mystery", "text": "x"}])
        assert count == 0
        assert children.added == []
        assert failures and "unknown type 'mystery'" in failures[0]

    def test_non_string_text_rejected(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(
            parent, [{"type": "bulleted_list", "text": {"bad": "object"}}]
        )
        assert count == 0
        assert children.added == []
        assert failures and "'text' must be a string" in failures[0]

    def test_non_bool_checked_rejected(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(
            parent, [{"type": "todo", "text": "x", "checked": "yes"}]
        )
        assert count == 0
        assert failures and "'checked' must be a boolean" in failures[0]

    def test_non_string_icon_language_rejected(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(
            parent,
            [{"type": "callout", "text": "x", "icon": {"bad": 1}}],
        )
        assert count == 0
        assert failures and "'icon' must be a string" in failures[0]

        count, failures = fn(
            _FakeParent(_FakeChildren()),
            [{"type": "code", "text": "x", "language": {"bad": 1}}],
        )
        assert count == 0
        assert failures and "'language' must be a string" in failures[0]

    def test_valid_specs_still_pass_validation(self):
        fn = self._spec_fn()
        children = _FakeChildren()
        parent = _FakeParent(children)
        count, failures = fn(
            parent,
            [
                {"type": "text", "text": "a"},
                {"type": "todo", "text": "b", "checked": True},
                {"type": "code", "text": "c", "language": "python"},
                {"type": "callout", "text": "d", "icon": "x"},
            ],
        )
        assert count == 4
        assert failures == []


# ---- issue #25: local store double-applies content list ops -------------------


class TestIssue25ListOpIdempotency:
    """listAfter/listBefore replayed twice (optimistic mirror in add_new +
    commit replay in submit_transaction) must not duplicate the id."""

    def _store(self):
        from unpy.store import RecordStore

        store = RecordStore.__new__(RecordStore)
        store._values = {"block": {"parent": {"id": "parent", "content": []}}}
        store._role = {"block": {}}
        store._callbacks = {"block": {"parent": []}}
        from threading import Lock

        store._mutex = Lock()
        store._pages_to_refresh = []
        store._records_to_refresh = {}
        store._fetched_at = {"block": {}}
        store._cache_key = None  # no disk cache → _mark_cache_dirty no-ops

        class FakeClient:
            def in_transaction(self):
                return False

        store._client = FakeClient()
        return store

    def test_list_after_append_dedupe(self):
        store = self._store()
        op = {
            "table": "block", "id": "parent", "path": ["content"],
            "command": "listAfter", "args": {"id": "newblock"},
        }
        store.run_local_operation(**op)
        store.run_local_operation(**op)
        assert store._values["block"]["parent"]["content"] == ["newblock"]

    def test_list_after_positional_dedupe(self):
        store = self._store()
        store.run_local_operation(
            table="block", id="parent", path=["content"],
            command="listAfter", args={"id": "newblock", "after": "anchor"},
        )
        # anchor not present locally (server echo of a later insert) —
        # no ValueError, falls back to append
        store.run_local_operation(
            table="block", id="parent", path=["content"],
            command="listAfter", args={"id": "newblock", "after": "anchor"},
        )
        assert store._values["block"]["parent"]["content"] == ["newblock"]

    def test_list_before_dedupe(self):
        store = self._store()
        op = {
            "table": "block", "id": "parent", "path": ["content"],
            "command": "listBefore", "args": {"id": "newblock"},
        }
        store.run_local_operation(**op)
        store.run_local_operation(**op)
        assert store._values["block"]["parent"]["content"] == ["newblock"]

    def test_replay_keeps_position_when_reflowed(self):
        store = self._store()
        store.run_local_operation(
            table="block", id="parent", path=["content"],
            command="listAfter", args={"id": "head"},
        )
        store.run_local_operation(
            table="block", id="parent", path=["content"],
            command="listAfter", args={"id": "a"},
        )
        store.run_local_operation(
            table="block", id="parent", path=["content"],
            command="listAfter", args={"id": "b"},
        )
        # server echo reflows b after "head" (a pre-existing child);
        # b already in list → remove-then-insert, exactly one copy
        store.run_local_operation(
            table="block", id="parent", path=["content"],
            command="listAfter", args={"id": "b", "after": "head"},
        )
        content = store._values["block"]["parent"]["content"]
        assert content == ["head", "b", "a"]
        assert content.count("b") == 1

    def test_real_ids_survive_replay_of_same_op_set(self):
        """Simulates the exact #25 flow: ops buffered + optimistically
        mirrored, then the same ops replayed on commit."""
        store = self._store()
        # record creation mirrors through _update_record (as create_record does)
        store._values["block"].setdefault("newblock", None)
        store._update_record(
            "block", "newblock",
            value={"id": "newblock", "type": "text", "alive": True},
            role="editor",
        )
        ops = [
            {
                "table": "block", "id": "parent", "path": ["content"],
                "command": "listAfter", "args": {"id": "newblock"},
            },
        ]
        store.run_local_operations(ops)  # optimistic mirror in add_new
        store.run_local_operations(ops)  # commit replay
        assert store._values["block"]["parent"]["content"].count("newblock") == 1


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


# ---- issue #26: "Added X of N" denominator counts the batch, not the errors ---


class TestIssue26Denominator:
    """Issue #26: when up-front validation rejects a batch, 'Added 0 of N'
    counted error MESSAGES (the invalid specs), not the submitted batch."""

    def _fake_append(self, blocks_json):
        """Drive the append_blocks tool body with a stubbed client."""
        import importlib

        old = {k: os.environ.get(k) for k in ("NOTION_TOKEN_V2", "NOTION_ALLOW_WRITE")}
        os.environ["NOTION_TOKEN_V2"] = "test-token"
        os.environ["NOTION_ALLOW_WRITE"] = "1"
        try:
            import unpy_mcp.server as srv

            importlib.reload(srv)

            class FakeChildren:
                def __init__(self):
                    self.added = []

                def add_new(self, cls, **kwargs):
                    self.added.append(kwargs)

            class FakePage:
                def __init__(self):
                    self.children = FakeChildren()

            page = FakePage()

            class FakeClient:
                def get_block(self, _id):
                    return page

            srv._get_client = lambda: FakeClient()
            result = srv.append_blocks("pid", blocks_json)  # decorator passes fn through
            return result, page.children.added
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_partial_success_denominator_unchanged(self):
        # runtime failure path must keep the #19 denominator = batch size
        from unpy_mcp.server import _add_blocks_from_specs_core

        children = _FakeChildren(fail_on={"to_do"})
        parent = _FakeParent(children)
        count, failures = _add_blocks_from_specs_core(
            parent,
            [
                {"type": "text", "text": "one"},
                {"type": "todo", "text": "two"},
                {"type": "text", "text": "three"},
            ],
            {"text": TextBlock, "todo": TodoBlock},
        )
        assert (count, len(failures)) == (2, 1)
        # denominator reconstructable from the return: count + len(failures) == 3

    def test_append_blocks_validation_batch_size_not_error_count(self):
        # issue #26 example 1: 3 specs, #2 is not an object → "Added 0 of 3"
        result, added = self._fake_append(
            json.dumps(
                [
                    {"type": "text", "text": "a"},
                    "not-an-object",
                    {"type": "text", "text": "c"},
                ]
            )
        )
        assert added == []
        assert result.startswith("Added 0 of 3 block(s)")
        assert "block 2: expected an object, got str" in result

    def test_append_blocks_multi_invalid_still_batch_size(self):
        # issue #26 example 2: 6 specs, #2-#6 invalid → "Added 0 of 6"
        # (5 error messages, but the batch was 6)
        result, added = self._fake_append(
            json.dumps(
                [
                    {"type": "text", "text": "a"},
                    "not-an-object",
                    {"type": 7, "text": "b"},
                    {"type": "mystery", "text": "c"},
                    {"type": "text", "text": True},
                    {"type": "text", "text": "f", "checked": "yes"},
                ]
            )
        )
        assert added == []
        assert result.startswith("Added 0 of 6 block(s)")
        for frag in ("block 2:", "block 3:", "block 4:", "block 5:", "block 6:"):
            assert frag in result

    def test_non_list_payload_falls_back_to_error_count(self):
        # blocks = "7" parses to a non-list: no batch size to report
        result, added = self._fake_append(json.dumps(7))
        assert added == []
        assert result.startswith("Added 0 of 1 block(s)")
        assert "JSON array of objects" in result

    def test_runtime_failure_message_shape_unchanged(self):
        # non-validation failure keeps the historical wording
        result, _ = self._fake_append(
            json.dumps([{"type": "text", "text": "ok"}]),
        )
        # one clean success → no denominator path at all
        assert result == "Added 1 block(s) to pid"
