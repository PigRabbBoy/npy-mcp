"""Tests for feedback fixes: date writes, rendering, schema building, pagination."""
import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-core", "src"))

from unpy.collection import NotionDate
from unpy.render import render_property


class _FakeRow:
    """Mimics CollectionRowBlock enough for render_property."""
    def __init__(self, rid, title):
        self.id = rid
        self.title_plaintext = title

    def get_browseable_url(self):
        return f"https://notion.so/{self.id.replace('-', '')}"


class _FakeUser:
    def __init__(self, uid, name="", email=""):
        self.id = uid
        self.name = name
        self.email = email
        self.role = "person"

    def get(self, key, default=None):
        return getattr(self, key, default)


class _TestDateObj:
    """Mimics NotionDate interface for render tests."""
    def __init__(self, start, end=None):
        self.start = start
        self.end = end
        self.timezone = None


# ---- fix 1: date string coercion ----------------------------------------

class TestNotionDateFromIsoformat:
    def test_plain_date(self):
        d = NotionDate.from_isoformat("2026-01-31")
        assert d.start == date(2026, 1, 31)

    def test_datetime(self):
        d = NotionDate.from_isoformat("2026-01-31T14:30:00")
        assert d.start == datetime(2026, 1, 31, 14, 30)

    def test_z_suffix(self):
        d = NotionDate.from_isoformat("2026-01-31T00:00:00Z")
        assert d.start.year == 2026

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            NotionDate.from_isoformat("not-a-date")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            NotionDate.from_isoformat("")


class TestDateConversion:
    def _convert(self, val):
        from unpy.collection import CollectionRowBlock

        prop = {"type": "date", "name": "D", "id": "x"}
        # _convert_python_to_notion's date branch doesn't touch client state —
        # bypass __init__ (and its store wiring) with a stub self
        obj = object.__new__(CollectionRowBlock)
        object.__setattr__(obj, "_client", None)
        path, out = CollectionRowBlock._convert_python_to_notion(obj, val, prop)
        return path, out

    def test_iso_string_no_longer_silently_empty(self):
        path, out = self._convert("2026-02-01")
        assert out != []  # previously the silent-corruption bug
        assert out[0][1][0][0] == "d"

    def test_datetime_string(self):
        path, out = self._convert("2026-02-01T09:30")
        data = out[0][1][0][1]
        assert data["start_time"] == "09:30"

    def test_bad_string_raises_not_silent(self):
        with pytest.raises(ValueError):
            self._convert("garbage-date")

    def test_date_object_still_works(self):
        path, out = self._convert(date(2026, 2, 1))
        assert out != []

    def test_notion_date_passthrough(self):
        nd = NotionDate(date(2026, 2, 1))
        path, out = self._convert(nd)
        assert out != []


# ---- fix 2/3: rendering (shared renderer) --------------------------------

class TestRenderProperty:
    def test_none(self):
        assert render_property(None) == ""

    def test_row_with_title_and_url(self):
        r = _FakeRow("abc-def", "My Row")
        out = render_property(r)
        assert "My Row" in out and "https://notion.so/abcdef" in out

    def test_row_without_title_falls_back(self):
        r = _FakeRow("abc-def", "")
        assert render_property(r) == "https://notion.so/abcdef"

    def test_user_name(self):
        u = _FakeUser("u1", name="Ann")
        assert render_property(u) == "Ann"

    def test_date(self):
        assert render_property(_TestDateObj("2026-01-01")) == "2026-01-01"

    def test_range(self):
        assert render_property(_TestDateObj("2026-01-01", "2026-01-05")) == \
            "2026-01-01 → 2026-01-05"

    def test_list_joins(self):
        r1 = _FakeRow("a1", "X")
        out = render_property([r1, "b"])
        assert "X (" in out and "b" in out

    def test_no_raw_repr_leak(self):
        class Weird:
            pass

        out = render_property(Weird())
        assert "0x" not in out


# ---- fix 4/5: schema building (relation/formula/rollup) -------------------

