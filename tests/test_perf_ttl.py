"""Tests for v2.0.0 M3: TTL freshness cache in RecordStore.

v1 semantics anchor: an UNFORCED get() of a cached record never re-fetched
(v1 was "cache forever" for plain reads); forced gets always refreshed.
v2 TTL changes ONE thing: inside the TTL window even a FORCED get serves
the cached copy. UNPY_CACHE_TTL=0 or UNPY_LEGACY=1 restores v1 exactly.
"""

import time

import pytest

FAKE_TOKEN = "test-token-not-real"


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


B1 = "11111111-1111-4111-8111-111111111111"


class TestTTLCache:
    def test_fresh_record_skips_forced_refresh(self, monkeypatch):
        """v2 gain: MCP read tools pass force_refresh=True; inside the TTL
        window the cached copy is served without a network refresh."""
        store = _fresh_client(monkeypatch)
        store._update_record("block", B1, value={"id": B1}, role="editor")
        result = store.get("block", B1, force_refresh=True)
        assert result == {"id": B1}
        assert store.calls == []

    def test_stale_record_refreshes_on_forced_get(self, monkeypatch):
        store = _fresh_client(monkeypatch, ttl="0.05")
        store._update_record("block", B1, value={"id": B1}, role="editor")
        time.sleep(0.12)
        store.get("block", B1, force_refresh=True)
        assert len(store.calls) == 1

    def test_ttl_zero_always_refreshes(self, monkeypatch):
        store = _fresh_client(monkeypatch, ttl="0")
        store._update_record("block", B1, value={"id": B1}, role="editor")
        store.get("block", B1, force_refresh=True)
        assert len(store.calls) == 1

    def test_v1_cached_get_never_refetches(self, monkeypatch):
        """v1 semantics preserved for unforced reads: cached record never
        refreshes, even outside the TTL window."""
        store = _fresh_client(monkeypatch, ttl="0")
        store._update_record("block", B1, value={"id": B1}, role="editor")
        result = store.get("block", B1)
        assert result == {"id": B1}
        assert store.calls == []

    def test_legacy_mode_disables_ttl(self, monkeypatch):
        """UNPY_LEGACY=1: forced get STILL refreshes (v1: force = refresh)."""
        monkeypatch.setenv("UNPY_LEGACY", "1")
        monkeypatch.setenv("UNPY_CACHE_TTL", "15")
        from unpy.store import RecordStore

        store = RecordStore(None)

        class Client:
            def in_transaction(self):
                return False

        store._client = Client()
        store.calls = []
        store.call_get_record_values = lambda **kw: store.calls.append(kw)
        store._update_record("block", B1, value={"id": B1}, role="editor")
        store.get("block", B1, force_refresh=True)
        assert len(store.calls) == 1

    def test_missing_record_unaffected(self, monkeypatch):
        """Records never fetched still fetch normally (TTL is not a gate)."""
        store = _fresh_client(monkeypatch)
        result = store.get("block", "eeeeeeee-9999-4999-8999-999999999999")
        assert result is None
        assert len(store.calls) == 1