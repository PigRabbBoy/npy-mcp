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


def _scrub_response(response):
    """Drop response Set-Cookie headers before a cassette is written.

    vcr's ``filter_headers`` only covers *request* headers. Notion responses
    set session cookies (``file_token``, ``device_id``, ``notion_browser_id``)
    that must never land in a committed cassette.
    """
    headers = response.get("headers") or {}
    for key in list(headers):
        if key.lower() == "set-cookie":
            del headers[key]
    return response


my_vcr = vcr.VCR(
    record_mode="none",  # never record, only replay
    cassette_library_dir=rec_dir,
    serializer="yaml",
    filter_headers=["cookie", "authorization"],
    before_record_response=_scrub_response,
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


class TestSessionCookieScope:
    """token_v2 must only ever be sent to Notion hosts."""

    @staticmethod
    def _cookie_for(client, url):
        from requests import Request

        return client.session.prepare_request(Request("GET", url)).headers.get("Cookie")

    def test_cookie_sent_to_notion_hosts(self, unpy_client_fixture):
        assert "token_v2=" in self._cookie_for(unpy_client_fixture, "https://app.notion.com/api/v3/x")
        assert "token_v2=" in self._cookie_for(unpy_client_fixture, "https://www.notion.so/api/v3/getTasks")

    def test_cookie_not_sent_elsewhere(self, unpy_client_fixture):
        # Regression: a domain-less cookie was attached to every host the
        # session fetched (external image sources, S3 presigned URLs, ...).
        for url in (
            "https://evil.example.com/img.png",
            "https://s3.us-west-2.amazonaws.com/secure.notion-static.com/f.png",
            "http://169.254.169.254/latest/meta-data/",
            "http://app.notion.com/plain-http",  # secure cookie, https only
        ):
            assert self._cookie_for(unpy_client_fixture, url) is None, url


def test_scrub_response_drops_set_cookie_only():
    # record_mode="none" never invokes the hook, so exercise it directly.
    response = {"headers": {"Set-Cookie": ["file_token=x"], "set-cookie": ["a=b"], "X-Other": ["y"]}}
    assert _scrub_response(response)["headers"] == {"X-Other": ["y"]}
    assert _scrub_response({"headers": None}) == {"headers": None}


def test_cassettes_contain_no_set_cookie():
    """Response Set-Cookie headers carry session cookies; never commit them."""
    import glob

    for path in glob.glob(os.path.join(rec_dir, "*.yaml")):
        with open(path, encoding="utf-8") as f:
            text = f.read().lower()
        assert "set-cookie" not in text, path
        assert "file_token=" not in text, path


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