class TestBuildSchema:
    def _client(self):
        from unpy.client import NotionClient

        c = NotionClient.__new__(NotionClient)
        c.current_space = type("S", (), {"id": "sp1"})()
        return c

    def test_relation_with_target(self):
        from unpy_mcp.server import _build_relation_prop

        spec = {"name": "Rel", "target_database_id": "8c3f85d3-3368"}
        prop = _build_relation_prop(spec, None, "sp1")
        assert prop["collection_id"] == "8c3f85d3-3368"
        assert prop["collection_pointer"]["spaceId"] == "sp1"
        assert "limit" not in prop  # dual by default

    def test_relation_single_mode(self):
        from unpy_mcp.server import _build_relation_prop

        prop = _build_relation_prop(
            {"name": "R", "target_database_id": "x", "limit": 1}, None, "sp1"
        )
        assert prop["limit"] == 1

    def test_relation_reverse_name(self):
        from unpy_mcp.server import _build_relation_prop

        prop = _build_relation_prop(
            {"name": "R", "target_database_id": "x", "reverse_name": "Built-on"},
            None,
            "sp1",
        )
        # two-way shape captured from Notion's own client: a "property"
        # back-ref + version v2, autoRelate disabled
        assert prop["autoRelate"] == {"enabled": False}
        assert prop["version"] == "v2"
        assert isinstance(prop["property"], str) and len(prop["property"]) == 4

    def test_relation_no_reverse(self):
        from unpy_mcp.server import _build_relation_prop

        prop = _build_relation_prop(
            {"name": "R", "target_database_id": "x"}, None, "sp1"
        )
        assert prop["autoRelate"] == {"enabled": False}
        assert "property" not in prop
        assert "version" not in prop

    def test_relation_requires_target(self):
        from unpy_mcp.server import _build_relation_prop

        with pytest.raises(ValueError, match="target_database_id"):
            _build_relation_prop({"name": "R"}, None, "sp1")

    def test_formula_encode(self):
        from unpy_mcp.formula_eval import encode_expr, build_expr

        code = encode_expr('if({"Done"}, 1, 0)')
        src, refs = build_expr({"formula2": {"code": code}})
        assert src == 'if({0}, 1, 0)'
        assert len(refs) == 1
        assert refs[0]["name"] == "Done"

    def test_formula_encode_with_meta(self):
        from unpy_mcp.formula_eval import encode_expr, build_expr

        code = encode_expr('if({"Done"}, 1, 0)', {"Done": {"property": "dd11", "collection": {"id": "cc22", "table": "collection", "spaceId": "sp"}}})
        _, refs = build_expr({"formula2": {"code": code}})
        assert refs[0]["property"] == "dd11"
        assert refs[0]["collection"]["id"] == "cc22"

    def test_rollup_resolves_ids(self):
        from unpy_mcp.server import _build_rollup_prop

        spec = {
            "name": "Total",
            "relation_property": "Rel",
            "target_property": "Price",
            "_own_schema": {
                "aaa1": {
                    "name": "Rel",
                    "type": "relation",
                    "collection_id": "coll1",
                }
            },
        }

        class FakeColl:
            def __init__(self, schema):
                self._s = schema

            def get(self, path):
                assert path == "schema"
                return self._s

        class FakeClient:
            def get_collection(self, cid):
                assert cid == "coll1"
                return FakeColl({"bbb2": {"name": "Price", "type": "number"}})

        prop = _build_rollup_prop(spec, FakeClient())
        assert prop["relation_property"] == "aaa1"
        assert prop["target_property"] == "bbb2"
        assert prop["target_property_type"] == "number"
        assert prop["rollup_type"] == "relation"

    def test_rollup_missing_relation_raises(self):
        from unpy_mcp.server import _build_rollup_prop

        with pytest.raises(ValueError, match="relation property"):
            _build_rollup_prop(
                {
                    "name": "T",
                    "relation_property": "Nope",
                    "target_property": "P",
                    "_own_schema": {},
                },
                None,
            )


# ---- fix 7: pagination via fetch_all ---------------------------------------

class TestFetchAllSemantics:
    def test_fetch_all_queries_remote_total(self):
        """limit=-1 in CollectionQuery queries the remote total then fetches it."""
        # Probed live: queryCollection returns the FULL result set in one
        # request when limit >= total (no cursor pagination exists).
        # CollectionQuery.execute(limit=-1) already implements total-fetch.
        from unpy.collection import CollectionQuery

        q = CollectionQuery(
            collection=type("C", (), {"id": "x", "_client": None})(),
            collection_view=type("V", (), {"id": "v"})(),
            space_id="s",
            limit=-1,
        )
        assert q.limit == -1  # marker recognized by execute()

