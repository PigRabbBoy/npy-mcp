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


# ---- issue #29: create_page without blocks must not raise UnboundLocalError ---


class TestIssue29CreatePageNoBlocks:
    """create_page(blocks="") crashed with UnboundLocalError on `failures`
    AFTER the page was created — page id lost, retries create duplicates."""

    def _drive(self, blocks, add_new=None):
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
                    if add_new:
                        add_new(self, cls, **kwargs)
                    self.added.append(kwargs)
                    return FakePageChild()

            class FakePage:
                id = "page999"

                def __init__(self):
                    self.children = FakeChildren()

                def get_browseable_url(self):
                    return "https://notion.so/page999"

            class FakePageChild(FakePage):
                pass

            page = FakePage()

            class FakeClient:
                def get_block(self, _id):
                    return page

            srv._get_client = lambda: FakeClient()
            result = srv.create_page("pid", "X", icon="☑️", blocks=blocks)
            return result, page
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_no_blocks_returns_page_id(self):
        # the issue repro: no blocks → must succeed, not UnboundLocalError
        result, page = self._drive("")
        assert isinstance(result, str)
        assert "page999" in result
        assert "URL" not in result  # just sanity: no crash placeholder

    def test_no_blocks_id_reported_for_retry_safety(self):
        result, _ = self._drive("")
        assert result == "Created page page999 — https://notion.so/page999"

    def test_invalid_json_still_reports_page_id(self):
        result, _ = self._drive("{not json")
        assert "page999" in result
        assert "invalid blocks JSON" in result
        assert "0 blocks added" in result

    def test_partial_failure_includes_added_count(self):
        # the `added` message from the issue's suggested fix: count + denominator
        def boom(children, cls, **kwargs):
            if getattr(cls, "_type", "") == "to_do":
                raise RuntimeError("400: nope")

        result, page = self._drive(
            json.dumps(
                [
                    {"type": "text", "text": "a"},
                    {"type": "todo", "text": "b"},
                    {"type": "text", "text": "c"},
                ]
            ),
            add_new=boom,
        )
        assert "page999" in result
        assert "added 2 of 3 block(s)" in result
        assert "400: nope" in result

    def test_validation_reject_is_batch_size(self):
        # 3 specs, middle invalid → "added 0 of 3", page id still present
        result, _ = self._drive(
            json.dumps(
                [
                    {"type": "text", "text": "a"},
                    "not-an-object",
                    {"type": "text", "text": "c"},
                ]
            )
        )
        assert "page999" in result
        assert "added 0 of 3 block(s)" in result


# ---- issue #28: query-database silently capped at 100 rows --------------------


class _FakeCollectionQuery:
    """Stands in for CollectionQuery with a scripted query_collection."""

    def __init__(self, collection, collection_view, space_id, **kwargs):
        self.collection = collection
        self.kwargs = kwargs
        self.limit = kwargs.get("limit", 100)
        self._client = collection._client

    def execute(self):
        from unpy.collection import CollectionQuery

        # replicate the real execute() flow by driving the patched methods
        return CollectionQuery.execute(self)


