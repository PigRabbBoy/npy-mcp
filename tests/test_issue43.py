"""Issue #43 fixes: TTL-cache freshness semantics + batch block deletion.

Two user-visible bugs fixed together:
1. force_refresh=True inside the TTL window served the cached copy —
   get_page/update_block/delete_block acted on stale snapshots ("the edit
   seems to not stick"). Forced reads must bypass the TTL window.
2. Deleting a page's content was one HTTP transaction per block. A batch
   remove (unpy.blocks.remove_blocks) flushes ~2 ops per block in chunks
   of batch_max_ops — deleting N blocks costs ~N/50 HTTP calls.
"""

import time
from unittest.mock import MagicMock

import pytest

FAKE_TOKEN = "test-token-not-real"
B1 = "11111111-1111-4111-8111-111111111111"
B2 = "22222222-2222-4222-8222-222222222222"
B3 = "33333333-3333-4333-8333-333333333333"
P1 = "44444444-4444-4444-8444-444444444444"


# ---------------------------------------------------------------------------
# 1. force_refresh bypasses the TTL window
# ---------------------------------------------------------------------------


def _fresh_client(monkeypatch, ttl="15"):
    monkeypatch.setenv("UNPY_LEGACY", "")
    if ttl is None:
        monkeypatch.delenv("UNPY_CACHE_TTL", raising=False)
    else:
        monkeypatch.setenv("UNPY_CACHE_TTL", ttl)
    from unpy.store import RecordStore

    store = RecordStore(None)

    class Client:
        def in_transaction(self):
            return False

    store._client = Client()
    store.calls = []
    store.call_get_record_values = lambda **kw: store.calls.append(kw)
    return store


class TestForcedRefreshBypassesTTL:
    def test_forced_get_refreshes_inside_ttl_window(self, monkeypatch):
        """Regression #43: force_refresh=True must bypass the freshness
        window — a 15s-old snapshot is NOT an acceptable answer to a
        request that explicitly asked for current server state."""
        store = _fresh_client(monkeypatch)
        store._update_record("block", B1, value={"id": B1}, role="editor")
        store.get("block", B1, force_refresh=True)
        assert len(store.calls) == 1

    def test_unforced_get_still_serves_fresh_cache(self, monkeypatch):
        """Plain (unforced) reads keep the TTL benefit — this is exactly
        what the v2 cache was for."""
        store = _fresh_client(monkeypatch)
        store._update_record("block", B1, value={"id": B1}, role="editor")
        result = store.get("block", B1)
        assert result == {"id": B1}
        assert store.calls == []

    def test_forced_get_stamps_freshness_after_refresh(self, monkeypatch):
        """After a forced refresh, the just-fetched copy is fresh — reads
        inside the window serve it without another round trip."""
        store = _fresh_client(monkeypatch)
        store._update_record("block", B1, value={"id": B1}, role="editor")
        store.calls = []
        store.get("block", B1, force_refresh=True)
        assert len(store.calls) == 1
        result = store.get("block", B1)
        assert result == {"id": B1}
        assert len(store.calls) == 1  # no second call


# ---------------------------------------------------------------------------
# 2. batch block deletion
# ---------------------------------------------------------------------------