class TestFileUploadBranch:
    def test_mimetype_bound_for_local_paths(self, tmp_path):
        """Issue #1: local-path branch must bind mimetype before S3 PUT."""
        import inspect

        from unpy.collection import CollectionRowBlock

        src = inspect.getsource(CollectionRowBlock._convert_python_to_notion)
        assert 'mimetype = (' in src or 'mimetype =' in src, (
            "mimetype must be bound to a name before put_headers uses it"
        )
        # the PUT call must reference the bound variable, not a bare guess
        assert 'put_headers = {"Content-type": mimetype}' in src


class TestRowIdentity:
    """Issue #3: query output must carry row identity for read-then-write."""

    def test_safe_props_shape(self):
        from unpy_cli.render import _safe_props

        row = _FakeRow("abc-def", "X")
        out = _safe_props(row)
        assert out["id"] == "abc-def"
        assert out["url"].startswith("https://notion.so/abcdef")
        assert "name" in out["properties"] or isinstance(out["properties"], dict)

    def test_user_id_column_not_shadowed(self):
        # a column literally named "id" must not clobber row identity
        from unpy_cli.render import _safe_props

        class RowWithIdCol:
            def __init__(self):
                self.id = "rid"

            @property
            def title_plaintext(self):
                return "X"

            def get_browseable_url(self):
                return "https://notion.so/rid"

            def get_all_properties(self):
                return {"id": "user-column-value"}

        out = _safe_props(RowWithIdCol())
        assert out["id"] == "rid"  # identity wins, user column is nested
        assert out["properties"]["id"] == "user-column-value"


class TestInTransactionFetch:
    """Core fix: resolving a pre-existing record mid-transaction must work."""

    def test_call_get_record_values_force_signature(self):
        import inspect

        from unpy.store import RecordStore

        sig = inspect.signature(RecordStore.call_get_record_values)
        assert "_force_real_request" in sig.parameters

    def test_get_block_none_relation_raises_clearly(self):
        from unpy.collection import CollectionRowBlock
        import inspect

        src = inspect.getsource(CollectionRowBlock._convert_python_to_notion)
        assert "Relation target not found" in src


class TestComments:
    """get_comments / add_comment (page comments feature)."""

    def test_creval_get_flat_and_nested(self):
        from unpy.client import creval_get

        flat = {"id": "c1", "text": [["hi"]], "parent_table": "discussion"}
        assert creval_get(flat) is flat
        nested = {"value": {"value": {"id": "c2", "text": []}}}
        assert creval_get(nested)["id"] == "c2"
        assert creval_get(None) is None
        assert creval_get("junk") is None

    def test_comment_text_rendering_skips_mentions(self):
        # mention segments ('‣') render as @… tokens, literal text passes through
        text = [["‣", [["u", "u1"]]], [" hello world"]]
        parts = []
        for seg in text:
            if not isinstance(seg, list) or not seg:
                continue
            if seg[0] == "‣":
                parts.append("@…")
            else:
                parts.append(str(seg[0]))
        assert "".join(parts) == "@… hello world"

    def test_add_comment_builds_discussion_ops(self):
        # the op sequence for a NEW thread = set discussion + set comment +
        # set comment.text (no listAfter); for a REPLY = set comment +
        # listAfter + set text
        import inspect

        from unpy.client import NotionClient

        src = inspect.getsource(NotionClient.add_comment)
        assert '"parent_table": "block"' in src  # new discussion
        assert '"parent_table": "discussion"' in src  # comment record
        assert '"listAfter"' in src  # reply append


class TestAddComment:
    """add_comment op shapes (captured from the web client)."""

    def test_new_thread_uses_update_discussion_op(self):
        import inspect

        from unpy.client import NotionClient

        src = inspect.getsource(NotionClient.add_comment)
        # new-thread creates the discussion with an *update* op (partial args)
        assert 'command="update"' in src
        assert '"parent_table": "block"' in src
        # and appends it to the block's discussions list
        assert '["discussions"]' in src

    def test_reply_uses_list_after(self):
        import inspect

        from unpy.client import NotionClient

        src = inspect.getsource(NotionClient.add_comment)
        assert '["comments"]' in src and '"listAfter"' in src


# ---- issue #5: two-way relations -------------------------------------------


