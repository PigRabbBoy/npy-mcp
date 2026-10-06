"""Regression tests for issues #30, #31, #32, #33, #36, #37, #38, #39 (v2.2.0 batch)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-core", "src"))
_CORE = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src")
_CLI = os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-cli", "src")
for _p in (_CORE, _CLI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from unpy.records import Record


# ---- shared fakes -----------------------------------------------------------


class FakeStore:
    def __init__(self):
        self._values = {
            "block": {},
            "collection": {},
            "collection_view": {},
        }
        self._role = {}
        self._callbacks = {}
        self.submitted = []  # ops passed to submit_transaction

    def call_query_collection(self, **kwargs):
        return kwargs


class FakeClient:
    def __init__(self, space_id="sp1", user_id="u1"):
        self._store = FakeStore()
        self._monitor = None
        self.current_space = type("S", (), {"id": space_id})()
        self.current_user = type("U", (), {"id": user_id})()
        self.submitted = []
        self._store_block_index = {}

    def submit_transaction(self, ops):
        if isinstance(ops, dict):
            ops = [ops]
        self.submitted.extend(ops)

    def get_block(self, _id):
        return self._store_block_index.get(_id) if hasattr(self, "_store_block_index") else None

    def refresh_records(self, **kwargs):
        pass

    def as_atomic_transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def create_record(self, table, parent, **kw):
        import uuid

        rid = str(uuid.uuid4())
        self._store._values.setdefault(table, {})[rid] = {
            "id": rid, "alive": True, **kw,
            "parent_id": parent.id, "parent_table": "collection",
        }
        return rid

    def get_record_data(self, table, _id, **kw):
        return self._store._values.get(table, {}).get(_id)

    def get_collection(self, col_id):
        from unpy.collection import Collection

        data = self._store._values["collection"].get(col_id)
        if data is None:
            return None
        col = Collection.__new__(Collection)
        object.__setattr__(col, "_client", self)
        object.__setattr__(col, "_id", col_id)
        object.__setattr__(col, "_table", "collection")
        object.__setattr__(col, "_callbacks", [])
        return col

    batched_transaction = None  # forces the v1 code path in block spec builder


def _make_collection(client, schema):
    from unpy.collection import Collection

    coll = Collection.__new__(Collection)
    object.__setattr__(coll, "_client", client)
    object.__setattr__(coll, "_id", "col1")
    object.__setattr__(coll, "_table", "collection")
    object.__setattr__(coll, "_callbacks", [])
    client._store._values["collection"]["col1"] = {
        "id": "col1", "schema": schema, "name": "Test DB", "alive": True,
    }
    return coll


# ---- issue #30: get_database with a collection id must not crash ------------


class TestIssue30GetDatabaseCollectionId:
    def _drive(self, get_block_result):
        import importlib

        old = os.environ.get("NOTION_TOKEN_V2")
        os.environ["NOTION_TOKEN_V2"] = "test-token"
        try:
            import unpy_mcp.server as srv

            importlib.reload(srv)
            client = FakeClient()
            coll = _make_collection(client, {"title": {"name": "Name", "type": "title"}})
            object.__setattr__(coll, "name", "Target DB")
            object.__setattr__(
                coll, "get_schema_properties",
                lambda *a, **k: [{"name": "Name", "type": "title", "slug": "title"}],
            )
            object.__setattr__(coll, "get_rows", lambda *a, **k: [])
            client.get_block = lambda _id, **kw: get_block_result
            client.get_collection = lambda _id: coll
            srv._get_client = lambda: client
            return srv.get_database("col-target")
        finally:
            if old is None:
                os.environ.pop("NOTION_TOKEN_V2", None)
            else:
                os.environ["NOTION_TOKEN_V2"] = old

    def test_collection_id_does_not_crash(self):
        # the issue: block is None (collection id) → block.id AttributeError
        out = self._drive(None)
        assert "Test DB" in out
        assert "looked up by data source id" in out

    def test_block_id_still_printed_when_block_exists(self):
        block = type("B", (), {"id": "blk9", "get": lambda self, p, d=None: None})()
        out = self._drive(block)
        assert "block id: blk9" in out


# ---- issue #36: get_database must pass force_refresh ------------------------


class TestIssue36Refresh:
    def test_force_refresh_reaches_get_block(self):
        import importlib

        old = os.environ.get("NOTION_TOKEN_V2")
        os.environ["NOTION_TOKEN_V2"] = "test-token"
        try:
            import unpy_mcp.server as srv

            importlib.reload(srv)
            client = FakeClient()
            from unpy.collection import Collection

            coll = Collection.__new__(Collection)
            object.__setattr__(coll, "_client", client)
            object.__setattr__(coll, "_id", "col-x")
            object.__setattr__(coll, "_table", "collection")
            object.__setattr__(coll, "_callbacks", [])
            object.__setattr__(coll, "name", "DB")
            object.__setattr__(
                coll, "get_schema_properties", lambda *a, **k: []
            )
            calls = {}

            def fake_get_block(_id, force_refresh=False):
                calls["force_refresh"] = force_refresh
                return None  # falls through to get_collection

            client.get_block = fake_get_block
            client.get_collection = lambda _id: coll
            object.__setattr__(coll, "get_rows", lambda *a, **k: [])
            srv._get_client = lambda: client
            srv.get_database("col-x")
            assert calls["force_refresh"] is True
        finally:
            if old is None:
                os.environ.pop("NOTION_TOKEN_V2", None)
            else:
                os.environ["NOTION_TOKEN_V2"] = old


# ---- issue #32: CLI must not import unpy_mcp --------------------------------


class TestIssue32CliOnlyInstall:
    def test_cli_module_imports_without_unpy_mcp(self):
        import importlib.abc

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "unpy_mcp" or name.startswith("unpy_mcp."):
                    raise ModuleNotFoundError(f"blocked: {name}")
                return None

        blocker = Blocker()
        sys.meta_path.insert(0, blocker)
        saved = {k: v for k, v in sys.modules.items() if k.startswith("unpy_mcp")}
        for k in saved:
            del sys.modules[k]
        try:
            from unpy_cli import cli  # noqa: F401
            from unpy.schema import (
                add_column_prop, resolve_collection_for_write,
                build_collection_schema, find_column,
                set_property_description, full_schema_entries,
            )
            from unpy.blocks import add_blocks_from_specs_core, batch_denominator
            from unpy.csv_import import import_csv_impl
            from unpy.views import build_view_payload, list_views
            from unpy.templates import create_template, list_templates
        finally:
            sys.meta_path.remove(blocker)
            sys.modules.update(saved)

    def test_shared_builders_live_in_core(self):
        from unpy import schema, blocks, views, templates, csv_import

        assert hasattr(schema, "build_collection_schema")
        assert hasattr(blocks, "add_blocks_from_specs_core")
        assert hasattr(views, "build_view_payload")
        assert hasattr(templates, "create_template")
        assert hasattr(csv_import, "import_csv_impl")


# ---- issue #33: add-column uses high-level schema ops -----------------------


class TestIssue33AddColumnHighLevelOps:
    def _client_with_collection(self):
        client = FakeClient()
        schema = {
            "title": {"name": "Name", "type": "title"},
            "6404": {"name": "Link", "type": "relation", "collection_id": "target-col"},
        }
        coll = _make_collection(client, schema)
        return client, coll

    def test_text_column_submits_high_level_op(self):
        from unpy.schema import add_column_prop

        client, coll = self._client_with_collection()
        msg, pid = add_column_prop(client, coll, "Notes", "text")
        assert len(client.submitted) == 1
        op = client.submitted[0]
        assert op["command"] == "updateCollectionPropertySchema"
        assert op["id"] == "col1"
        assert op["args"]["primitiveOp"]["args"][pid]["type"] == "text"
        # the whole-schema `set` path (the 400 bug) must NOT appear
        assert not any(o.get("path") == ["schema"] and o.get("command") == "set"
                       for o in client.submitted)

    def test_select_options_built(self):
        from unpy.schema import add_column_prop

        client, coll = self._client_with_collection()
        msg, pid = add_column_prop(
            client, coll, "Status", "select", '["Todo","Done"]'
        )
        prop = client.submitted[0]["args"]["primitiveOp"]["args"][pid]
        assert [o["value"] for o in prop["options"]] == ["Todo", "Done"]
        assert all(o.get("id") for o in prop["options"])

    def test_two_way_relation_writes_both_sides_in_one_tx(self):
        from unpy.schema import add_column_prop

        client, coll = self._client_with_collection()
        target_col = _make_collection(client, {"title": {"name": "N", "type": "title"}})
        client._store_block_index = {}
        client.get_collection = lambda _id: (
            coll if _id == "col1" else target_col
        )
        msg, pid = add_column_prop(
            client, coll, "Features", "relation",
            json.dumps({"target_database_id": "col2", "reverse_name": "Requirements"}),
        )
        # both ops in ONE transaction
        assert len(client.submitted) == 2
        fwd = client.submitted[0]["args"]["primitiveOp"]["args"][pid]
        rev_pid = fwd["property"]
        rev = client.submitted[1]["args"]["primitiveOp"]["args"][rev_pid]
        assert rev["type"] == "relation"
        assert rev["property"] == pid
        assert rev["collection_id"] == "col1"
        assert "reverse 'Requirements'" in msg

    def test_title_rejected(self):
        from unpy.schema import add_column_prop

        client, coll = self._client_with_collection()
        with pytest.raises(ValueError, match="title"):
            add_column_prop(client, coll, "X", "title")

    def test_formula_encoded_with_meta(self):
        from unpy.schema import add_column_prop

        client, coll = self._client_with_collection()
        msg, pid = add_column_prop(
            client, coll, "F", "formula", '{"expression":"if({\\"Link\\"}, 1, 0)"}'
        )
        prop = client.submitted[0]["args"]["primitiveOp"]["args"][pid]
        assert prop["version"] == "v2"
        code = prop["formula2"]["code"]
        # the fpp ref resolves to the Link property id
        fpp = next(seg for seg in code if isinstance(seg, list) and seg and seg[0] == "‣")
        meta = fpp[1][0][1]
        assert meta.get("property") == "6404"


# ---- issue #31: full-schema readback ----------------------------------------


RAW_SCHEMA_31 = {
    "title": {"name": "Name", "type": "title"},
    "ee11": {"name": "Status", "type": "select",
             "description": "Draft → Review → Approved",
             "options": [
                 {"id": "o1", "value": "Draft", "color": "default"},
                 {"id": "o2", "value": "Done", "color": "default"},
             ]},
    "ff22": {"name": "Features", "type": "relation",
             "collection_id": "col-target-99",
             "collection_pointer": {"id": "col-target-99", "table": "collection", "spaceId": "sp1"},
             "property": "rr55", "version": "v2", "autoRelate": {"enabled": False},
             "limit": 1},
    "gg33": {"name": "Total", "type": "rollup",
             "relation_property": "ff22", "target_property": "hh44"},
    "aa66": {"name": "Flag", "type": "formula", "formula2": {"code": [
        'if(', ["‣", [["fpp", {"name": "Status", "property": "ee11",
                                "collection": {"id": "col1", "table": "collection", "spaceId": "sp1"}}]]],
        ',"x","y")',
    ]}},
    "dead": None,  # tombstoned
}

TARGET_SCHEMA = {
    "title": {"name": "N", "type": "title"},
    "hh44": {"name": "Price", "type": "number"},
    "rr55": {"name": "Requirements", "type": "relation",
             "collection_id": "col1", "property": "ff22", "version": "v2",
             "autoRelate": {"enabled": False}},
}


class _FakeCollection:
    def __init__(self, client, schema):
        self._client = client
        self._schema = schema
        self.id = "col1"

    def get(self, path, default=None):
        if path == "schema":
            return self._schema
        return default


class TestIssue31FullSchema:
    def _entries(self, target_schema=None):
        from unittest.mock import patch

        import unpy.schema as sch

        client = FakeClient()
        with patch.object(sch, "fetch_schema", return_value=target_schema or TARGET_SCHEMA):
            return sch.full_schema_entries(_FakeCollection(client, RAW_SCHEMA_31), client)

    def test_entries_cover_every_live_property(self):
        entries = self._entries()
        names = [e["name"] for e in entries]
        assert names == ["Name", "Status", "Features", "Total", "Flag"]
        assert all(e["id"] != "dead" for e in entries)

    def test_description_included(self):
        entries = self._entries()
        status = next(e for e in entries if e["name"] == "Status")
        assert status["description"] == "Draft → Review → Approved"

    def test_formula_refs_as_prop_names(self):
        entries = self._entries()
        flag = next(e for e in entries if e["name"] == "Flag")
        assert 'prop("Status")' in flag["expression"]
        assert "{0}" in flag["raw_expression"]
        assert flag["refs"][0]["property"] == "ee11"

    def test_rollup_names_resolved_against_target(self):
        entries = self._entries()
        roll = next(e for e in entries if e["name"] == "Total")
        assert roll["relation_property"] == "Features"
        assert roll["target_property"] == "Price"
        assert roll["relation_property_id"] == "ff22"
        assert roll["target_property_id"] == "hh44"
        assert roll["aggregation"] == "show_original"

    def test_two_way_relation_reverse_name_shown(self):
        entries = self._entries()
        rel = next(e for e in entries if e["name"] == "Features")
        assert rel["target"] == "col-target-99"
        assert rel["single"] is True
        assert rel["reverse"] == "Requirements"
        assert rel["reverse_id"] == "rr55"

    def test_one_way_relation_reverse_none(self):
        from unittest.mock import patch

        import unpy.schema as sch

        schema = {"title": {"name": "N", "type": "title"},
                  "aa11": {"name": "R", "type": "relation", "collection_id": "c2"}}
        client = FakeClient()
        with patch.object(sch, "fetch_schema", return_value={}):
            entries = sch.full_schema_entries(_FakeCollection(client, schema), client)
        rel = next(e for e in entries if e["name"] == "R")
        assert rel["reverse"] is None

    def test_status_groups_readback(self):
        from unittest.mock import patch

        import unpy.schema as sch

        schema = {"title": {"name": "N", "type": "title"},
                  "ss11": {"name": "Status", "type": "status",
                           "options": [
                               {"id": "o1", "value": "Todo"},
                               {"id": "o2", "value": "Done"},
                           ],
                           "groups": [{"name": "Complete", "options": ["o2"]}]}}
        client = FakeClient()
        entries = sch.full_schema_entries(_FakeCollection(client, schema), client)
        st = next(e for e in entries if e["name"] == "Status")
        assert st["options"] == ["Todo", "Done"]
        assert st["groups"] == [{"name": "Complete", "options": ["Done"]}]

    def test_markdown_render_lines(self):
        from unpy.schema import render_full_schema_markdown

        client = FakeClient()
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "unpy.schema.fetch_schema", return_value=TARGET_SCHEMA
        ):
            lines = render_full_schema_markdown(_FakeCollection(client, RAW_SCHEMA_31), client)
        text = "\n".join(lines)
        assert "prop(\"Status\")" in text
        assert "reverse_name: Requirements" in text
        assert "target_property: Price" in text

    def test_cli_get_database_has_full_schema_flag(self):
        import inspect

        from unpy_cli import cli as cli_mod

        sig = inspect.signature(cli_mod.get_database)
        assert "full_schema" in sig.parameters
        default = sig.parameters["full_schema"].default
        # typer wraps the default in OptionInfo
        default = getattr(default, "default", default)
        assert default is False


# ---- issue #39: set-column-description --------------------------------------


class TestIssue39ColumnDescription:
    def test_sets_description_preserving_all_other_fields(self):
        from unpy.schema import set_property_description

        client = FakeClient()
        schema = {
            "title": {"name": "Name", "type": "title"},
            "ee11": {
                "name": "Status", "type": "select",
                "options": [{"id": "o1", "value": "Draft", "color": "blue"}],
            },
        }
        coll = _make_collection(client, schema)
        pid, old = set_property_description(client, coll, "Status", "help text")
        assert pid == "ee11"
        assert old == ""
        op = client.submitted[0]
        assert op["command"] == "updateCollectionPropertySchema"
        new_prop = op["args"]["primitiveOp"]["args"][pid]
        assert new_prop["description"] == "help text"
        # nothing else changed
        assert new_prop["options"] == schema["ee11"]["options"]
        assert new_prop["name"] == "Status"

    def test_clears_with_empty_string(self):
        from unpy.schema import set_property_description

        client = FakeClient()
        schema = {"title": {"name": "Name", "type": "title"},
                  "ee11": {"name": "Status", "type": "select", "description": "old"}}
        coll = _make_collection(client, schema)
        pid, old = set_property_description(client, coll, "Status", "")
        assert old == "old"
        new_prop = client.submitted[0]["args"]["primitiveOp"]["args"][pid]
        assert new_prop["description"] == ""

    def test_unknown_column_lists_available(self):
        from unpy.schema import set_property_description

        client = FakeClient()
        coll = _make_collection(client, {"title": {"name": "Name", "type": "title"}})
        with pytest.raises(ValueError, match="available"):
            set_property_description(client, coll, "Nope", "x")

    def test_spec_description_honoured_in_build(self):
        from unpy.schema import build_collection_schema

        schema = build_collection_schema([
            {"name": "Status", "type": "select", "options": ["A"], "description": "how to use"},
        ], None, "sp1")
        assert list(schema.values())[0]["description"] == "how to use"

    def test_empty_description_key_writes_empty(self):
        from unpy.schema import build_collection_schema

        schema = build_collection_schema([
            {"name": "A", "type": "text", "description": ""},
        ], None, "sp1")
        assert list(schema.values())[0]["description"] == ""


# ---- issue #37: views -------------------------------------------------------


VIEW_SCHEMA = {
    "title": {"name": "Name", "type": "title"},
    "ee11": {"name": "Status", "type": "select",
             "options": [
                 {"id": "o1", "value": "Draft", "color": "default"},
                 {"id": "o2", "value": "Done", "color": "default"},
             ]},
    "pp22": {"name": "Owner", "type": "person"},
    "dd33": {"name": "Due", "type": "date"},
    "cc44": {"name": "Done", "type": "checkbox"},
}


class TestIssue37Views:
    def _collection(self):
        client = FakeClient()
        return _make_collection(client, VIEW_SCHEMA), client

    def test_translate_filter_select_uses_enum(self):
        from unpy.views import translate_filter, schema_maps

        coll, _ = self._collection()
        raw, names = schema_maps(coll)
        f = translate_filter(
            {"and": [
                {"property": "Status", "is": "Draft"},
                {"property": "Done", "operator": "is", "value": "true"},
            ]},
            raw, names,
        )
        assert f["operator"] == "and"
        c0, c1 = f["filters"]
        assert c0["property"] == "ee11"
        assert c0["filter"] == {"operator": "enum_is", "value": {"type": "exact", "value": "Draft"}}
        assert c1["filter"]["operator"] == "checkbox_is"
        assert c1["filter"]["value"] is True

    def test_translate_filter_person_me(self):
        from unpy.views import translate_filter, schema_maps

        coll, _ = self._collection()
        raw, names = schema_maps(coll)
        f = translate_filter(
            {"property": "Owner", "operator": "is", "value": "me"}, raw, names
        )
        assert f["filters"][0]["filter"] == {"operator": "person_contains",
                                             "value": {"type": "relative", "value": "me"}}

    def test_unknown_option_rejected_before_write(self):
        from unpy.views import translate_filter, schema_maps

        coll, _ = self._collection()
        raw, names = schema_maps(coll)
        with pytest.raises(ValueError, match="option 'Nope' not found"):
            translate_filter({"property": "Status", "is": "Nope"}, raw, names)

    def test_unknown_property_lists_available(self):
        from unpy.views import translate_filter, schema_maps

        coll, _ = self._collection()
        raw, names = schema_maps(coll)
        with pytest.raises(ValueError, match="available"):
            translate_filter({"property": "Nope", "is": "x"}, raw, names)

    def test_status_group_value(self):
        from unpy.views import translate_filter, schema_maps

        client = FakeClient()
        coll = _make_collection(client, {
            "title": {"name": "Name", "type": "title"},
            "ss99": {"name": "Status", "type": "status",
                     "options": [{"id": "o1", "value": "Todo"},
                                 {"id": "o2", "value": "Done"}],
                     "groups": [{"name": "Complete", "options": ["o2"]}]},
        })
        raw, names = schema_maps(coll)
        f = translate_filter(
            {"property": "Status", "operator": "is", "value": {"group": "Complete"}},
            raw, names,
        )
        assert f["filters"][0]["filter"]["value"] == {"type": "is_option", "value": "Done"}

    def test_raw_escape_hatch(self):
        from unpy.views import translate_filter, schema_maps

        coll, _ = self._collection()
        raw, names = schema_maps(coll)
        rawfilter = {"operator": "date_is_relative_to",
                     "value": {"type": "relative", "unit": "week", "value": "surrounding"}}
        f = translate_filter({"property": "Due", "raw": rawfilter}, raw, names)
        assert f["property"] == "dd33"
        assert f["filter"] == rawfilter

    def test_sort_shorthand(self):
        from unpy.views import translate_sort, schema_maps

        coll, _ = self._collection()
        raw, names = schema_maps(coll)
        s = translate_sort("-Due", raw, names)
        assert s == [{"property": "dd33", "direction": "descending"}]

    def test_board_group_by_writes_board_columns_by(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(client, coll, "board", "By status", group_by="Status")
        assert "board_columns_by" in payload["format"]
        assert payload["format"]["board_columns_by"]["property"] == "ee11"

    def test_table_group_by_writes_collection_group_by(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(client, coll, "table", "T", group_by="Status")
        assert "collection_group_by" in payload["format"]

    def test_calendar_requires_date_column(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(client, coll, "calendar", "Cal")
        assert payload["query2"]["calendar_by"] == "dd33"
        # no date column → clear error before write
        client._store._values["collection"]["col1"]["schema"] = {
            "title": {"name": "N", "type": "title"}}
        with pytest.raises(ValueError, match="date column"):
            build_view_payload(client, _make_collection(client, {
                "title": {"name": "N", "type": "title"}}), "calendar", "Cal")

    def test_visible_properties_order_and_hidden_rest(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(
            client, coll, "table", "V",
            properties='["Status","Due"]',
        )
        entries = payload["format"]["table_properties"]
        assert [e["property"] for e in entries[:2]] == ["ee11", "dd33"]
        assert entries[0]["visible"] is True
        # table view: title is FORCED visible; unlisted props hidden
        hidden = {e["property"] for e in entries if not e["visible"]}
        assert hidden == {"pp22", "cc44"}
        title = next(e for e in entries if e["property"] == "title")
        assert title["visible"] is True

    def test_table_title_forced_visible(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(
            client, coll, "table", "V", properties='["Status"]',
        )
        entries = payload["format"]["table_properties"]
        title = next(e for e in entries if e["property"] == "title")
        assert title["visible"] is True

    def test_unknown_view_type(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        with pytest.raises(ValueError, match="available"):
            build_view_payload(client, coll, "chart", "C")


# ---- issue #38: templates ----------------------------------------------------


TEMPLATE_SCHEMA = {
    "title": {"name": "Name", "type": "title"},
    "ee11": {"name": "Status", "type": "select",
             "options": [{"id": "o1", "value": "Draft", "color": "default"}]},
    "ff22": {"name": "Flag", "type": "formula", "formula2": {"code": ["1"]}},
}


class TestIssue38Templates:
    def _collection(self):
        client = FakeClient()
        coll = _make_collection(client, TEMPLATE_SCHEMA)
        return coll, client

    def test_property_defaults_resolved_and_bad_option_rejected(self):
        from unpy.templates import resolve_property_defaults

        coll, _ = self._collection()
        out = resolve_property_defaults(coll, '{"Status":"Draft"}')
        assert out == {"ee11": "Draft"}
        with pytest.raises(ValueError, match="not a valid option"):
            resolve_property_defaults(coll, '{"Status":"Nope"}')

    def test_computed_columns_rejected(self):
        from unpy.templates import resolve_property_defaults

        coll, _ = self._collection()
        with pytest.raises(ValueError, match="computed"):
            resolve_property_defaults(coll, '{"Flag":"1"}')

    def test_unknown_property_rejected_before_write(self):
        from unpy.templates import resolve_property_defaults

        coll, _ = self._collection()
        with pytest.raises(ValueError, match="available"):
            resolve_property_defaults(coll, '{"Nope":"x"}')

    def test_malformed_body_spec_rejected(self):
        from unpy.templates import create_template

        coll, client = self._collection()
        with pytest.raises(ValueError, match="unknown type"):
            create_template(client, coll, "T", blocks='[{"type":"mystery","text":"x"}]')

    def test_list_templates_readback_uses_names(self):
        from unpy.templates import list_templates

        coll, client = self._collection()
        tid = "tmpl1"
        client._store._values["block"][tid] = {
            "id": tid, "type": "page", "is_template": True, "alive": True,
            "parent_id": "col1", "parent_table": "collection",
            "properties": {
                "title": [["Daily"]],
                "ee11": [["Draft"]],
            },
            "content": [],
        }
        client._store._values["collection"]["col1"]["template_pages"] = [tid]
        out = list_templates(coll, client)
        assert len(out) == 1
        assert out[0]["title"] == "Daily"
        assert out[0]["properties"] == {"Status": "Draft"}
        assert out[0]["default"] is False

    def test_legacy_blocks_body_roundtrip(self):
        from unpy.templates import validate_block_specs_specs

        assert validate_block_specs_specs([{"type": "todo", "text": "x", "checked": False}]) == []
        errs = validate_block_specs_specs([{"type": "todo", "text": "x", "checked": "yes"}])
        assert errs and "'checked' must be a boolean" in errs[0]


# ---- issue #40: sort shorthand dropped before translate_sort ----------------


class TestIssue40SortShorthand:
    """String shorthand must reach translate_sort (which parses it), not die
    in build_view_payload's eager json.loads."""

    def _collection(self):
        client = FakeClient()
        coll = _make_collection(client, {
            "title": {"name": "Name", "type": "title"},
            "dd33": {"name": "Due", "type": "date"},
        })
        return coll, client

    def test_shorthand_string_accepted(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(client, coll, "table", "V",
                                     sort_spec="Name,-Due")
        assert payload["query2"]["sort"] == [
            {"property": "title", "direction": "ascending"},
            {"property": "dd33", "direction": "descending"},
        ]

    def test_single_name_shorthand(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(client, coll, "table", "V", sort_spec="Due")
        assert payload["query2"]["sort"] == [
            {"property": "dd33", "direction": "ascending"}]

    def test_json_list_still_works(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        payload = build_view_payload(
            client, coll, "table", "V",
            sort_spec='[{"property":"Due","direction":"descending"}]',
        )
        assert payload["query2"]["sort"] == [
            {"property": "dd33", "direction": "descending"}]

    def test_invalid_property_still_raises_before_write(self):
        from unpy.views import build_view_payload

        coll, client = self._collection()
        with pytest.raises(ValueError, match="sort property"):
            build_view_payload(client, coll, "table", "V", sort_spec="Nope")


# ---- issue #41: template blocks never loaded into a fresh store --------------


class TestIssue41TemplateStoreLoad:
    """find_template_by_name / list_templates read the store directly; a
    fresh client (every CLI call) must fetch the template_pages blocks
    first or every template is silently skipped."""

    def _collection_with_template(self, client, tid="85c493ca-748d-4f32-9513-75060d1f375a", title="Clause"):
        from unpy.collection import Collection

        coll = Collection.__new__(Collection)
        object.__setattr__(coll, "_client", client)
        object.__setattr__(coll, "_id", "col1")
        object.__setattr__(coll, "_table", "collection")
        object.__setattr__(coll, "_callbacks", [])
        client._store._values["collection"]["col1"] = {
            "id": "col1", "schema": TEMPLATE_SCHEMA, "name": "T DB",
            "alive": True, "template_pages": [tid],
        }
        return coll

    def _register_fresh_block(self, client, tid, title):
        """Simulate what syncRecordValues would return — the fake client
        stores it directly when 'refreshed'."""
        TID = "85c493ca-748d-4f32-9513-75060d1f375a"
        assert tid == TID
        data = {
            "id": TID, "type": "page", "is_template": True, "alive": True,
            "parent_id": "col1", "parent_table": "collection",
            "properties": {"title": [[title]]},
            "content": [],
        }

        def refresh_records(**kw):
            for b in kw.get("block", []):
                client._store._values["block"][b] = dict(data)

        client.refresh_records = refresh_records
        return data

    def test_find_template_by_name_fresh_client(self):
        from unpy.templates import find_template_by_name

        client = FakeClient()
        coll = self._collection_with_template(client)
        tid = "85c493ca-748d-4f32-9513-75060d1f375a"
        # nothing in store yet — the bug reported the block as missing
        data = self._register_fresh_block(client, tid, "Clause")
        assert not client._store._values["block"]
        found = find_template_by_name(coll, "Clause")
        assert found is not None
        assert found.id == tid
        loaded = client._store._values["block"][tid]
        assert loaded["is_template"] is True and loaded == data

    def test_find_template_by_name_no_match_after_load(self):
        from unpy.templates import find_template_by_name

        client = FakeClient()
        coll = self._collection_with_template(client)
        self._register_fresh_block(
            client, "85c493ca-748d-4f32-9513-75060d1f375a", "Clause")
        assert find_template_by_name(coll, "Other") in (None,)

    def test_list_templates_fresh_client(self):
        from unpy.templates import list_templates

        client = FakeClient()
        coll = self._collection_with_template(client)
        self._register_fresh_block(client, "85c493ca-748d-4f32-9513-75060d1f375a", "Clause")
        out = list_templates(coll, client)
        assert len(out) == 1
        assert out[0]["id"] == "85c493ca-748d-4f32-9513-75060d1f375a"
        assert out[0]["title"] == "Clause"

    def test_list_templates_empty_pages_no_request(self):
        from unpy.templates import list_templates

        client = FakeClient()
        coll = self._collection_with_template(client, tid="85c493ca-748d-4f32-9513-75060d1f375a", title="x")
        client._store._values["collection"]["col1"]["template_pages"] = []
        called = []
        client.refresh_records = lambda **kw: called.append(kw)
        assert list_templates(coll, client) == []
        assert called == []  # no ids → no syncRecordValues round-trip

    def test_create_template_idempotent_across_processes(self):
        # simulate a second process: store empty, refresh loads the block
        from unittest.mock import patch

        import uuid

        from unpy.templates import create_template

        client = FakeClient()

        def make_record(table, parent, **kw):
            rid = str(uuid.uuid4())
            client._store._values["block"][rid] = {
                "id": rid, "type": "page", "alive": True,
                "parent_id": "col1", "parent_table": "table",
                "properties": {}, "content": [],
            }
            return rid

        client.create_record = make_record
        coll = self._collection_with_template(client)

        # first run: nothing loaded → find fails → row created; register
        # the created row as a template so a second lookup finds it
        created = []

        def submit_transaction(ops):
            ops = ops if isinstance(ops, list) else [ops]
            client.submitted.extend(ops)
            for op in ops:
                if not isinstance(op, dict):
                    continue
                if (op.get("path") == ["template_pages"]
                        and op.get("command") == "listAfter"):
                    new_id = op["args"]["id"]
                    created.append(new_id)
                    client._store._values["block"][new_id] = {
                        "id": new_id, "type": "page",
                        "is_template": True, "alive": True,
                        "parent_id": "col1", "parent_table": "collection",
                        "properties": {"title": [["Clause"]]},
                        "content": [],
                    }

        client.submit_transaction = submit_transaction
        row, msg = create_template(client, coll, "Clause")
        assert row.id in created
        # second "process": pretend store was forgotten, but the template
        # block is loadable (as syncRecordValues would)
        client._store._values["block"] = {}
        tdata = {
            "id": created[0], "type": "page", "is_template": True,
            "alive": True, "parent_id": "col1", "parent_table": "collection",
            "properties": {"title": [["Clause"]]}, "content": [],
        }

        def refresh_records(**kw):
            for b in kw.get("block", []):
                client._store._values["block"][b] = dict(tdata)

        client.refresh_records = refresh_records
        client._store._values["collection"]["col1"]["template_pages"] = created
        with patch.object(type(coll), "add_row") as add_row:
            row2, msg2 = create_template(client, coll, "Clause")
            add_row.assert_not_called()
        assert "updated existing" in msg2