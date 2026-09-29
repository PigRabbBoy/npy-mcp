"""Tests for v2.0.0 M4: thread fan-out (fetch_many_blocks)."""

import threading
import time

import pytest


class TestFetchManyBlocks:
    def _client(self, monkeypatch, workers=None, set_legacy=None):
        monkeypatch.setenv("UNPY_LEGACY", set_legacy or "")
        monkeypatch.delenv("UNPY_MAX_WORKERS", raising=False)
        if workers:
            monkeypatch.setenv("UNPY_MAX_WORKERS", str(workers))
        from unpy.client import NotionClient
        from unpy.store import RecordStore

        class Client:
            def __init__(self):
                self._store = RecordStore(None)
                self._monitor = None
                self.get_calls = []
                self.lock = threading.Lock()
                # simulate blocking I/O in get_block to verify parallelism
                self.get_delay = 0.02

            def in_transaction(self):
                return False

            def post(self, endpoint, data):
                # stub: refresh of missing ids returns nothing (unknown ids)
                return type("R", (), {"json": lambda self: {}})()

            def get_block(self, url_or_id):
                with self.lock:
                    self.get_calls.append(url_or_id)
                time.sleep(self.get_delay)
                from unpy.block import Block

                block = self._store.get("block", url_or_id)
                if not block:
                    return None
                return Block(self, url_or_id)

        client = Client()
        client._store._client = client
        # bind real fetch_many_blocks on the stub
        client.fetch_many_blocks = (
            NotionClient.fetch_many_blocks.__get__(client)
        )
        for bid in ("aaaaaaaa-0000-4000-8000-00000000000%s" % i for i in range(4)):
            client._store._update_record(
                "block", bid, value={"id": bid, "type": "text"}, role="editor"
            )
        return client

    def _ids(self, n=4):
        return ["aaaaaaaa-0000-4000-8000-00000000000%s" % i for i in range(n)]

    def test_parallel_fetch_is_faster_than_sequential(self, monkeypatch):
        client = self._client(monkeypatch, workers=4)
        ids = self._ids()
        t0 = time.perf_counter()
        blocks = client.fetch_many_blocks(ids)
        parallel = time.perf_counter() - t0
        assert all(b is not None for b in blocks)
        # sequential would be 4 × get_delay ≈ 80ms; parallel with 3+ workers
        # should be ≪ that
        assert parallel < 0.06, f"parallel fetch too slow: {parallel:.3f}s"

    def test_order_preserved(self, monkeypatch):
        client = self._client(monkeypatch, workers=8)
        ids = list(reversed(self._ids()))
        blocks = client.fetch_many_blocks(ids)
        assert [b.id for b in blocks] == ids

    def test_dedup(self, monkeypatch):
        client = self._client(monkeypatch, workers=4)
        ids = self._ids(2) + self._ids(2)  # duplicates
        blocks = client.fetch_many_blocks(ids)
        assert len(blocks) == 4
        assert all(b.id == i for b, i in zip(blocks, ids))

    def test_unknown_ids_return_none(self, monkeypatch):
        client = self._client(monkeypatch, workers=4)
        ids = ["cccccccc-0000-4000-8000-000000000001", self._ids(1)[0]]
        blocks = client.fetch_many_blocks(ids)
        assert blocks[0] is None
        assert blocks[1].id == self._ids(1)[0]

    def test_legacy_serializes(self, monkeypatch):
        client = self._client(monkeypatch, set_legacy="1")
        ids = self._ids()
        t0 = time.perf_counter()
        blocks = client.fetch_many_blocks(ids)
        serial = time.perf_counter() - t0
        assert all(b is not None for b in blocks)
        # sequential: ~4 × get_delay (parallel path would be ~1 ×)
        assert serial >= 0.065, f"expected serialized timing, got {serial:.3f}s"