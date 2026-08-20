"""npy-mcp server — Notion MCP server (stdio + HTTP).

Exposes 6 read tools (+ 9 write tools when NOTION_ALLOW_WRITE=1).
Uses MCP Python SDK v2 (MCPServer + decorator pattern).

Per-request token: HTTP clients can send X-Notion-Token header to use
their own Notion session. Falls back to NOTION_TOKEN_V2 env var.
"""

from __future__ import annotations

import contextvars
import json
import os
import sys
from typing import Annotated

# Ensure npy-core is importable when running from source without install
_CORE_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "npy-core", "src")
if os.path.isdir(_CORE_SRC) and os.path.abspath(_CORE_SRC) not in sys.path:
    sys.path.insert(0, os.path.abspath(_CORE_SRC))

from mcp.server import MCPServer

from notion import NotionClient
from notion.auth import resolve_auth

mcp = MCPServer("notion-py")

# Context variable for per-request Notion token (set by HTTP middleware)
# When None, falls back to env var NOTION_TOKEN_V2
notion_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "notion_token", default=None
)

# Cache of NotionClient per token (avoids re-calling loadUserContent on every request)
_client_cache: dict[str, NotionClient] = {}


def _get_client() -> NotionClient:
    """Get or create a NotionClient for the current request's token.

    Token resolution (first non-empty wins):
    1. Per-request token from contextvar (set by HTTP middleware via X-Notion-Token header)
    2. NOTION_TOKEN_V2 / NOTION_TOKEN env var
    3. ~/.config/notion-py/token config file

    Raises RuntimeError with a helpful message if the token is invalid or expired,
    instead of letting the HTTP 401 crash the MCP connection.
    """
    token = notion_token_var.get()
    if token is None:
        cfg = resolve_auth()
        token = cfg["token"]
    # Cache client per token to avoid re-init on every request
    if token in _client_cache:
        return _client_cache[token]
    try:
        client = NotionClient(token_v2=token)
    except Exception as exc:
        # Invalidate cache entry if it was cached before but is now failing
        _client_cache.pop(token, None)
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg:
            raise RuntimeError(
                "Notion token is invalid or expired. Extract a fresh token_v2 "
                "from browser DevTools (Application → Cookies → token_v2) and "
                "update NOTION_TOKEN_V2."
            ) from exc
        raise RuntimeError(f"Failed to connect to Notion: {exc}") from exc
    # Try to bind space from config/env
    cfg = resolve_auth()
    space_id = cfg.get("space_id")
    if space_id:
        try:
            client.current_space = client.get_space(space_id)
        except Exception:
            pass
    _client_cache[token] = client
    return client


def _format_icon(icon: str) -> str:
    """Format a page icon for inline display.

    Emoji icons are kept inline; URL/attachment/path icons are dropped
    (they render as noise in text output and waste tokens).
    """
    if not icon:
        return ""
    # Emoji icons are short and don't start with / http or attachment:
    if icon.startswith(("/", "http", "attachment:")):
        return ""
    return icon


def _block_summary(block) -> dict:
    """Compact block dict for tool output."""
    url = ""
    try:
        url = block.get_browseable_url()
    except Exception:
        pass
    icon = block.get("format.page_icon") or ""
    # Strip icon from title to avoid noise (icon is separate field)
    title = block.title_plaintext if hasattr(block, "title_plaintext") else None
    if title and icon and title.startswith(icon):
        title = title[len(icon):].strip()
    return {
        "id": block.id,
        "type": block.get("type"),
        "title": title,
        "url": url,
        "icon": icon,
    }


def _block_tree(client: NotionClient, block, depth: int) -> dict:
    """Recursive block tree."""
    d = _block_summary(block)
    if depth == 0:
        d["children"] = []
        return d
    children = getattr(block, "children", None)
    if children is None:
        d["children"] = []
        return d
    d["children"] = [
        _block_tree(client, c, depth - 1 if depth > 0 else -1)
        for c in children
    ]
    return d