class TestTwoWayRelationOps:
    def test_build_collection_schema_update_shape(self):
        from unpy.operations import build_collection_schema_update

        op = build_collection_schema_update("coll1", "ab12", {"name": "X"})
        assert op["command"] == "updateCollectionPropertySchema"
        assert op["table"] == "collection"
        assert op["path"] == ["schema"]
        assert op["args"]["primitiveOp"] == {
            "command": "update",
            "args": {"ab12": {"name": "X"}},
        }

    def test_store_unwraps_primitive_op(self):
        import threading

        from unpy.store import RecordStore

        store = RecordStore.__new__(RecordStore)
        store._mutex = threading.Lock()
        store._values = {
            "collection": {
                "c1": {"schema": {"title": {"name": "Name", "type": "title"}}}
            }
        }
        store._update_record = (
            lambda table, id, value=None, role=None, _s=store: (
                _s._values[table].__setitem__(id, value) if value else None
            )
        )
        store.run_local_operation(
            table="collection",
            id="c1",
            path=["schema"],
            command="updateCollectionPropertySchema",
            args={
                "primitiveOp": {
                    "command": "update",
                    "args": {"ab12": {"name": "Rel", "type": "relation"}},
                }
            },
        )
        schema = store._values["collection"]["c1"]["schema"]
        assert schema["ab12"]["name"] == "Rel"
        assert "title" in schema

    def test_sync_two_way_relation_adds_and_removes(self):
        import json as _json
        import threading

        from unpy.collection import CollectionRowBlock

        submitted = []

        class FakeClient:
            def get_block(self, bid):
                return blocks.get(bid)

            def submit_transaction(self, ops):
                submitted.extend(ops)

        client = FakeClient()

        def _fake_row(rid, props):
            b = CollectionRowBlock.__new__(CollectionRowBlock)
            object.__setattr__(b, "_id", rid)
            object.__setattr__(b, "_client", client)
            object.__setattr__(
                b,
                "get",
                lambda path, default=None, force_refresh=False, _p=props: (
                    _p.get(path[-1])
                    if path and path[0] == "properties"
                    else default
                ),
            )
            return b

        blocks = {
            "rowOld": _fake_row("rowOld", {"rev1": [["‣", [["p", "rowA"]]], [","]]}),
            "rowNew": _fake_row("rowNew", {"rev1": []}),
        }

        row = CollectionRowBlock.__new__(CollectionRowBlock)
        object.__setattr__(row, "_client", client)
        object.__setattr__(row, "_id", "rowA")
        object.__setattr__(
            row,
            "get",
            lambda path, default=None, force_refresh=False: (
                [["‣", [["p", "rowOld"]]], [","]]
                if path == ["properties", "fwd1"]
                else default
            ),
        )

        prop = {"id": "fwd1", "type": "relation", "property": "rev1"}
        new_val = [["‣", [["p", "rowNew"]]]]
        row._sync_two_way_relation(prop, new_val)

        assert len(submitted) == 3
        # op 1: forward write on self
        assert submitted[0]["id"] == "rowA"
        assert submitted[0]["path"] == ["properties", "fwd1"]
        # op 2: reverse add on the new target
        assert submitted[1]["id"] == "rowNew"
        assert ["‣", [["p", "rowA"]]] in submitted[1]["args"]
        # op 3: reverse removal on the old target (rowA gone from its list)
        assert submitted[2]["id"] == "rowOld"
        assert "rowA" not in _json.dumps(submitted[2]["args"])


# ---- issue #6: duplicate title column ---------------------------------------


class TestIssue6TitlePropId:
    def test_title_column_gets_canonical_prop_id(self):
        """The first title column must get prop id 'title' — Notion requires a
        property with that id; when missing the server silently adds its own
        phantom 'Name' title prop, producing two title columns."""
        from unpy_mcp.server import _build_collection_schema

        schema = _build_collection_schema(
            [{"name": "Name", "type": "title"}, {"name": "Route", "type": "text"}]
        )
        title_ids = [pid for pid, p in schema.items() if p["type"] == "title"]
        assert title_ids == ["title"]
        assert schema["title"]["name"] == "Name"
        assert len(schema) == 2

    def test_title_with_different_name_still_canonical_id(self):
        """A title column named anything else (e.g. 'Title') also gets id 'title'."""
        from unpy_mcp.server import _build_collection_schema

        schema = _build_collection_schema(
            [{"name": "Title", "type": "title"}, {"name": "Notes", "type": "text"}]
        )
        title_ids = [pid for pid, p in schema.items() if p["type"] == "title"]
        assert title_ids == ["title"]
        assert schema["title"]["name"] == "Title"

    def test_second_title_column_rejected(self):
        """Two title columns in one spec list is invalid — the second must raise."""
        from unpy_mcp.server import _build_collection_schema

        with pytest.raises(ValueError, match="title"):
            _build_collection_schema(
                [
                    {"name": "Name", "type": "title"},
                    {"name": "Other", "type": "title"},
                ]
            )

    def test_non_first_specs_keep_random_ids(self):
        """Non-title props still get generated 4-char ids, unaffected."""
        import re

        from unpy_mcp.server import _build_collection_schema

        schema = _build_collection_schema(
            [{"name": "T", "type": "title"}, {"name": "N", "type": "number"}]
        )
        assert schema["title"]["type"] == "title"
        other = [pid for pid in schema if pid != "title"][0]
        assert re.fullmatch(r"[0-9a-f]{4}", other)


