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
    btype = block.get("type", "") or ""
    # Strip icon from title to avoid noise (icon is separate field)
    title = block.title_plaintext if hasattr(block, "title_plaintext") else None
    if title and icon and title.startswith(icon):
        title = title[len(icon):].strip()
    # For collection_view/collection_view_page, use DB name if title is empty
    if not title and btype in ("collection_view", "collection_view_page"):
        title = _get_inline_db_name(block) or ""
    return {
        "id": block.id,
        "type": btype,
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


def _get_inline_db_name(block) -> str:
    """Try to resolve an inline database's name from a collection_view block.

    The collection may not be lazily loaded on the block itself, so we look it
    up via the view_ids → collection_view record → collection_pointer → collection.
    """
    col = getattr(block, "collection", None)
    if col is not None and hasattr(col, "name") and col.name:
        return col.name
    # Fallback: resolve via view_ids → collection_view → collection_pointer
    view_ids = block.get("view_ids") or []
    for vid in view_ids:
        cv_data = block._client._store._values.get("collection_view", {}).get(vid)
        if cv_data:
            ptr = cv_data.get("format", {}).get("collection_pointer", {})
            col_id = ptr.get("id")
            if col_id:
                col_data = block._client._store._values.get("collection", {}).get(col_id)
                if col_data:
                    # Collection name is stored as Notion rich-text array, not plain string
                    name_raw = col_data.get("name") or col_data.get("title")
                    if name_raw:
                        # Parse Notion rich-text: [["text", [["b"]]], ...] → "text"
                        try:
                            parts = []
                            for segment in name_raw:
                                if isinstance(segment, list) and segment:
                                    parts.append(str(segment[0]))
                                elif isinstance(segment, str):
                                    parts.append(segment)
                            return "".join(parts)
                        except Exception:
                            return str(name_raw)
                # Try loading the collection
                try:
                    col_obj = block._client.get_collection(col_id)
                    if col_obj and col_obj.name:
                        return col_obj.name
                except Exception:
                    pass
    return ""


def _build_image_url(block) -> str:
    """Build a downloadable image URL for an image block.

    Notion stores images as 'attachment:<file_id>:<filename>' which the browser
    resolves via a proxy URL: https://app.notion.com/image/<url-encoded-source>?table=block&id=<block_id>&spaceId=...&userId=...
    This proxy URL works with the token_v2 cookie for authentication.
    """
    source = block.get("format.display_source") or block.get("source") or ""
    if not source:
        return ""
    # If it's already a full URL (http/https), return as-is
    if source.startswith("http"):
        return source
    # Build Notion image proxy URL for attachment: sources
    from urllib.parse import quote
    space_id = ""
    user_id = ""
    try:
        space_id = block._client.current_space.id
    except Exception:
        pass
    try:
        user_id = block._client.current_user.id
    except Exception:
        pass
    params = f"table=block&id={block.id}"
    if space_id:
        params += f"&spaceId={space_id}"
    if user_id:
        params += f"&userId={user_id}"
    params += "&cache=v2"
    return f"https://app.notion.com/image/{quote(source, safe='')}?{params}"


def _block_to_markdown(block) -> str:
    """Convert a single block to markdown text."""
    btype = block.get("type", "") or ""
    # Image — emit marker with filename and get_image hint
    if btype == "image":
        # Extract filename from properties for readability
        filename = ""
        try:
            title_raw = block.get("properties.title") or []
            if title_raw and isinstance(title_raw[0], list):
                filename = str(title_raw[0][0])
            elif title_raw and isinstance(title_raw[0], str):
                filename = title_raw[0]
        except Exception:
            pass
        caption = ""
        try:
            caption = block.caption or ""
        except Exception:
            pass
        label = caption or filename or "(untitled)"
        return f"[image] {label} — use get_image(\"{block.id}\") to download"
    # Embed/video/file/audio/pdf — emit marker with source URL
    if btype in ("embed", "video", "file", "audio", "pdf"):
        source = block.get("format.display_source") or block.get("source") or ""
        return f"[{btype}] {source}" if source else f"[{btype}] (no source)"
    # Bookmark/figma/tweet/gist/etc — emit marker with source URL
    if btype in ("bookmark", "figma", "tweet", "gist", "drive", "loom", "typeform",
                 "codepen", "maps", "invision", "framer", "html", "miro", "excalidraw",
                 "replit", "deepnote", "sketch", "abstract", "mixpanel"):
        source = block.get("format.display_source") or block.get("source") or ""
        return f"[{btype}] {source}" if source else f"[{btype}]"
    # Simple table (type=table or simple_table) — render as markdown table from children
    if btype in ("table", "simple_table"):
        return _table_to_markdown(block)
    # Column list — render children sequentially with column headers
    if btype == "column_list":
        return ""  # handled in _render_page_tree via recursion
    if btype == "column":
        return ""  # handled in _render_page_tree via recursion
    # Synced block — render its children (same as a container)
    if btype == "synced_block":
        return ""  # handled in _render_page_tree via recursion
    # Breadcrumb — auto-generated by Notion
    if btype == "breadcrumb":
        return "[breadcrumb]"
    # Factory — template factory block
    if btype == "factory":
        return f"[template factory] {md}" if md else "[template factory]"
    # Link to collection — linked database
    if btype == "link_to_collection":
        return f"[linked database] — use get_database(\"{block.id}\")"
    # Table of contents
    if btype == "table_of_contents":
        return "[table of contents]"
    # Link to page
    if btype == "link_to_page":
        return f"[link to page] {md}" if md else "[link to page]"
    # Inline database — only emit stub if there's actually a collection
    if btype in ("collection_view", "collection_view_page"):
        db_name = _get_inline_db_name(block)
        if db_name:
            return f"[inline database] {db_name} — use get_database(\"{block.id}\")"
        # No collection found — might be a simple table misidentified, or empty DB
        return f"[collection_view] (no collection) — block id: {block.id}"
    try:
        md = block.title_plaintext
    except Exception:
        md = ""
    if btype == "header":
        return f"# {md}"
    if btype == "sub_header":
        return f"## {md}"
    if btype == "sub_sub_header":
        return f"### {md}"
    if btype == "sub_sub_sub_header":
        return f"#### {md}"
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
    if btype == "equation":
        return f"$$ {md} $$"
    return md


def _table_to_markdown(block) -> str:
    """Render a Notion simple table (type=table) as a markdown table.

    Simple tables store rows as children blocks, with cells in properties.
    """
    children = getattr(block, "children", None)
    if not children:
        return f"[table] (empty — block id: {block.id})"
    # Check if table has collection (some tables are collection-backed)
    col = getattr(block, "collection", None)
    if col is not None:
        db_name = _get_inline_db_name(block) or "(unnamed)"
        return f"[inline database] {db_name} — use get_database(\"{block.id}\")"
    rows = []
    for child in children:
        cells = []
        # Table row cells are in properties, keyed by column id
        props = child.get("properties") or {}
        # Get column order from format
        fmt = block.get("format", {}) or {}
        col_order = fmt.get("table_block_column_order", [])
        col_widths = fmt.get("table_block_column_format", {})
        if col_order:
            for col_id in col_order:
                cell_data = props.get(col_id, [])
                cell_text = _parse_rich_text(cell_data)
                cells.append(cell_text.replace("|", "\\|").replace("\n", " "))
        else:
            # Fallback: just dump all property values in order
            for _, cell_data in props.items():
                cell_text = _parse_rich_text(cell_data)
                cells.append(cell_text.replace("|", "\\|").replace("\n", " "))
        rows.append(cells)
    if not rows:
        return f"[table] (no rows — block id: {block.id})"
    # First row is header
    ncols = len(rows[0])
    lines = []
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(ncols)) + " |")
    for row in rows[1:]:
        # Pad row to ncols
        while len(row) < ncols:
            row.append("")
        lines.append("| " + " | ".join(row[:ncols]) + " |")
    return "\n".join(lines)


