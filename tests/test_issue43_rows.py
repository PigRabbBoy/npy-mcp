"""Tests for batch database-row operations (unpy.unpy.rows, issue #43).

add_rows/update_rows/delete_rows: N rows in one batched transaction —
reusing the single-row setters so schema auto-add and two-way relation
mirroring behave identically, only batched.
"""

from unittest.mock import MagicMock

import pytest

from test_issue43 import (
    B1, P1, T1, T2, _mock_client_with_blocks, _wrap,
)

FAKE_TOKEN = "test-token-not-real"
COL1 = "77777777-7777-4777-8777-777777777777"
R1 = "88888888-8888-4888-8888-888888888888"
R2 = "99999999-9999-4999-8999-999999999999"
R3 = "aaaa0000-0000-4000-8000-000000000000"


def _collection_client(monkeypatch, schema, rows=None):
    """Mock client + a Collection with the given {colname: {type, options}} schema."""
    monkeypatch.setenv("UNPY_LEGACY", "")
    from unpy.client import NotionClient
    from unpy.collection import Collection
    from unpy.utils import slugify

    client = _mock_client_with_blocks(monkeypatch, rows or {})
    collection = Collection(client, COL1)
    client._store._update_record(
        "collection", COL1,
        value={
            "id": COL1,
            "name": [[ "Test DB" ]],
            "schema": {
                # schema ids are 4-char ids in real Notion; slugified names
                # are only the lookup path — use the slug as the id (fine
                # for the resolver)
                slugify(name) or name[:4]: {"name": name, **spec}
                for name, spec in schema.items()
            },
        },
        role="editor",
    )
    # get_schema_property relies on collection.get("schema") — served from
    # the store above; get_block returns the collection's parent page
    def _get_block(url_or_id, force_refresh=False, limit=100):
        from unpy.utils import extract_id
        key = extract_id(url_or_id)
        with client._store._mutex:
            val = client._store._values["block"].get(key)
        if val:
            return _wrap(client, key)
        with client._store._mutex:
            cval = client._store._values["collection"].get(key)
        if cval:
            return collection
        return None

    client.get_block = _get_block
    client.get_record_data = lambda table, id, force_refresh=False, limit=100: (
        client._store.get(table, id, force_refresh=force_refresh, limit=limit)
    )
    # rows' .collection attr resolves via get_collection(parent_id)
    client.get_collection = lambda cid, force_refresh=False: collection
    # collection.parent (block) reads the collection's parent block — serve
    # a minimal page block so add_row's view updates don't explode
    client._store._update_record(
        "block", P1,
        value={"id": P1, "type": "page", "parent_id": "",
               "parent_table": "space", "collection_id": COL1},
        role="editor",
    )
    # fabricate create_record: mint an id, mirror the create ops through
    # the real submit path — which buffers while a transaction is open
    # (in_transaction) just like the real create_record
    created = []

    def _create_record(table, parent, **kwargs):
        rid = f"{len(created):08x}-aaaa-4bbb-8ccc-00000000{len(created):04x}"
        created.append(rid)
        ops = [
            {"id": rid, "path": [], "command": "set", "table": "block",
             "args": {"id": rid, "alive": True, "type": "page",
                      "parent_id": parent.id, "parent_table": "collection"}},
            {"id": parent.id, "path": ["content"], "command": "listAfter",
             "table": "collection", "args": {"id": rid}},
        ]
        if hasattr(client, "_transaction_operations"):
            client._transaction_operations.extend(ops)
            client._store.run_local_operations([op for op in ops if op["command"] != "set"])
            with client._store._mutex:
                client._store._values["block"][rid] = dict(ops[0]["args"])
            client._store._fetched_at["block"][rid] = 0.0
        else:
            client.submit_transaction(ops)
            with client._store._mutex:
                client._store._values["block"][rid] = dict(ops[0]["args"])
            client._store._fetched_at["block"][rid] = 0.0
        return rid

    client.create_record = _create_record
    return client, collection


SCHEMA = {
    "Name": {"type": "title"},
    "Status": {"type": "select", "options": [{"value": "Todo", "color": "default"}]},
    "Points": {"type": "number"},
    "Done": {"type": "checkbox"},
}