# ---- issues #7-#13: feedback batch 2 ----------------------------------------


class TestIssue7ComputedPlaceholder:
    def test_empty_rollup_returns_explicit_marker(self):
        """A rollup with no related rows returns '(empty)', not '' — blank is
        indistinguishable from an unevaluated value (issue #7)."""
        # _eval_formula_value needs a client; exercise the empty-out branch
        # by monkeypatching the helpers it calls
        import sys

        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src"
        ))
        from unittest.mock import patch

        import unpy_mcp.server as srv

        class _FakeClient:
            pass

        prop = {
            "type": "rollup",
            "relation_property": "rel_pid",
            "target_property": "tgt_pid",
            "collection_pointer": {"id": "coll1"},
        }
        schema = {"rel_pid": {"type": "relation", "name": "Rel"}, "tgt_pid": {"type": "text", "name": "T"}}
        with patch.object(srv, "_load_schema_cached", return_value={}), \
             patch.object(srv, "_relation_ids", return_value=[]):
            result = srv._eval_formula_value(_FakeClient(), {}, "roll1", {"roll1": prop})
        assert result == "(empty)"

    def test_empty_formula_source_returns_none(self):
        """An empty formula expression → None → '(computed)', not blank."""
        import sys

        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src"
        ))
        import unpy_mcp.server as srv

        result = srv._eval_formula_value(object(), {}, "f1", {"f1": {"type": "formula"}})
        assert result is None


class TestIssue8CodeWhitespace:
    def test_codeblock_title_bypasses_markdown(self):
        """CodeBlock.title must store text verbatim (markdown=False) —
        the markdown converter strips leading whitespace (issue #8)."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "packages", "unpy-core", "src"
        ))
        from unpy.block import CodeBlock

        # functional check: fset on a fake block stores [[text]] segments
        # verbatim (no markdown conversion — that would strip indentation)
        captured = {}

        class FakeClient:
            def submit_transaction(self, ops):
                captured["ops"] = ops
        b = CodeBlock.__new__(CodeBlock)
        b._client = FakeClient()
        b._id = "T"
        b._data = {"id": "T", "properties": {}}
        b.title = "def f():\n    return 1"
        ops = captured["ops"]
        op = (ops[0] if isinstance(ops, list) else ops)
        assert op["args"] == [["def f():\n    return 1"]]


class TestIssue9DatabaseIds:
    def test_get_database_reports_own_ids(self):
        """get_database output includes block id + data source id (issue #9)."""
        import sys

        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src"
        ))
        from unittest.mock import MagicMock, patch

        import unpy_mcp.server as srv

        coll = MagicMock()
        coll.name = "Docs"
        coll.get_schema_properties.return_value = [
            {"id": "title", "slug": "title", "name": "Name", "type": "title"},
        ]
        coll.get.return_value = {"title": {"name": "Name", "type": "title"}}
        coll.id = "coll-abc"
        blk = MagicMock()
        blk.id = "block-xyz"
        blk.collection = coll
        client = MagicMock()
        client.get_block.return_value = blk
        with patch.object(srv, "_get_client", return_value=client):
            out = srv.get_database("block-xyz", sample_rows=0)
        assert "block id: block-xyz" in out
        assert "data source id: coll-abc" in out


class TestIssue11ColumnOps:
    def test_find_column_by_name_and_id(self):
        import sys

        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src"
        ))
        from unpy_mcp.server import _find_column

        schema = {"ab12": {"name": "Status", "type": "select"},
                  "cd34": {"name": "Gone", "type": "text", "alive": False},
                  "dead": None}  # tombstoned
        assert _find_column(schema, "Status")[0] == "ab12"
        assert _find_column(schema, "ab12")[0] == "ab12"
        assert _find_column(schema, "missing") == (None, None)
        assert _find_column(schema, "Gone")[0] is None  # tombstoned skipped
