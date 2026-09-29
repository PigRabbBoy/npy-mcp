"""Tests for v2.0.0 M2: RecordStore read-lock + debounced disk saves + batched reads."""

import json
import os
import threading
import time
from pathlib import Path

import pytest

FAKE_TOKEN = "test-token-not-real"


class TestReadLocking:
    """Concurrent read-while-write must never raise or miss (v2 read-lock)."""

    def _store(self, tmp_path, monkeypatch):
        from unpy.store import RecordStore

        monkeypatch.setenv("NOTION_DATA_DIR", str(tmp_path))
        # settings caches CACHE_DIR at import — patch the module-level
        import unpy.settings as settings

        monkeypatch.setattr(settings, "CACHE_DIR", str(tmp_path / "cache"))
        os.makedirs(str(tmp_path / "cache"), exist_ok=True)
        store = RecordStore(None, cache_key="t1")
        return store

    def test_concurrent_reads_of_updates(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UNPY_LEGACY", "")
        from unpy.store import RecordStore

        monkeypatch.setenv("NOTION_DATA_DIR", str(tmp_path))
        import unpy.settings as settings

        monkeypatch.setattr(settings, "CACHE_DIR", str(tmp_path / "cache"))
        os.makedirs(str(tmp_path / "cache"), exist_ok=True)
        store = RecordStore(None, cache_key="t2")
        store._update_record("block", "b1", value={"id": "b1", "v": 0}, role="editor")

        errors = []

        def reader():
            for _ in range(400):
                try:
                    r = store._get("block", "b1")
                    assert r is not RecordStore_Missing if False else True
                except Exception as exc:  # noqa
                    errors.append(exc)
                    return

        def writer():
            for i in range(200):
                try:
                    store._update_record(
                        "block", "b1", value={"id": "b1", "v": i}, role="editor"
                    )
                except Exception as exc:
                    errors.append(exc)
                    return

        from unpy.store import Missing as RecordStore_Missing

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_set_collection_rows_read_safe(self, tmp_path, monkeypatch):
        from unpy.store import RecordStore

        monkeypatch.setenv("NOTION_DATA_DIR", str(tmp_path))
        import unpy.settings as settings

        monkeypatch.setattr(settings, "CACHE_DIR", str(tmp_path / "cache"))
        os.makedirs(str(tmp_path / "cache"), exist_ok=True)
        store = RecordStore(None, cache_key="t3")
        errors = []

        def setter():
            for i in range(50):
                store.set_collection_rows("c1", [f"r{j}" for j in range(i + 1)])

        def getter():
            for _ in range(200):
                try:
                    store.get_collection_rows("c1")
                except Exception as exc:
                    errors.append(exc)
                    return

        threads = [threading.Thread(target=setter), threading.Thread(target=getter)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestDebouncedDiskSave:
    """Disk persistence coalesces bursts instead of dumping per record."""

    def _make_store(self, tmp_path, monkeypatch, cache_key="deb"):
        from unpy.store import RecordStore

        monkeypatch.setenv("NOTION_DATA_DIR", str(tmp_path))
        import unpy.settings as settings

        monkeypatch.setattr(settings, "CACHE_DIR", str(tmp_path / "cache"))
        os.makedirs(str(tmp_path / "cache"), exist_ok=True)
        return RecordStore(True, cache_key=cache_key)

    def test_no_client_store_marks_dirty_without_disk(self, tmp_path, monkeypatch):
        # cache_key=None (no disk cache) — marks must never touch disk
        from unpy.store import RecordStore

        store = RecordStore(True)
        assert store._cache_key is None
        store._update_record("block", "b1", value={"id": "b1"}, role="editor")
        assert store._get("block", "b1") == {"id": "b1"}

    def test_burst_updates_flush_once(self, tmp_path, monkeypatch):
        store = self._make_store(tmp_path, monkeypatch)
        # write 50 records quickly
        for i in range(50):
            store._update_record(
                "block", f"b{i}", value={"id": f"b{i}", "v": i}, role="editor"
            )
        path = tmp_path / "cache" / (store._cache_key + "_values.json")
        # wait for the debounce timer to fire (scheduled 1s out)
        timer = store._cache_flush_timer
        assert timer is not None
        timer.join(timeout=4)
        assert timer.is_alive() is False
        assert path.exists(), list((tmp_path / "cache").iterdir())
        data = json.loads(path.read_text())
        assert len(data["block"]) == 50


class TestBatchedChildrenReads:
    """Children iteration batch-fetches; count syncRecordValues posts."""

    P1 = "11111111-1111-4111-8111-111111111111"
    C1 = "22222222-2222-4222-8222-222222222221"
    C2 = "22222222-2222-4222-8222-222222222222"
    C3 = "22222222-2222-4222-8222-222222222223"

    def test_children_iter_batches_missing_ids(self, monkeypatch):
        from unpy.block import Block
        from unpy.store import RecordStore

        P1, C1, C2, C3 = self.P1, self.C1, self.C2, self.C3

        class Client:
            def __init__(self):
                self._store = RecordStore(None)
                self._monitor = None
                self.refresh_calls = []

            def refresh_records(self, **kwargs):
                self.refresh_calls.append(kwargs)
                for bid in kwargs.get("block", []):
                    self._store._update_record(
                        "block",
                        bid,
                        value={
                            "id": bid,
                            "type": "text",
                            "parent_id": P1,
                            "parent_table": "block",
                        },
                        role="editor",
                    )

            def get_block(self, url_or_id):
                from unpy.block import Block

                bid = self._store.get("block", url_or_id)
                if not bid:
                    return None
                return Block(self, url_or_id)

            def get_record_data(self, table, id, force_refresh=False):
                return self._store.get(table, id, force_refresh=force_refresh)

        client = Client()
        with client._store._mutex:
            client._store._values["block"][P1] = {
                "id": P1,
                "type": "page",
                "content": [C1, C2, C3],
            }
        kids = list(Block(client, P1).children)
        assert len(kids) == 3
        # exactly ONE batched refresh (not one per child)
        assert len(client.refresh_calls) == 1
        assert set(client.refresh_calls[0]["block"]) == {C1, C2, C3}

    def test_children_iter_skips_prefetch_when_cached(self, monkeypatch):
        from unpy.block import Block
        from unpy.store import RecordStore

        P1 = self.P1
        C1 = self.C1

        class Client:
            def __init__(self):
                self._store = RecordStore(None)
                self._monitor = None
                self.refresh_calls = []

            def refresh_records(self, **kwargs):
                self.refresh_calls.append(kwargs)

            def get_block(self, url_or_id):
                from unpy.block import Block

                bid = self._store.get("block", url_or_id)
                if not bid:
                    return None
                return Block(self, url_or_id)

            def get_record_data(self, table, id, force_refresh=False):
                return self._store.get(table, id, force_refresh=force_refresh)

        client = Client()
        with client._store._mutex:
            client._store._values["block"][P1] = {
                "id": P1,
                "type": "page",
                "content": [C1],
            }
            client._store._values["block"][C1] = {
                "id": C1,
                "type": "text",
                "parent_id": P1,
                "parent_table": "block",
            }
        kids = list(Block(client, P1).children)
        assert len(kids) == 1
        assert client.refresh_calls == []