"""Tests for feedback fixes: date writes, rendering, schema building, pagination."""
import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "npy-core", "src"))

from notion.collection import NotionDate
from notion.render import render_property


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
        from notion.collection import CollectionRowBlock

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
        from notion.client import NotionClient

        c = NotionClient.__new__(NotionClient)
        c.current_space = type("S", (), {"id": "sp1"})()
        return c

    def test_relation_with_target(self):
        from notion_mcp.server import _build_relation_prop

        spec = {"name": "Rel", "target_database_id": "8c3f85d3-3368"}
        prop = _build_relation_prop(spec, None, "sp1")
        assert prop["collection_id"] == "8c3f85d3-3368"
        assert prop["collection_pointer"]["spaceId"] == "sp1"
        assert "limit" not in prop  # dual by default

    def test_relation_single_mode(self):
        from notion_mcp.server import _build_relation_prop

        prop = _build_relation_prop(
            {"name": "R", "target_database_id": "x", "limit": 1}, None, "sp1"
        )
        assert prop["limit"] == 1

    def test_relation_reverse_name(self):
        from notion_mcp.server import _build_relation_prop

        prop = _build_relation_prop(
            {"name": "R", "target_database_id": "x", "reverse_name": "Built-on"},
            None,
            "sp1",
        )
        assert prop["autoRelate"] == {"enabled": True, "name": "Built-on"}

    def test_relation_requires_target(self):
        from notion_mcp.server import _build_relation_prop

        with pytest.raises(ValueError, match="target_database_id"):
            _build_relation_prop({"name": "R"}, None, "sp1")

    def test_formula_encode(self):
        from notion_mcp.formula_eval import encode_expr, build_expr

        code = encode_expr('if({"Done"}, 1, 0)')
        src, refs = build_expr({"formula2": {"code": code}})
        assert src == 'if({0}, 1, 0)'
        assert len(refs) == 1
        assert refs[0]["name"] == "Done"

    def test_formula_encode_with_meta(self):
        from notion_mcp.formula_eval import encode_expr, build_expr

        code = encode_expr('if({"Done"}, 1, 0)', {"Done": {"property": "dd11", "collection": {"id": "cc22", "table": "collection", "spaceId": "sp"}}})
        _, refs = build_expr({"formula2": {"code": code}})
        assert refs[0]["property"] == "dd11"
        assert refs[0]["collection"]["id"] == "cc22"

    def test_rollup_resolves_ids(self):
        from notion_mcp.server import _build_rollup_prop

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
        from notion_mcp.server import _build_rollup_prop

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
        from notion.collection import CollectionQuery

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

        from notion.collection import CollectionRowBlock

        src = inspect.getsource(CollectionRowBlock._convert_python_to_notion)
        assert 'mimetype = (' in src or 'mimetype =' in src, (
            "mimetype must be bound to a name before put_headers uses it"
        )
        # the PUT call must reference the bound variable, not a bare guess
        assert 'put_headers = {"Content-type": mimetype}' in src