def _mock_client_with_blocks(monkeypatch, blocks):
    """A minimal NotionClient stand-in for remove_blocks tests.

    blocks: {block_id: {"id":…, "parent_id":…, "parent_table":…, "type":…}}
    All ids are pre-populated in the store as alive blocks.
    Captures submitted transactions in client.submitted.
    """
    monkeypatch.setenv("UNPY_LEGACY", "")
    from unittest.mock import patch as _patch

    from unpy.client import NotionClient
    from unpy.store import RecordStore

    client = MagicMock(spec=NotionClient)
    client._monitor = None
    store = RecordStore(None)

    class _C:
        def in_transaction(self):
            return False

    store._client = _C()
    client._store = store
    for bid, val in blocks.items():
        store._update_record("block", bid, value=dict(val), role="editor")
    client.submitted = []

    from unpy.utils import extract_id

    client.extract_id = extract_id
    client.fetch_many_blocks = lambda ids: [
        _wrap(client, extract_id(b)) for b in ids
    ]

    def _submit(operations, update_last_edited=True):
        if isinstance(operations, dict):
            operations = [operations]
        # mirror the real submit path: inside an open transaction, buffer
        # (the enclosing batched/atomic ctx flushes on exit)
        if hasattr(client, "_transaction_operations"):
            client._transaction_operations.extend(operations)
            return
        client.submitted.append(list(operations))
        store.run_local_operations(operations)

    client.submit_transaction = _submit
    # real batched_transaction bound against this mock (MagicMock(spec) would
    # otherwise return a MagicMock context manager that never buffers)
    client.batched_transaction = lambda: NotionClient.batched_transaction(client)
    client.as_atomic_transaction = lambda: NotionClient.as_atomic_transaction(client)
    return client


def _wrap(_client, block_id):
    from unpy.block import BLOCK_TYPES, Block
    from unpy.collection import CollectionRowBlock

    with _client._store._mutex:
        val = _client._store._values["block"].get(block_id)
    if not val:
        return None
    # mirror NotionClient.get_block's class resolution: rows in collections
    # are CollectionRowBlock, everything else BLOCK_TYPES[type]
    if val.get("parent_table") == "collection":
        cls = CollectionRowBlock
    else:
        cls = BLOCK_TYPES.get(val.get("type", ""), Block)
    return cls(_client, block_id)


