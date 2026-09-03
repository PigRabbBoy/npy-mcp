"""get_image must never hand the Notion session to a third-party host."""
import pytest
import requests

from unpy_mcp import server as srv


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://app.notion.com/image/x", True),
        ("https://www.notion.so/signed/x", True),
        ("https://notion.so/x", True),
        ("https://evil.example.com/x.png", False),
        ("https://notion.com.evil.tld/x", False),
        ("https://fakenotion.com/x", False),
        ("https://s3.us-west-2.amazonaws.com/secure.notion-static.com/x", False),
        ("file:///etc/passwd", False),
        ("ftp://notion.com/x", False),
        ("", False),
    ],
)
def test_is_notion_host(url, expected):
    assert srv._is_notion_host(url) is expected


class _FakeSession:
    def __init__(self, calls):
        self._calls = calls

    def get(self, url, **kwargs):
        self._calls.append(("session", url))
        return "session-response"


class _FakeClient:
    def __init__(self, calls):
        self.session = _FakeSession(calls)


def test_external_source_is_fetched_without_session(monkeypatch):
    calls = []
    monkeypatch.setattr(
        requests, "get", lambda url, **kw: calls.append(("plain", url)) or "plain-response"
    )
    client = _FakeClient(calls)

    assert srv._fetch_image(client, "https://evil.example.com/x.png") == "plain-response"
    assert calls == [("plain", "https://evil.example.com/x.png")]


def test_notion_source_uses_authenticated_session(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: pytest.fail("plain GET used"))
    client = _FakeClient(calls)

    url = "https://app.notion.com/image/attachment%3Aabc?table=block&id=1"
    assert srv._fetch_image(client, url) == "session-response"
    assert calls == [("session", url)]


def test_non_http_source_rejected():
    with pytest.raises(ValueError):
        srv._fetch_image(_FakeClient([]), "file:///etc/passwd")
