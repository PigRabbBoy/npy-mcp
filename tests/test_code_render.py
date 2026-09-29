"""Smoke test: render code blocks via MCP + CLI renderers (issue #20)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-mcp", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "unpy-cli", "src"))

from unpy.block import CodeBlock


def _code_block(stored, lang="Python"):
    cb = CodeBlock.__new__(CodeBlock)
    object.__setattr__(
        cb, "_client", SimpleNamespace(_monitor=None, current_space=None, current_user=None)
    )
    object.__setattr__(cb, "_id", "code1")

    def fake_get_data(force_refresh=False):
        props = {"title": stored}
        if lang:
            props["language"] = [[lang]]
        return {"type": "code", "properties": props}

    object.__setattr__(cb, "_get_record_data", fake_get_data)
    return cb


def test_mcp_renders_text_not_raw_list():
    from unpy_mcp.server import _block_to_markdown

    cb = _code_block([["print('hi')"]])
    out = _block_to_markdown(cb)
    assert out == "```python\nprint('no language')\n```".replace("print('no language')", "print('hi')")
    assert "[[" not in out


def test_mcp_renders_leading_whitespace():
    from unpy_mcp.server import _block_to_markdown

    cb = _code_block([["  x = 1"]])
    out = _block_to_markdown(cb)
    assert "  x = 1" in out
    assert not out.startswith("``` [[")  # no raw list in fence


def test_mcp_no_language_is_plain_fence():
    from unpy_mcp.server import _block_to_markdown

    cb = _code_block([["print('x')"]], lang="")
    out = _block_to_markdown(cb)
    assert out.startswith("```\n")


def test_cli_renders_code_with_language():
    from unpy_cli.render import _block_to_markdown as cli_block_md

    cb = _code_block([["print('x')"]])
    out = cli_block_md(cb)
    assert out.startswith("```python\n")
    assert "[[" not in out


def test_cli_code_multiline():
    from unpy_cli.render import _block_to_markdown as cli_md

    cb = _code_block([["def f():", [","]], ["    return 1"]])
    out = cli_md(cb)
    assert "def f():" in out and "return 1" in out