class TestRemoveBlocks:
    def test_batch_delete_many_blocks_one_transaction(self, monkeypatch):
        """N blocks → ~2N ops, submitted in ONE transaction (not N)."""
        blocks = {
            B1: {"id": B1, "parent_id": P1, "parent_table": "block", "type": "text"},
            B2: {"id": B2, "parent_id": P1, "parent_table": "block", "type": "text"},
            B3: {"id": B3, "parent_id": P1, "parent_table": "block", "type": "text"},
        }
        client = _mock_client_with_blocks(monkeypatch, blocks)
        from unpy.blocks import remove_blocks

        count, failures = remove_blocks(client, [B1, B2, B3])
        assert (count, failures) == (3, [])
        assert len(client.submitted) == 1  # ONE transaction
        ops = client.submitted[0]
        alive_off = [op for op in ops if op.get("command") == "update" and op.get("args") == {"alive": False}]
        list_rems = [op for op in ops if op.get("command") == "listRemove"]
        assert len(alive_off) == 3
        assert len(list_rems) == 3
        # the parent content lists must be empty NOW (local replay happened)
        with client._store._mutex:
            parent = client._store._values["block"][P1]
        assert parent.get("content", []) == []

    def test_unknown_ids_reported_not_written(self, monkeypatch):
        blocks = {
            B1: {"id": B1, "parent_id": P1, "parent_table": "block", "type": "text"},
        }
        client = _mock_client_with_blocks(monkeypatch, blocks)
        from unpy.blocks import remove_blocks

        count, failures = remove_blocks(client, [B1, "does-not-exist"])
        assert count == 1
        assert len(failures) == 1
        assert "does-not-exist" in failures[0]
        # only B1's two ops were written
        assert len(client.submitted) == 1
        assert len(client.submitted[0]) == 2

    def test_urls_and_dupes_are_normalized(self, monkeypatch):
        blocks = {
            B1: {"id": B1, "parent_id": P1, "parent_table": "block", "type": "text"},
        }
        client = _mock_client_with_blocks(monkeypatch, blocks)
        from unpy.blocks import remove_blocks

        url = f"https://app.notion.com/#{B1.replace('-', '')}"
        count, failures = remove_blocks(client, [B1, url, B1.replace("-", "")])
        assert (count, failures) == (1, [])
        assert len(client.submitted) == 1

    def test_empty_input(self, monkeypatch):
        client = _mock_client_with_blocks(monkeypatch, {})
        from unpy.blocks import remove_blocks

        count, failures = remove_blocks(client, [])
        assert count == 0
        assert failures == ["no valid block ids given"]

    def test_chunks_by_batch_max_ops(self, monkeypatch):
        """5 blocks with cap=4 (2 ops/block) → 3 chunks (4+4+2)."""
        blocks = {
            bid: {"id": bid, "parent_id": P1, "parent_table": "block", "type": "text"}
            for bid in (B1, B2, B3)
        }
        blocks[B2.replace("2", "a")] = {
            "id": B2.replace("2", "a"), "parent_id": P1, "parent_table": "block", "type": "text",
        }
        blocks[B3.replace("3", "b")] = {
            "id": B3.replace("3", "b"), "parent_id": P1, "parent_table": "block", "type": "text",
        }
        monkeypatch.setenv("UNPY_BATCH_MAX_OPS", "4")
        client = _mock_client_with_blocks(monkeypatch, blocks)
        from unpy.blocks import remove_blocks

        ids = [B1, B2, B3, B2.replace("2", "a"), B3.replace("3", "b")]
        count, failures = remove_blocks(client, ids)
        assert (count, failures) == (5, [])
        assert len(client.submitted) == 3  # chunks: 4, 4, 2 data ops
        with client._store._mutex:
            parent = client._store._values["block"][P1]
        assert parent.get("content", []) == []

    def test_chunk_failure_stops_and_reports(self, monkeypatch):
        blocks = {
            B1: {"id": B1, "parent_id": P1, "parent_table": "block", "type": "text"},
            B2: {"id": B2, "parent_id": P1, "parent_table": "block", "type": "text"},
        }
        client = _mock_client_with_blocks(monkeypatch, blocks)
        calls = {"n": 0}

        def _submit(operations, update_last_edited=True):
            calls["n"] += 1
            if calls["n"] == 2:
                from requests import HTTPError
                raise HTTPError("boom")
            client.submitted.append(list(operations))
            client._store.run_local_operations(operations)

        monkeypatch.setenv("UNPY_BATCH_MAX_OPS", "2")
        client.submit_transaction = _submit
        from unpy.blocks import remove_blocks

        count, failures = remove_blocks(client, [B1, B2])
        assert count == 1  # B1's chunk committed before the failure
        assert any("boom" in f or "not deleted" in f for f in failures)

    def test_legacy_mode_uses_block_remove(self, monkeypatch):
        blocks = {
            B1: {"id": B1, "parent_id": P1, "parent_table": "block", "type": "text"},
        }
        monkeypatch.setenv("UNPY_LEGACY", "1")
        client = _mock_client_with_blocks(monkeypatch, blocks)
        client.remove = MagicMock()
        from unpy.blocks import remove_blocks

        # fetch_many_blocks wraps blocks with the real Block class; patch
        # Block.remove via the instances we hand back
        blocks_instances = client.fetch_many_blocks([B1])

        def _remove(permanently=False):
            client._store.run_local_operations([
                {"id": B1, "path": [], "args": {"alive": False}, "command": "update", "table": "block"},
            ])

        for inst in blocks_instances:
            inst.remove = _remove
        client.fetch_many_blocks = lambda ids: blocks_instances

        count, failures = remove_blocks(client, [B1])
        assert (count, failures) == (1, [])
        with client._store._mutex:
            assert client._store._values["block"][B1]["alive"] is False