def _parse_rich_text(data) -> str:
    """Parse Notion rich-text property value to plain text.

    Notion stores cell text as: [["text", [["b"]]], [", "], ["more text"]]
    Each element is [text, formatting_markers] or a plain string.
    """
    if not data:
        return ""
    if isinstance(data, str):
        return data
    parts = []
    for segment in data:
        if isinstance(segment, str):
            parts.append(segment)
        elif isinstance(segment, list) and segment:
            parts.append(str(segment[0]))
    return "".join(parts)


def _tree_to_markdown(client: NotionClient, block, depth: int, level: int = 0) -> list[str]:
    """Recursively render a block tree to markdown lines."""
    lines = []
    btype = block.get("type", "") or ""

    # Container blocks — render children, not the container itself
    if btype == "column_list":
        if depth == 0:
            return lines
        children = getattr(block, "children", None)
        if children is None:
            return lines
        col_num = 0
        for child in children:
            col_num += 1
            if child.get("type", "") == "column":
                lines.append(("  " * level) + f"--- Column {col_num} ---")
                child_lines = _tree_to_markdown(
                    client, child, depth - 1 if depth > 0 else -1, level + 1
                )
                lines.extend(child_lines)
            else:
                child_lines = _tree_to_markdown(
                    client, child, depth - 1 if depth > 0 else -1, level
                )
                lines.extend(child_lines)
        return lines

    if btype == "column":
        # Column itself is transparent — just render children
        if depth == 0:
            return lines
        children = getattr(block, "children", None)
        if children is None:
            return lines
        for child in children:
            child_lines = _tree_to_markdown(
                client, child, depth - 1 if depth > 0 else -1, level
            )
            lines.extend(child_lines)
        return lines

    if btype == "synced_block":
        # Synced block — render children (same as a container)
        if depth == 0:
            return lines
        children = getattr(block, "children", None)
        if children is None:
            return lines
        for child in children:
            child_lines = _tree_to_markdown(
                client, child, depth - 1 if depth > 0 else -1, level
            )
            lines.extend(child_lines)
        return lines

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