class TestIssue28QueryLimit:
    """Three callers never lifted the default limit=100."""

    def _collection(self, total_rows, reducer_result):
        from unpy.collection import Collection
        from unpy.records import Record

        store_calls = []

        class FakeStore:
            _values = {"block": {}}

            def call_query_collection(self, **kwargs):
                store_calls.append(kwargs)
                return reducer_result

        class FakeClient:
            _store = FakeStore()

        col = Collection.__new__(Collection)
        object.__setattr__(col, "_client", FakeClient())
        object.__setattr__(col, "_id", "col1")
        object.__setattr__(col, "_callbacks", [])
        object.__setattr__(col, "_table", "collection")
        col._store_attach(store_calls, total_rows)
        return col, store_calls

    def test_default_stays_100_backwards_compatible(self):
        # CollectionQuery default must remain sensible
        from unpy.collection import CollectionQuery

        assert CollectionQuery.__init__.__defaults__[-1] == 100

    def test_execute_minus_one_falls_back_to_size_hint(self):
        # issue core: reducer response has sizeHint but no total
        from unpy.collection import CollectionQuery

        q = CollectionQuery.__new__(CollectionQuery)
        q.limit = -1
        q.type = "table"

        class FakeCollection:
            id = "col1"

        q.collection = FakeCollection()
        q.collection_view = type("V", (), {"id": "view1"})()
        q.space_id = "sp1"
        q.search = ""
        q.aggregate = []
        q.aggregations = []
        q.filter = []
        q.sort = []
        q.calendar_by = ""
        q.group_by = ""

        captured = {}

        class FakeClient:
            def query_collection(self, **kwargs):
                captured.update(kwargs)
                if kwargs["limit"] == 0:
                    return {
                        "type": "reducer",
                        "reducerResults": {},
                        "sizeHint": 116,
                        "rowCountStatus": "under",
                    }
                return {"blockIds": [f"row{i}" for i in range(kwargs["limit"])]}

        q._client = FakeClient()
        from unittest.mock import patch

        with patch("unpy.collection.QUERY_RESULT_TYPES", {"table": _FakeQR}):
            result = q.execute()
        # second query must request 116 rows, not stay at -1 (→ 100)
        assert captured["limit"] == 116

    def test_execute_minus_one_no_size_hint_clamps_high(self):
        # neither total nor sizeHint → must still exceed the 100 default
        from unpy.collection import CollectionQuery

        q = CollectionQuery.__new__(CollectionQuery)
        q.limit = -1
        q.type = "table"

        class FakeCollection:
            id = "col1"

        q.collection = FakeCollection()
        q.collection_view = type("V", (), {"id": "view1"})()
        q.space_id = "sp1"
        q.search = ""
        q.aggregate = []
        q.aggregations = []
        q.filter = []
        q.sort = []
        q.calendar_by = ""
        q.group_by = ""

        captured = {}

        class FakeClient:
            def query_collection(self, **kwargs):
                captured.update(kwargs)
                if kwargs["limit"] == 0:
                    return {"type": "reducer", "reducerResults": {}}
                return {"blockIds": [f"row{i}" for i in range(250)]}

        q._client = FakeClient()
        from unittest.mock import patch

        with patch("unpy.collection.QUERY_RESULT_TYPES", {"table": _FakeQR}):
            result = q.execute()
        assert captured["limit"] > 100

    def test_execute_zero_and_negative_size_hint_clamped(self):
        # sizeHint present but 0/None → clamped high, not stuck
        from unpy.collection import CollectionQuery

        for hint in (0, None):
            q = CollectionQuery.__new__(CollectionQuery)
            q.limit = -1
            q.type = "table"

            class FakeCollection:
                id = "col1"

            q.collection = FakeCollection()
            q.collection_view = type("V", (), {"id": "view1"})()
            q.space_id = "sp1"
            q.search = ""
            q.aggregate = []
            q.aggregations = []
            q.filter = []
            q.sort = []
            q.calendar_by = ""
            q.group_by = ""

            captured = {}

            class FakeClient:
                def query_collection(self, **kwargs):
                    captured.update(kwargs)
                    return {"type": "reducer", "reducerResults": {}}

            q._client = FakeClient()
            from unittest.mock import patch

            with patch("unpy.collection.QUERY_RESULT_TYPES", {"table": _FakeQR}):
                result = q.execute()
            assert captured["limit"] > 100

    def test_cli_query_database_passes_limit_through(self):
        # CLI used to slice get_rows()[:limit] → max 100 rows client-side
        import inspect

        from unpy_cli import cli as cli_mod

        src = inspect.getsource(cli_mod.query_database)
        assert "get_rows(limit=limit)" in src
        assert "get_rows()[:limit]" not in src


class _FakeQR:
    """Minimal QueryResult stand-in for execute() tests."""

    _type = "table"

    def __init__(self, collection, result, query):
        self._result = result

    def _get_block_ids(self, result):
        return result.get("blockIds", [])

    def __iter__(self):
        return iter([])


# ---- issue #30: get_database with a collection / data source id ----


class _FakeCollection30:
    """Collection record looked up by its own id (no block in between)."""

    def __init__(self, record):
        self.id = "coll-abc"
        self.name = "Features"
        self._record = record

    def get(self, key, default=None):
        return self._record.get(key, default)

    def get_schema_properties(self):
        return [{"id": "title", "slug": "name", "name": "Name", "type": "title"}]

    def get_rows(self, **kwargs):
        return []


class _FakeClient30:
    """get_block() finds nothing for a collection id; get_collection() does."""

    def __init__(self, collection):
        self._collection = collection

    def get_block(self, block_id, force_refresh=False):
        return None

    def get_collection(self, collection_id, force_refresh=False):
        return self._collection if collection_id == self._collection.id else None


class TestIssue30GetDatabaseByCollectionId:
    """get_database(<collection id>) dereferenced block.id on the None that
    get_block() returned, so following a relation target failed while
    query_database with the same id worked."""

    def _get_database(self, record, **kwargs):
        from unittest.mock import patch

        import unpy_mcp.server as srv

        client = _FakeClient30(_FakeCollection30(record))
        with patch.object(srv, "_get_client", return_value=client):
            return srv.get_database("coll-abc", sample_rows=0, **kwargs)

    def test_collection_id_reports_parent_block_id(self):
        out = self._get_database(
            {"parent_id": "block-xyz", "parent_table": "block",
             "schema": {"title": {"name": "Name", "type": "title"}}}
        )
        assert "block id: block-xyz" in out
        assert "data source id: coll-abc" in out
        assert "**Name** (title)" in out

    def test_collection_id_with_full_schema(self):
        out = self._get_database(
            {"parent_id": "block-xyz", "parent_table": "block",
             "schema": {"title": {"name": "Name", "type": "title"}}},
            full_schema=True,
        )
        assert "## Full schema" in out
        assert "data source id: coll-abc" in out

    def test_collection_without_block_parent_does_not_crash(self):
        out = self._get_database(
            {"parent_id": "space-1", "parent_table": "space",
             "schema": {"title": {"name": "Name", "type": "title"}}}
        )
        assert "block id: (unknown)" in out
        assert "data source id: coll-abc" in out
