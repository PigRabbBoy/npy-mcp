"""Output formatters — convert Notion blocks to markdown or JSON."""

from __future__ import annotations

import json
from typing import Any

from unpy import Block, CollectionRowBlock, NotionClient, notion_to_markdown
from unpy.render import render_property


def _safe_props(row) -> dict:
    """Row identity + rendered properties (never raw reprs).

    Shape: {"id": ..., "url": ..., "properties": {slug: rendered}}. The
    properties live nested so a user column literally named "id" can't
    shadow the row's identity (issue #3 — read-then-write loops need the id).
    """
    try:
        raw = row.get_all_properties()
    except Exception:
        raw = {}
    return {
        "id": row.id,
        "url": row.get_browseable_url()
        if hasattr(row, "get_browseable_url")
        else "",
        "properties": {k: render_property(v) for k, v in raw.items()},
    }


def render_block(block: Block, format: str = "markdown") -> str:
    """Render a single block to the requested format."""
    if format == "json":
        return json.dumps(_block_to_dict(block), indent=2, ensure_ascii=False)
    return _block_to_markdown(block)


def render_page(
    client: NotionClient,
    page: Block,
    depth: int = 1,
    format: str = "markdown",
) -> str:
    """Render a page and optionally its children tree.

    depth: 0 = metadata only, 1 = direct children, 2 = grandchildren, -1 = full tree.
    """
    if format == "json":
        return json.dumps(_page_tree_to_dict(client, page, depth), indent=2, ensure_ascii=False)
    lines = _page_tree_to_markdown(client, page, depth, level=0)
    return "\n".join(lines)


def render_search_results(results: list[Block], format: str = "markdown") -> str:
    """Render a list of search results."""
    if format == "json":
        items = [_block_summary_dict(b) for b in results]
        return json.dumps(items, indent=2, ensure_ascii=False)
    if not results:
        return "(no results)"
    lines = []
    for b in results:
        lines.append(_block_summary_markdown(b))
    return "\n".join(lines)


def render_rows(rows: list[CollectionRowBlock], format: str = "markdown") -> str:
    """Render database rows (used by query_database / get_database)."""
    if format == "json":
        items = [_safe_props(r) for r in rows]
        return json.dumps(items, indent=2, ensure_ascii=False)
    if not rows:
        return "(no rows)"
    lines = []
    for row in rows:
        props = _safe_props(row)
        parts = [f"id: {props['id']}"]
        if props["url"]:
            parts.append(f"url: {props['url']}")
        for k, v in props["properties"].items():
            parts.append(f"  {k}: {v}")
        lines.append("\n".join(parts))
    return "\n---\n".join(lines)


def render_database(collection, sample_rows: int = 5, format: str = "markdown") -> str:
    """Render a database (collection) schema + sample rows."""
    if format == "json":
        schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
        rows = collection.get_rows()[:sample_rows] if hasattr(collection, "get_rows") else []
        data = {
            "name": collection.name if hasattr(collection, "name") else "",
            "schema": [{"name": p.get("name","?"), "type": p.get("type","?")} for p in schema],
            "sample_rows": [_safe_props(r) for r in rows],
        }
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)
    name = collection.name if hasattr(collection, "name") else "(unnamed)"
    schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    lines = [f"# {name}", ""]
    lines.append("## Columns")
    for prop in schema:
        pname = prop.get("name", "?")
        ptype = prop.get("type", "?")
        lines.append(f"  - **{pname}** ({ptype})")
    lines.append("")
    rows = collection.get_rows()[:sample_rows] if hasattr(collection, "get_rows") else []
    if rows:
        lines.append(f"## Sample rows ({len(rows)})")
        for row in rows:
            props = _safe_props(row)
            parts = [f"id: {props['id']}"]
            if props["url"]:
                parts.append(f"url: {props['url']}")
            for k, v in props["properties"].items():
                parts.append(f"  {k}: {v}")
            lines.append("\n".join(parts))
            lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def _block_to_markdown(block: Block) -> str:
    """Convert a single block to markdown text."""
    try:
        md = block.title_plaintext
    except Exception:
        md = ""
    btype = block.get("type", "") or ""
    if btype == "header":
        return f"# {md}"
    if btype == "sub_header":
        return f"## {md}"
    if btype == "sub_sub_header":
        return f"### {md}"
    if btype == "to_do":
        checked = block.get("format.checked", False)
        return f"- [{'x' if checked else ' '}] {md}"
    if btype == "bulleted_list":
        return f"- {md}"
    if btype == "numbered_list":
        return f"1. {md}"
    if btype == "quote":
        return f"> {md}"
    if btype == "code":
        return f"```\n{md}\n```"
    if btype == "callout":
        icon = block.get("format.page_icon", "") or "💡"
        return f"{icon} {md}"
    if btype == "divider":
        return "---"
    if btype == "toggle":
        return f"<details><summary>{md}</summary></details>"
    return md


def _page_tree_to_markdown(
    client: NotionClient,
    block: Block,
    depth: int,
    level: int,
) -> list[str]:
    """Recursively render a block tree to markdown lines."""
    lines = []
    md = _block_to_markdown(block)
    if md:
        lines.append(md)
    if depth == 0:
        return lines
    children = getattr(block, "children", None)
    if children is None:
        return lines
    for child in children:
        if depth > 0:
            child_lines = _page_tree_to_markdown(client, child, depth - 1 if depth > 0 else depth, level + 1)
        else:
            child_lines = _page_tree_to_markdown(client, child, -1, level + 1)
        for cl in child_lines:
            lines.append(("  " * (level + 1)) + cl if cl.strip() else cl)
    return lines


def _block_summary_markdown(block: Block) -> str:
    """One-line summary for search results."""
    btype = block.get("type", "") or "block"
    try:
        title = block.title_plaintext
    except Exception:
        title = ""
    icon = block.get("format.page_icon", "") or ""
    url = ""
    try:
        url = block.get_browseable_url()
    except Exception:
        pass
    return f"[{btype}] {icon}{title}  \n  {url}"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _block_to_dict(block: Block) -> dict[str, Any]:
    """Block to dict for JSON output."""
    return {
        "id": block.id,
        "type": block.get("type"),
        "title": block.title_plaintext if hasattr(block, "title_plaintext") else None,
        "url": block.get_browseable_url() if hasattr(block, "get_browseable_url") else None,
        "icon": block.get("format.page_icon"),
        "alive": block.get("alive"),
    }


def _page_tree_to_dict(client: NotionClient, block: Block, depth: int) -> dict[str, Any]:
    """Block tree to dict for JSON output."""
    d = _block_to_dict(block)
    if depth == 0:
        d["children"] = []
        return d
    children = getattr(block, "children", None)
    if children is None:
        d["children"] = []
        return d
    d["children"] = [
        _page_tree_to_dict(client, c, depth - 1 if depth > 0 else -1)
        for c in children
    ]
    return d


def _block_summary_dict(block: Block) -> dict[str, Any]:
    return _block_to_dict(block)