@mcp.tool(structured_output=False)
def get_image(block_id: str):
    """Download an image block and return it as MCP ImageContent.

    The Notion image proxy URL requires token_v2 cookie authentication, so
    external clients cannot download images directly. This tool fetches the
    image through the server's authenticated session and returns it as an
    MCP image content block — the client renders it natively as an image
    (~157 tokens for a typical diagram), not as base64 text (~37k tokens).

    Args:
        block_id: Image block URL or ID

    Returns:
        MCP ImageContent (image block) — client renders as image.
        On error, returns a text message.
    """
    from mcp.server.mcpserver import Image
    client = _get_client()
    block = client.get_block(block_id)
    if block is None:
        return f"Block not found: {block_id}"
    btype = block.get("type", "") or ""
    if btype != "image":
        return f"Block {block_id} is not an image (type: {btype})"
    url = _build_image_url(block)
    if not url:
        return f"Image block {block_id} has no source URL"
    try:
        r = client.session.get(url, allow_redirects=True, timeout=30)
        r.raise_for_status()
    except Exception as exc:
        return f"Failed to download image: {exc}"
    mime = r.headers.get("content-type", "image/png")
    # Fallback mime detection from filename
    if not mime or mime == "application/octet-stream":
        source = block.get("format.display_source") or block.get("source") or ""
        if source.endswith(".png"):
            mime = "image/png"
        elif source.endswith(".jpg") or source.endswith(".jpeg"):
            mime = "image/jpeg"
        elif source.endswith(".gif"):
            mime = "image/gif"
        elif source.endswith(".svg"):
            mime = "image/svg+xml"
        elif source.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/png"
    # Extract format from mime (e.g. "image/png" -> "png")
    fmt = mime.split("/")[-1] if "/" in mime else "png"
    return Image(data=r.content, format=fmt)


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
        # If block is collection_view but collection is None (lazy-loaded),
        # try resolving via view_ids → collection_view record → collection_pointer
        if collection is None and block.get("view_ids"):
            view_ids = block.get("view_ids") or []
            for vid in view_ids:
                cv_data = client._store._values.get("collection_view", {}).get(vid)
                if cv_data:
                    ptr = cv_data.get("format", {}).get("collection_pointer", {})
                    col_id = ptr.get("id")
                    if col_id:
                        try:
                            collection = client.get_collection(col_id)
                            break
                        except Exception:
                            pass
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    if collection is None:
        btype = block.get("type", "") if block else "(unknown)"
        return f"Database not found: {database_id} (block type: {btype}). This may be a simple table, not a database — use get_page to read it."
    try:
        name = collection.name if hasattr(collection, "name") else "(unnamed)"
        schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    except Exception as exc:
        return f"Failed to read database schema: {exc}"
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
        # If block is collection_view but collection is None (lazy-loaded),
        # try resolving via view_ids → collection_view record → collection_pointer
        if collection is None and block.get("view_ids"):
            view_ids = block.get("view_ids") or []
            for vid in view_ids:
                cv_data = client._store._values.get("collection_view", {}).get(vid)
                if cv_data:
                    ptr = cv_data.get("format", {}).get("collection_pointer", {})
                    col_id = ptr.get("id")
                    if col_id:
                        try:
                            collection = client.get_collection(col_id)
                            break
                        except Exception:
                            pass
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    if collection is None:
        btype = block.get("type", "") if block else "(unknown)"
        return f"Database not found: {database_id} (block type: {btype}). This may be a simple table, not a database — use get_page to read it."
    try:
        schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    except Exception as exc:
        return f"Failed to read database schema: {exc}"
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