def _render_property(value) -> str:
    """Render a Notion property value to a readable string.

    Handles common Notion types that would otherwise leak Python repr:
    - User → email or name (not "<User ...>")
    - CollectionRowBlock → row title (not "<CollectionRowBlock ...>")
    - NotionDate → ISO date string (not "<notion.collection.NotionDate ...>")
    - list → comma-joined rendered items
    - None → empty string
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_render_property(v) for v in value)
    # CollectionRowBlock — check before User since both have .id, .email, .role
    # CollectionRowBlock has .title_plaintext; User does not
    if hasattr(value, "title_plaintext") and hasattr(value, "id"):
        return value.title_plaintext or value.id
    # User — has .email/.role but NOT .title_plaintext
    # IMPORTANT: use .get() not property attrs — property attrs are lazy/cached
    # and may return stale empty values even when store data is populated.
    if hasattr(value, "email") and hasattr(value, "role"):
        email = value.get("email") or "" if hasattr(value, "get") else ""
        name = value.get("name") or "" if hasattr(value, "get") else ""
        if name:
            return str(name)
        if email:
            return str(email)
        return getattr(value, "id", str(value))
    # NotionDate — has start/end attributes
    if hasattr(value, "start") and hasattr(value, "end") and hasattr(value, "timezone"):
        start = value.start
        end = value.end
        if start and end:
            return f"{start} → {end}"
        return str(start or end or "")
    # Fallback: str() but strip memory addresses
    s = str(value)
    if " object at 0x" in s:
        return s.split(" object at ")[0].split(".")[-1]
    return s


def _render_row_props(row, schema_names: dict[str, str] | None = None) -> list[str]:
    """Render a database row's properties as readable key: value lines.

    schema_names maps slug → original column name (for readable keys).
    """
    try:
        props = row.get_all_properties()
    except Exception:
        props = {}
    parts = []
    for k, v in props.items():
        label = schema_names.get(k, k) if schema_names else k
        parts.append(f"  {label}: {_render_property(v)}")
    return parts


def _block_to_markdown(block) -> str:
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


def _tree_to_markdown(client: NotionClient, block, depth: int, level: int = 0) -> list[str]:
    """Recursively render a block tree to markdown lines."""
    lines = []
    md = _block_to_markdown(block)
    if md:
        lines.append(("  " * level) + md)
    if depth == 0:
        return lines
    children = getattr(block, "children", None)
    if children is None:
        return lines
    for child in children:
        child_lines = _tree_to_markdown(
            client, child, depth - 1 if depth > 0 else -1, level + 1
        )
        lines.extend(child_lines)
    return lines


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search(
    query: str,
    limit: int = 20,
) -> str:
    """Search Notion blocks/pages in the current space.

    Args:
        query: Search query string
        limit: Maximum results (default 20)

    Returns:
        Markdown list of matching blocks with type, title, and URL.
    """
    client = _get_client()
    results = client.search_blocks(query, limit=limit)
    if not results:
        return "(no results)"
    lines = []
    for b in results:
        s = _block_summary(b)
        icon = _format_icon(s["icon"] or "")
        title = s["title"] or ""
        lines.append(f"[{s['type']}] {icon}{title}\n  {s['url']}")
    return "\n".join(lines)


@mcp.tool()
def get_page(
    page_id: str,
    depth: int = 1,
) -> str:
    """Fetch a Notion page and its children tree as markdown.

    Args:
        page_id: Page URL or ID
        depth: 0=metadata only, 1=direct children (default), 2=grandchildren, -1=full tree

    Returns:
        Markdown rendering of the page and its children.
    """
    client = _get_client()
    page = client.get_block(page_id)
    if page is None:
        return f"Page not found: {page_id}"
    lines = _tree_to_markdown(client, page, depth)
    return "\n".join(lines)


@mcp.tool()
def get_block(block_id: str) -> str:
    """Fetch a single Notion block as markdown.

    Args:
        block_id: Block URL or ID

    Returns:
        Markdown rendering of the block, or type info for non-text blocks.
    """
    client = _get_client()
    block = client.get_block(block_id)
    if block is None:
        return f"Block not found: {block_id}"
    md = _block_to_markdown(block)
    btype = block.get("type", "") or ""
    if not md.strip():
        # Non-text block (collection_view_page, column, link_to_page, etc.)
        title = block.title_plaintext if hasattr(block, "title_plaintext") else ""
        if title:
            return f"[{btype}] {title}"
        return f"[{btype}] (no text content — use get_page or get_database for details)"
    return md


@mcp.tool()
def list_pages() -> str:
    """List top-level pages in the current space.

    Returns:
        Markdown list of pages with title and URL.
    """
    client = _get_client()
    pages = client.get_top_level_pages()
    if not pages:
        return "(no pages)"
    lines = []
    for p in pages:
        s = _block_summary(p)
        title = s["title"] or ""
        if not title:
            continue  # skip untitled/empty blocks
        icon = _format_icon(s["icon"] or "")
        lines.append(f"[page] {icon}{title}\n  {s['url']}")
    return "\n".join(lines)


@mcp.tool()
def get_database(
    database_id: str,
    sample_rows: int = 5,
) -> str:
    """Fetch a Notion database (collection) schema and sample rows.

    Args:
        database_id: Database block URL or ID, or collection ID
        sample_rows: Number of sample rows to show (default 5)

    Returns:
        Database name, column schema, and sample row data as markdown.

    Note: Formula and rollup columns show '(computed)' as placeholder.
        Notion evaluates these browser-side (JavaScript) and does not return
        values via the API. This is a known limitation of the cookie-based
        internal API — not a bug.
    """
    client = _get_client()
    block = client.get_block(database_id)
    collection = None
    if block is not None:
        collection = getattr(block, "collection", None)
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    if collection is None:
        return f"Database not found: {database_id}"
    name = collection.name if hasattr(collection, "name") else "(unnamed)"
    schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    # Build slug → name map for readable column keys
    slug_to_name: dict[str, str] = {}
    formula_slugs: set[str] = set()
    lines = [f"# {name}", ""]
    lines.append("## Columns")
    for prop in schema:
        pname = prop.get("name", "?")
        ptype = prop.get("type", "?")
        pslug = prop.get("slug", pname)
        slug_to_name[pslug] = pname
        if ptype in ("formula", "rollup"):
            formula_slugs.add(pslug)
        lines.append(f"  - **{pname}** ({ptype})")
    lines.append("")
    rows = collection.get_rows()[:sample_rows] if hasattr(collection, "get_rows") else []
    if rows:
        lines.append(f"## Sample rows ({len(rows)})")
        for row in rows:
            try:
                props = row.get_all_properties()
            except Exception:
                props = {}
            parts = []
            for prop in schema:
                pname = prop.get("name", "?")
                pslug = prop.get("slug", pname)
                v = props.get(pslug, "")
                rendered = _render_property(v)
                if not rendered and pslug in formula_slugs:
                    rendered = "(computed)"
                parts.append(f"  {pname}: {rendered}")
            lines.append("\n".join(parts))
            lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def query_database(
    database_id: str,
    limit: int = 20,
) -> str:
    """Query a Notion database and return rows as a markdown table.

    Args:
        database_id: Database block URL or ID, or collection ID
        limit: Maximum rows to return (default 20)

    Returns:
        Markdown table of database rows with all properties.

    Note: Formula and rollup columns show '(computed)' as placeholder.
        Notion evaluates these browser-side (JavaScript) and does not return
        values via the API. This is a known limitation of the cookie-based
        internal API — not a bug.
    """
    client = _get_client()
    block = client.get_block(database_id)
    collection = None
    if block is not None:
        collection = getattr(block, "collection", None)
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    if collection is None:
        return f"Database not found: {database_id}"
    # Build slug → name map for readable column keys
    schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    slug_to_name: dict[str, str] = {}
    col_names: list[str] = []
    formula_slugs: set[str] = set()
    for prop in schema:
        pname = prop.get("name", "?")
        pslug = prop.get("slug", pname)
        ptype = prop.get("type", "?")
        slug_to_name[pslug] = pname
        col_names.append(pname)
        if ptype in ("formula", "rollup"):
            formula_slugs.add(pslug)
    rows = collection.get_rows()[:limit] if hasattr(collection, "get_rows") else []
    if not rows:
        return "(no rows)"
    # Build markdown table
    lines = []
    # Header
    lines.append("| " + " | ".join(col_names) + " |")
    lines.append("| " + " | ".join("---" for _ in col_names) + " |")
    # Rows
    for row in rows:
        try:
            props = row.get_all_properties()
        except Exception:
            props = {}
        cells = []
        for prop in schema:
            pslug = prop.get("slug", prop.get("name", "?"))
            v = props.get(pslug, "")
            rendered = _render_property(v)
            # Formula/rollup values are computed browser-side and not returned
            # by the API — show placeholder instead of empty cell
            if not rendered and pslug in formula_slugs:
                rendered = "(computed)"
            cells.append(rendered.replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write tools (gated by NOTION_ALLOW_WRITE=1)
# ---------------------------------------------------------------------------

_WRITE_ENABLED = os.environ.get("NOTION_ALLOW_WRITE") == "1"


if _WRITE_ENABLED:
    from notion.block import PageBlock, TextBlock, TodoBlock, HeaderBlock, SubheaderBlock, CalloutBlock, BulletedListBlock, NumberedListBlock, QuoteBlock, CodeBlock, DividerBlock

    @mcp.tool()
    def create_page(
        parent_id: str,
        title: str,
        icon: str = "",
    ) -> str:
        """Create a new page under a parent block.

        Args:
            parent_id: Parent page URL or ID
            title: Title for the new page
            icon: Optional emoji icon (e.g. "📄")

        Returns:
            URL of the created page.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"
        page = parent.children.add_new(PageBlock, title=title)
        if icon:
            page.icon = icon
        return page.get_browseable_url()

    @mcp.tool()
    def append_blocks(
        page_id: str,
        blocks: str,
    ) -> str:
        """Append blocks to a page. blocks is a JSON array of {type, text, checked?}.

        Supported types: text, todo, header, subheader, callout, bulleted_list,
        numbered_list, quote, code, divider.

        Args:
            page_id: Parent page URL or ID
            blocks: JSON array string, e.g. [{"type":"text","text":"Hello"},{"type":"todo","text":"Task","checked":true}]

        Returns:
            Confirmation with count of blocks added.
        """
        client = _get_client()
        parent = client.get_block(page_id)
        if parent is None:
            return f"Page not found: {page_id}"
        block_specs = json.loads(blocks)
        TYPE_MAP = {
            "text": TextBlock,
            "todo": TodoBlock,
            "header": HeaderBlock,
            "subheader": SubheaderBlock,
            "callout": CalloutBlock,
            "bulleted_list": BulletedListBlock,
            "numbered_list": NumberedListBlock,
            "quote": QuoteBlock,
            "code": CodeBlock,
            "divider": DividerBlock,
        }
        count = 0
        for spec in block_specs:
            btype = spec.get("type", "text")
            text = spec.get("text", "")
            cls = TYPE_MAP.get(btype, TextBlock)
            kwargs = {"title": text}
            if btype == "todo" and "checked" in spec:
                kwargs["checked"] = spec["checked"]
            if btype == "callout" and "icon" in spec:
                kwargs["icon"] = spec["icon"]
            parent.children.add_new(cls, **kwargs)
            count += 1
        return f"Added {count} block(s) to {page_id}"

    @mcp.tool()
    def update_block(
        block_id: str,
        field: str,
        value: str,
    ) -> str:
        """Update a block field. Supports title/text fields and 'checked' for todos.

        Args:
            block_id: Block URL or ID
            field: Field name ('title' or 'checked')
            value: New value ('true'/'false' for checked, text for title)

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        if field == "title":
            block.title = value
        elif field == "checked":
            block.checked = value.lower() in ("true", "1", "yes")
        else:
            return f"Unsupported field: {field} (try 'title' or 'checked')"
        return f"Updated {field} on block {block_id}"

    @mcp.tool()
    def delete_block(
        block_id: str,
        permanently: bool = False,
    ) -> str:
        """Delete a block (soft delete by default, permanent optional).

        Args:
            block_id: Block URL or ID
            permanently: If true, permanently delete (cannot undo)

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        block.remove(permanently=permanently)
        action = "Permanently deleted" if permanently else "Deleted (soft)"
        return f"{action} block {block_id}"

    @mcp.tool()
    def move_block(
        block_id: str,
        target_id: str,
        position: str = "after",
    ) -> str:
        """Move a block relative to a target block.

        Args:
            block_id: Block to move
            target_id: Target block
            position: 'before', 'after', or 'first-child'

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        target = client.get_block(target_id)
        if target is None:
            return f"Target not found: {target_id}"
        block.move_to(target, position)
        return f"Moved {block_id} {position} {target_id}"

    @mcp.tool()
    def add_alias(
        block_id: str,
        target_page_id: str,
    ) -> str:
        """Add an alias (linked copy) of a block to a target page.

        Args:
            block_id: Block to alias
            target_page_id: Page to add the alias to

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        target = client.get_block(target_page_id)
        if target is None:
            return f"Target page not found: {target_page_id}"
        alias = target.children.add_alias(block)
        return f"Added alias of {block_id} to {target_page_id}"

    @mcp.tool()
    def add_database_row(
        database_id: str,
        properties: str,
    ) -> str:
        """Add a row to a database. properties is a JSON object of column_name -> value.

        Args:
            database_id: Database block URL or ID, or collection ID
            properties: JSON object string, e.g. {"Name":"New row","Tags":["A"]}

        Returns:
            ID of the created row.
        """
        client = _get_client()
        block = client.get_block(database_id)
        collection = None
        if block is not None:
            collection = getattr(block, "collection", None)
        if collection is None:
            try:
                collection = client.get_collection(database_id)
            except Exception:
                pass
        if collection is None:
            return f"Database not found: {database_id}"
        props = json.loads(properties)
        row = collection.add_row(**props)
        return f"Created row: {row.id}"

    @mcp.tool()
    def update_database_row(
        row_id: str,
        properties: str,
    ) -> str:
        """Update a database row's properties.

        Args:
            row_id: Row block ID
            properties: JSON object string of column_name -> value

        Returns:
            Confirmation message.
        """
        client = _get_client()
        row = client.get_block(row_id)
        if row is None:
            return f"Row not found: {row_id}"
        props = json.loads(properties)
        for k, v in props.items():
            setattr(row, k, v)
        return f"Updated row {row_id}"

    @mcp.tool()
    def delete_database_row(
        row_id: str,
        permanently: bool = False,
    ) -> str:
        """Delete a database row.

        Args:
            row_id: Row block ID
            permanently: If true, permanently delete

        Returns:
            Confirmation message.
        """
        client = _get_client()
        row = client.get_block(row_id)
        if row is None:
            return f"Row not found: {row_id}"
        try:
            row.remove(permanently=permanently)
        except TypeError:
            row.remove()
        return f"Deleted row {row_id}"