class TestRefreshBlocks:
    def test_refresh_blocks_bypasses_ttl_and_batches(self, monkeypatch):
        """refresh_blocks must expire TTL stamps (forcing a net fetch) and
        issue ONE syncRecordValues per 50 ids."""
        store = _fresh_client(monkeypatch)
        from unpy.client import NotionClient

        client = NotionClient.__new__(NotionClient)
        client._store = store
        store._client = type("C", (), {"in_transaction": lambda self: False})()
        store.call_get_record_values = lambda **kw: store.calls.append(kw)
        ids = [f"{i:08x}-1111-4111-8111-{i:012x}" for i in range(120)]
        for bid in ids:
            store._update_record("block", bid, value={"id": bid}, role="editor")
        store.calls = []
        client.refresh_blocks(ids)
        # 120 ids → 3 sync calls (50+50+20); each batch lists its ids
        assert len(store.calls) == 3
        assert sum(len(c.get("block", [])) for c in store.calls) == 120

    def test_refresh_blocks_empty_noop(self, monkeypatch):
        store = _fresh_client(monkeypatch)
        from unpy.client import NotionClient

        client = NotionClient.__new__(NotionClient)
        client._store = store
        store.calls = []
        client.refresh_blocks([])
        assert store.calls == []


# ---------------------------------------------------------------------------
# 3. batch block edits
# ---------------------------------------------------------------------------

T1 = "55555555-5555-4555-8555-555555555555"
T2 = "66666666-6666-4666-8666-666666666666"


class TestUpdateBlocks:
    def test_batch_edit_one_transaction(self, monkeypatch):
        """N updates → 1 transaction (chunked at batch_max_ops ops)."""
        blocks = {
            T1: {"id": T1, "parent_id": P1, "parent_table": "block", "type": "text"},
            T2: {"id": T2, "parent_id": P1, "parent_table": "block", "type": "to_do"},
        }
        client = _mock_client_with_blocks(monkeypatch, blocks)
        from unpy.blocks import update_blocks

        count, failures = update_blocks(client, [
            {"block_id": T1, "text": "Hello **world**"},
            {"block_id": T2, "checked": True},
        ])
        assert (count, failures) == (2, [])
        assert len(client.submitted) == 1
        ops = client.submitted[0]
        # text op: updateBlockPropertyValue on properties.title
        text_ops = [op for op in ops if op["path"] == ["properties", "title"]]
        checked_ops = [op for op in ops if op["path"] == ["properties", "checked"]]
        assert len(text_ops) == 1
        assert text_ops[0]["args"]["primitiveOp"]["command"] == "set"
        assert len(checked_ops) == 1
        assert checked_ops[0]["args"]["primitiveOp"]["args"] == [[["Yes"]]]

    def test_local_replay_visible_after_edit(self, monkeypatch):
        """After update_blocks the store reflects the new text immediately
        (submit replayed the ops locally)."""
        blocks = {
            T1: {"id": T1, "parent_id": P1, "parent_table": "block",
                 "type": "text", "properties": {"title": [["old"]]}},
        }
        client = _mock_client_with_blocks(monkeypatch, blocks)
        from unpy.blocks import update_blocks

        update_blocks(client, [{"block_id": T1, "text": "new text"}])
        with client._store._mutex:
            val = client._store._values["block"][T1]
        assert val["properties"]["title"] == [["new text"]]

    def test_unknown_block_id_reported_before_write(self, monkeypatch):
        blocks = {
            T1: {"id": T1, "parent_id": P1, "parent_table": "block", "type": "text"},
        }
        client = _mock_client_with_blocks(monkeypatch, blocks)
        from unpy.blocks import update_blocks

        count, failures = update_blocks(client, [
            {"block_id": T1, "text": "ok"},
            {"block_id": "missing-id", "text": "nope"},
        ])
        assert count == 1
        assert any("missing-id" in f for f in failures)
        assert len(client.submitted) == 1  # only the valid edit was written

    def test_validation_rejects_before_write(self, monkeypatch):
        client = _mock_client_with_blocks(monkeypatch, {})
        from unpy.blocks import update_blocks

        count, failures = update_blocks(client, [
            {"text": "no block_id"},
            {"block_id": T1, "checked": "yes"},
        ])
        assert count == 0
        assert client.submitted == []
        assert any("block_id" in f for f in failures)
        assert any("'checked' must be a boolean" in f for f in failures)

    def test_empty_updates(self, monkeypatch):
        client = _mock_client_with_blocks(monkeypatch, {})
        from unpy.blocks import update_blocks

        assert update_blocks(client, [])[0] == 0
        assert client.submitted == []