def _build_collection_schema(col_specs: list) -> dict:
    """Build a Notion collection schema from column specs.

    Each spec: {"name": str, "type": str, "options": [str, ...]}
    Returns: {prop_id: {"name": str, "type": str, "options": [...]}}
    """
    import uuid
    schema = {}
    for spec in col_specs:
        name = spec.get("name", "Untitled")
        ptype = spec.get("type", "text")
        prop_id = spec.get("id") or uuid.uuid4().hex[:4]
        prop = {"name": name, "type": ptype}
        if ptype in ("select", "multi_select", "status") and spec.get("options"):
            prop["options"] = [
                {"value": o, "color": "default"} for o in spec["options"]
            ]
        schema[prop_id] = prop
    return schema


if _WRITE_ENABLED:
    from notion.block import (
        PageBlock, TextBlock, TodoBlock, HeaderBlock, SubheaderBlock,
        SubsubheaderBlock, CalloutBlock, BulletedListBlock, NumberedListBlock,
        QuoteBlock, CodeBlock, DividerBlock, ToggleBlock, EquationBlock,
        CollectionViewBlock, CollectionViewPageBlock,
        EmbedBlock, BookmarkBlock, ImageBlock, VideoBlock, AudioBlock,
        FileBlock, PDFBlock, TweetBlock, GistBlock, FigmaBlock, LoomBlock,
        TypeformBlock, CodepenBlock, MapsBlock, InvisionBlock, FramerBlock,
        DriveBlock, HtmlBlock, MiroBlock, ExcalidrawBlock, ReplitBlock,
        DeepnoteBlock, SketchBlock, AbstractBlock, MixpanelBlock,
    )
    from notion.collection import Collection

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

        Supported types: text, todo, header, subheader, subsubheader, callout,
        bulleted_list, numbered_list, quote, code, divider, toggle, equation.

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
            "subsubheader": SubsubheaderBlock,
            "callout": CalloutBlock,
            "bulleted_list": BulletedListBlock,
            "numbered_list": NumberedListBlock,
            "quote": QuoteBlock,
            "code": CodeBlock,
            "divider": DividerBlock,
            "toggle": ToggleBlock,
            "equation": EquationBlock,
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

    @mcp.tool()
    def create_database(
        parent_id: str,
        title: str,
        columns: str = "",
        icon: str = "",
    ) -> str:
        """Create a new database (collection) under a parent page.

        Creates an inline database (collection_view block) embedded within
        the parent page. The database has a default table view.

        Args:
            parent_id: Parent page URL or ID
            title: Database title
            columns: Optional JSON array of column definitions, e.g.
                [{"name":"Status","type":"select","options":["Todo","Done"]},
                 {"name":"Priority","type":"select","options":["High","Low"]}]
                Supported types: title, text, number, select, multi_select,
                date, person, checkbox, url, email, phone_number, file, relation.
                If omitted, creates a database with a single "Name" title column.
            icon: Optional emoji icon

        Returns:
            Database block ID (use with get_database, query_database, add_database_row).
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        # Build schema from columns spec
        if columns:
            col_specs = json.loads(columns)
            schema = _build_collection_schema(col_specs)
        else:
            schema = {"title": {"name": "Name", "type": "title"}}

        # Create inline database (CollectionViewBlock as child)
        cvb = parent.children.add_new(CollectionViewBlock)
        collection_id = client.create_record(
            "collection", parent=cvb, schema=schema
        )
        cvb.collection = client.get_collection(collection_id)
        cvb.title = title
        if icon:
            cvb.icon = icon

        # Add a default table view
        cvb.views.add_new(view_type="table")
        return cvb.id

    @mcp.tool()
    def add_column(
        database_id: str,
        name: str,
        type: str,
        options: str = "",
    ) -> str:
        """Add a column to an existing database.

        Args:
            database_id: Database URL or ID
            name: Column name
            type: Column type (title, text, number, select, multi_select,
                date, person, checkbox, url, email, phone_number, file,
                relation, created_time, last_edited_time, created_by,
                last_edited_by, status)
            options: For select/multi_select/status: JSON array of option
                values, e.g. ["High","Medium","Low"]

        Returns:
            Confirmation message with the new column's property ID.
        """
        import uuid
        client = _get_client()

        # Get the collection
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

        # Build the new property
        prop_id = uuid.uuid4().hex[:4]
        prop = {"name": name, "type": type}
        if type in ("select", "multi_select", "status") and options:
            opts = json.loads(options)
            prop["options"] = [{"value": o, "color": "default"} for o in opts]

        # Add to schema
        current_schema = collection.get("schema") or {}
        current_schema[prop_id] = prop
        collection.set("schema", current_schema)
        return f"Added column '{name}' (type: {type}, id: {prop_id}) to database"

    @mcp.tool()
    def create_media(
        parent_id: str,
        type: str,
        url: str = "",
        file_path: str = "",
        caption: str = "",
    ) -> str:
        """Create a media block (image, video, audio, file, pdf) from a URL or file.

        Args:
            parent_id: Parent page URL or ID
            type: Media type (image, video, audio, file, pdf)
            url: Source URL (e.g. https://example.com/image.png)
            file_path: Local file path for upload (alternative to url)
            caption: Optional caption text

        Returns:
            Confirmation with the created block ID.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        TYPE_MAP = {
            "image": ImageBlock,
            "video": VideoBlock,
            "audio": AudioBlock,
            "file": FileBlock,
            "pdf": PDFBlock,
        }
        cls = TYPE_MAP.get(type)
        if cls is None:
            return f"Unsupported media type: {type} (try image, video, audio, file, pdf)"

        block = parent.children.add_new(cls)
        if file_path:
            block.upload_file(file_path)
        elif url:
            block.source = url
            block.display_source = url
        else:
            return "Either url or file_path must be provided"
        if caption:
            block.caption = caption
        return f"Created {type} block: {block.id}"

    @mcp.tool()
    def create_embed(
        parent_id: str,
        type: str,
        url: str,
        caption: str = "",
    ) -> str:
        """Create an embed block (tweet, figma, gist, miro, html, etc.).

        Args:
            parent_id: Parent page URL or ID
            type: Embed type (embed, bookmark, tweet, gist, figma, loom,
                typeform, codepen, maps, invision, framer, drive, html,
                miro, excalidraw, replit, deepnote, sketch, abstract, mixpanel)
            url: Source URL to embed
            caption: Optional caption text

        Returns:
            Confirmation with the created block ID.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        TYPE_MAP = {
            "embed": EmbedBlock,
            "bookmark": BookmarkBlock,
            "tweet": TweetBlock,
            "gist": GistBlock,
            "figma": FigmaBlock,
            "loom": LoomBlock,
            "typeform": TypeformBlock,
            "codepen": CodepenBlock,
            "maps": MapsBlock,
            "invision": InvisionBlock,
            "framer": FramerBlock,
            "drive": DriveBlock,
            "html": HtmlBlock,
            "miro": MiroBlock,
            "excalidraw": ExcalidrawBlock,
            "replit": ReplitBlock,
            "deepnote": DeepnoteBlock,
            "sketch": SketchBlock,
            "abstract": AbstractBlock,
            "mixpanel": MixpanelBlock,
        }
        cls = TYPE_MAP.get(type)
        if cls is None:
            supported = ", ".join(sorted(TYPE_MAP.keys()))
            return f"Unsupported embed type: {type} (supported: {supported})"

        block = parent.children.add_new(cls)
        block.source = url
        block.display_source = url
        if caption:
            block.caption = caption
        return f"Created {type} embed: {block.id}"

    @mcp.tool()
    def create_table(
        parent_id: str,
        rows: int = 3,
        cols: int = 2,
    ) -> str:
        """Create a simple table (not a database) with the specified dimensions.

        Args:
            parent_id: Parent page URL or ID
            rows: Number of rows (default 3)
            cols: Number of columns (default 2)

        Returns:
            Confirmation with the created table block ID.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        # Notion simple tables use the "table" block type
        # The block is created with format.table_columns specifying dimensions
        import uuid
        table_id = str(uuid.uuid4())
        client.create_record(
            "block",
            parent=parent,
            type="table",
            format={"table_columns": cols, "table_blocks": []},
            id=table_id,
        )
        table = client.get_block(table_id)
        return f"Created table ({rows}x{cols}): {table_id}"

    @mcp.tool()
    def create_columns(
        parent_id: str,
        num_columns: int = 2,
    ) -> str:
        """Create a column layout with the specified number of columns.

        Creates a column_list block with N empty column blocks.
        Add content to each column by using append_blocks with the column block ID.

        Args:
            parent_id: Parent page URL or ID
            num_columns: Number of columns (1-10)

        Returns:
            Confirmation with column block IDs.
        """
        from notion.block import ColumnListBlock, ColumnBlock
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"
        if num_columns < 1 or num_columns > 10:
            return f"num_columns must be 1-10, got {num_columns}"

        col_list = parent.children.add_new(ColumnListBlock)
        col_ids = []
        for i in range(num_columns):
            col = col_list.children.add_new(ColumnBlock)
            col_ids.append(col.id)
        return f"Created column_list ({num_columns} columns): {col_list.id}\nColumn IDs: {', '.join(col_ids)}"

    @mcp.tool()
    def import_csv(
        parent_id: str,
        file_path: str,
        title: str = "",
    ) -> str:
        """Import a CSV file as a new database.

        Parses the CSV file locally, creates a collection with the CSV
        headers as columns (first text column becomes the title), and
        inserts all rows as database entries.

        Args:
            parent_id: Parent page URL or ID
            file_path: Path to the CSV file
            title: Database title (defaults to the filename)

        Returns:
            Confirmation with the created database block ID.
        """
        import csv as csv_mod
        import os

        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"
        if not os.path.exists(file_path):
            return f"File not found: {file_path}"

        # Parse CSV
        with open(file_path, newline="", encoding="utf-8") as f:
            reader = csv_mod.reader(f)
            headers = next(reader)
            rows_data = list(reader)

        if not headers:
            return "CSV file has no headers"
        if not title:
            title = os.path.basename(file_path).rsplit(".", 1)[0]

        # Build schema: first text column as title, rest as text
        schema = {}
        title_prop_id = None
        for i, h in enumerate(headers):
            prop_id = f"col{i:04x}"
            if title_prop_id is None:
                schema[prop_id] = {"name": h, "type": "title"}
                title_prop_id = prop_id
            else:
                schema[prop_id] = {"name": h, "type": "text"}

        if title_prop_id is None:
            schema["title"] = {"name": "Name", "type": "title"}
            title_prop_id = "title"

        # Create inline database
        cvb = parent.children.add_new(CollectionViewBlock)
        collection_id = client.create_record(
            "collection", parent=cvb, schema=schema
        )
        cvb.collection = client.get_collection(collection_id)
        cvb.title = title
        cvb.views.add_new(view_type="table")

        # Add rows
        title_name = schema[title_prop_id]["name"]
        for row in rows_data:
            props = {}
            for i, val in enumerate(row):
                if i < len(headers):
                    col_name = headers[i]
                    if i == headers.index(schema[title_prop_id]["name"]):
                        props[title_name] = val
                    else:
                        props[col_name] = val
            try:
                cvb.collection.add_row(**props)
            except Exception:
                pass  # Skip rows that fail

        return f"Imported {len(rows_data)} rows from CSV as database: {cvb.id}"