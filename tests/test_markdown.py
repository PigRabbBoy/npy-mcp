"""Unit tests for markdown.py — pure logic, no HTTP needed."""

import pytest

from notion.markdown import (
    markdown_to_notion,
    notion_to_markdown,
    notion_to_plaintext,
    plaintext_to_notion,
)


# ---------------------------------------------------------------------------
# markdown_to_notion
# ---------------------------------------------------------------------------

class TestMarkdownToNotion:
    def test_plain_text(self):
        result = markdown_to_notion("Hello world")
        assert isinstance(result, list)
        assert len(result) >= 1
        # first segment should contain "Hello world"
        text = "".join(seg[0] for seg in result if isinstance(seg, list))
        assert "Hello world" in text

    def test_bold(self):
        result = markdown_to_notion("**bold**")
        text = "".join(seg[0] for seg in result if isinstance(seg, list))
        assert "bold" in text
        # check format annotations exist
        formats = []
        for seg in result:
            if isinstance(seg, list) and len(seg) > 1:
                formats.append(seg[1])
        # at least one segment should have bold format
        flat = str(formats)
        assert "b" in flat or "bold" in flat.lower() or "**" in str(result)

    def test_italic(self):
        result = markdown_to_notion("*italic*")
        text = "".join(seg[0] for seg in result if isinstance(seg, list))
        assert "italic" in text

    def test_code(self):
        result = markdown_to_notion("`code`")
        text = "".join(seg[0] for seg in result if isinstance(seg, list))
        assert "code" in text

    def test_empty_string(self):
        result = markdown_to_notion("")
        assert isinstance(result, list)

    def test_link(self):
        result = markdown_to_notion("[text](https://example.com)")
        text = "".join(seg[0] for seg in result if isinstance(seg, list))
        assert "text" in text


# ---------------------------------------------------------------------------
# notion_to_markdown
# ---------------------------------------------------------------------------

class TestNotionToMarkdown:
    def test_plain_text(self):
        notion = [["Hello world"]]
        result = notion_to_markdown(notion)
        assert "Hello world" in result

    def test_bold(self):
        notion = [["bold", [["b"]]]]
        result = notion_to_markdown(notion)
        assert "bold" in result

    def test_italic(self):
        notion = [["italic", [["i"]]]]
        result = notion_to_markdown(notion)
        assert "italic" in result

    def test_empty(self):
        notion = []
        result = notion_to_markdown(notion)
        assert result == ""

    def test_nested_formatting(self):
        notion = [["bold and italic", [["b"], ["i"]]]]
        result = notion_to_markdown(notion)
        assert "bold and italic" in result


# ---------------------------------------------------------------------------
# notion_to_plaintext
# ---------------------------------------------------------------------------

class TestNotionToPlaintext:
    def test_plain_text(self):
        notion = [["Hello world"]]
        result = notion_to_plaintext(notion)
        assert result == "Hello world"

    def test_strips_formatting(self):
        notion = [["bold", [["b"]]]]
        result = notion_to_plaintext(notion)
        assert result == "bold"

    def test_empty(self):
        assert notion_to_plaintext([]) == ""

    def test_multiple_segments(self):
        notion = [["Hello"], [" "], ["world"]]
        result = notion_to_plaintext(notion)
        assert "Hello" in result
        assert "world" in result


# ---------------------------------------------------------------------------
# plaintext_to_notion
# ---------------------------------------------------------------------------

class TestPlaintextToNotion:
    def test_plain_text(self):
        result = plaintext_to_notion("Hello world")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_empty(self):
        result = plaintext_to_notion("")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Round-trip: markdown -> notion -> plaintext
# ---------------------------------------------------------------------------

class TestRoundTrip:
    @pytest.mark.parametrize("text", [
        "Hello world",
        "Bold **text** here",
        "Italic *text* here",
        "Code `text` here",
    ])
    def test_markdown_to_plaintext_roundtrip(self, text):
        notion = markdown_to_notion(text)
        plain = notion_to_plaintext(notion)
        # the plaintext should contain the non-markdown parts
        words = text.replace("*", "").replace("`", "").split()
        for word in words:
            assert word in plain