class TestAddRows:
    def test_batch_create_two_rows_one_tx(self, monkeypatch):
        client, collection = _collection_client(monkeypatch, SCHEMA)
        from unpy.rows import add_rows

        row_ids, failures = add_rows(client, collection, [
            {"Name": "Row 1", "Status": "Todo"},
            {"Name": "Row 2"},
        ])
        assert failures == []
        assert len(row_ids) == 2
        # create-record ops + property ops all fit in one batched chunk
        assert len(client.submitted) == 1
        ops = client.submitted[0]
        sets = [op for op in ops if op["command"] == "set"]
        assert len(sets) == 2  # two row records created
        title_ops = [op for op in ops if op.get("path") == ["properties", "name"]]
        assert len(title_ops) == 2
        status_ops = [op for op in ops if op.get("path") == ["properties", "status"]]
        assert len(status_ops) == 1 and status_ops[0]["args"]["primitiveOp"]["args"] == [["Todo"]]

    def test_unknown_column_fails_before_write(self, monkeypatch):
        client, collection = _collection_client(monkeypatch, SCHEMA)
        from unpy.rows import add_rows

        row_ids, failures = add_rows(client, collection, [
            {"Name": "ok"},
            {"NoSuchColumn": "x"},
        ])
        assert len(row_ids) == 1
        assert any("NoSuchColumn" in f for f in failures)
        with client._store._mutex:
            bad = [bid for bid, val in client._store._values["block"].items()
                   if val.get("properties", {}).get("title") == [["x"]]]
        assert bad == []  # the bad row was never created

    def test_empty_input(self, monkeypatch):
        client, collection = _collection_client(monkeypatch, SCHEMA)
        from unpy.rows import add_rows

        assert add_rows(client, collection, []) == ([], [])


class TestUpdateRows:
    def test_batch_update_two_rows(self, monkeypatch):
        rows = {
            R1: {"id": R1, "parent_id": COL1, "parent_table": "collection", "type": "page",
                 "properties": {"title": [["old"]]}},
            R2: {"id": R2, "parent_id": COL1, "parent_table": "collection", "type": "page",
                 "properties": {"title": [["old2"]]}},
        }
        client, collection = _collection_client(monkeypatch, SCHEMA, rows)
        from unpy.rows import update_rows

        count, failures = update_rows(client, [
            {"row_id": R1, "properties": {"Name": "First"}},
            {"row_id": R2, "properties": {"Name": "Second", "Done": True}},
        ])
        assert (count, failures) == (2, [])
        assert len(client.submitted) >= 1
        with client._store._mutex:
            v1 = client._store._values["block"][R1]
            v2 = client._store._values["block"][R2]
        # the schema fixture uses slugs as prop ids → writes land on
        # properties.name
        assert v1["properties"]["name"] == [["First"]]
        assert v2["properties"]["name"] == [["Second"]]
        assert v2["properties"]["done"] == [["Yes"]]

    def test_unknown_row_reported_before_write(self, monkeypatch):
        rows = {
            R1: {"id": R1, "parent_id": COL1, "parent_table": "collection", "type": "page",
                 "properties": {"title": [["old"]]}},
        }
        client, collection = _collection_client(monkeypatch, SCHEMA, rows)
        from unpy.rows import update_rows

        count, failures = update_rows(client, [
            {"row_id": R1, "properties": {"Name": "ok"}},
            {"row_id": "nope-not-here", "properties": {"Name": "x"}},
        ])
        assert count == 1
        assert any("nope-not-here" in f for f in failures)

    def test_bad_properties_shape(self, monkeypatch):
        client, collection = _collection_client(monkeypatch, SCHEMA)
        from unpy.rows import update_rows

        count, failures = update_rows(client, [{"row_id": R1, "properties": "not-a-dict"}])
        assert count == 0
        assert any("'properties' must be an object" in f for f in failures)
        assert client.submitted == []


class TestDeleteRows:
    def test_delete_rows_delegates_to_remove_blocks(self, monkeypatch):
        rows = {
            R1: {"id": R1, "parent_id": COL1, "parent_table": "collection", "type": "page"},
            R2: {"id": R2, "parent_id": COL1, "parent_table": "collection", "type": "page"},
        }
        client, collection = _collection_client(monkeypatch, SCHEMA, rows)
        from unpy.rows import delete_rows

        count, failures = delete_rows(client, [R1, R2])
        assert (count, failures) == (2, [])
        with client._store._mutex:
            v1 = client._store._values["block"][R1]
        assert v1["alive"] is False