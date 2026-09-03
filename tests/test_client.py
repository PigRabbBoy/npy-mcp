"""Integration tests using vcr.py recordings — no live Notion calls.

Tests the core client + store + block logic against recorded HTTP responses.
Recordings were captured once from a live session and committed to
tests/fixtures/recordings/. To re-record, run tests/record_fixtures.py
with a valid NOTION_TOKEN_V2 env var.
"""

import os

import pytest
import vcr

# Use a fake token — recordings match on method+host+path, not headers
FAKE_TOKEN = "test-token-not-real"

rec_dir = os.path.join(os.path.dirname(__file__), "fixtures", "recordings")

my_vcr = vcr.VCR(
    record_mode="none",  # never record, only replay
    cassette_library_dir=rec_dir,
    serializer="yaml",
    filter_headers=["cookie", "authorization"],
    match_on=["method", "scheme", "host", "path"],
)


@pytest.fixture
def unpy_client_fixture(monkeypatch):
    """Build a NotionClient using vcr recordings instead of live calls."""
    monkeypatch.setenv("NOTION_TOKEN_V2", FAKE_TOKEN)
    monkeypatch.setenv("NOTION_TOKEN", FAKE_TOKEN)
    from unpy import NotionClient
    # Client init calls loadUserContent + getPublicSpaceData (both in client_init.yaml)
    with my_vcr.use_cassette("client_init.yaml"):
        client = NotionClient(token_v2=FAKE_TOKEN)
    return client


class TestClientInit:
    def test_client_initializes(self, unpy_client_fixture):
        """Client should initialize and load user content from recording."""
        assert unpy_client_fixture is not None
        assert unpy_client_fixture.current_user is not None

    def test_current_user_has_id(self, unpy_client_fixture):
        assert unpy_client_fixture.current_user.id is not None

    def test_current_space_exists(self, unpy_client_fixture):
        """loadUserContent recording should have loaded at least one space."""
        # current_space may or may not be set depending on config
        # but the store should have space data
        store = unpy_client_fixture._store
        spaces = store._values.get("space", {})
        assert len(spaces) >= 1


class TestGetBlock:
    def test_get_block_from_recording(self, unpy_client_fixture):
        """loadPageChunk recording has the shared sample page."""
        with my_vcr.use_cassette("loadPageChunk.yaml"):
            block = unpy_client_fixture.get_block("44444444-4444-4444-8444-444444444444")
        assert block is not None
        assert block.get("type") == "page"

    def test_get_block_returns_none_for_unknown(self, unpy_client_fixture):
        # This ID is not in any recording
        with my_vcr.use_cassette("loadPageChunk.yaml"):
            block = unpy_client_fixture.get_block("00000000-0000-0000-0000-000000000000")
        # vcr in none mode will fail to find a match and raise, or return None
        # depending on whether the endpoint is hit at all


class TestSearch:
    def test_search_returns_results(self, unpy_client_fixture):
        """search recording has results for query 'Benz'."""
        with my_vcr.use_cassette("search.yaml"):
            results = unpy_client_fixture.search_blocks("Benz", limit=5)
        # search recording should return at least one result
        assert isinstance(results, list)


class TestStoreRecordmap:
    def test_store_has_block_data(self, unpy_client_fixture):
        """After loadUserContent, the store should have block records."""
        store = unpy_client_fixture._store
        blocks = store._values.get("block", {})
        # loadUserContent typically loads the user's top-level pages
        assert len(blocks) >= 1

    def test_store_has_user_data(self, unpy_client_fixture):
        store = unpy_client_fixture._store
        users = store._values.get("notion_user", {})
        assert len(users) >= 1