"""npy-cli — Notion CLI (cookie-based).

Commands:
  search            Search blocks in the current space
  get-page          Fetch a page and its children tree
  get-block         Fetch a single block
  list-pages        List top-level pages in the current space
  get-database      Fetch a database schema + sample rows
  query-database    Query a database and return rows

  create-page       Create a new page (write)
  append-blocks     Append blocks to a page (write)
  update-block      Update a block field (write)
  delete-block      Delete a block (write)
  move-block        Move a block relative to target (write)
  add-alias         Add an alias of a block to a page (write)
  add-database-row Add a row to a database (write)
  update-database-row Update a database row's properties (write)
  delete-database-row Delete a database row (write)

  auth whoami      Show current token + space
  auth use-space   Set the current space (persisted)
  auth spaces     List all spaces the token has access to
"""

from __future__ import annotations

import json
import os
import sys

import typer

from .client_factory import get_client
from .render import (
    render_block,
    render_database,
    render_page,
    render_rows,
    render_search_results,
)

app = typer.Typer(
    name="notion",
    help="Notion CLI — cookie-based access to Notion's internal API.",
    no_args_is_help=True,
    add_completion=False,
)

auth_app = typer.Typer(help="Auth and config commands.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_write_enabled() -> None:
    """Gate write commands behind NOTION_ALLOW_WRITE=1 env var."""
    if os.environ.get("NOTION_ALLOW_WRITE") != "1":
        typer.echo(
            "Write commands require NOTION_ALLOW_WRITE=1 env var.\n"
            "Example: NOTION_ALLOW_WRITE=1 notion create-page ...",
            err=True,
        )
        raise typer.Exit(1)


def _resolve_collection(client, database_id: str):
    """Resolve a collection from a block ID, URL, or collection ID."""
    block = client.get_block(database_id)
    collection = None
    if block is not None:
        collection = getattr(block, "collection", None)
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    return collection


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------

@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(20, "--limit", "-n"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Search blocks in the current space."""
    client = get_client(token_arg=token)
    results = client.search_blocks(query, limit=limit)
    typer.echo(render_search_results(results, format))


@app.command(name="get-page")
def get_page(
    page_id: str = typer.Argument(..., help="Page URL or ID"),
    depth: int = typer.Option(1, "--depth", "-d", help="0=metadata, 1=children (default), 2=grandchildren, -1=full tree"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Fetch a page and its children tree."""
    client = get_client(token_arg=token)
    page = client.get_block(page_id)
    if page is None:
        typer.echo(f"Page not found: {page_id}", err=True)
        raise typer.Exit(1)
    typer.echo(render_page(client, page, depth=depth, format=format))


@app.command(name="get-block")
def get_block(
    block_id: str = typer.Argument(..., help="Block URL or ID"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Fetch a single block."""
    client = get_client(token_arg=token)
    block = client.get_block(block_id)
    if block is None:
        typer.echo(f"Block not found: {block_id}", err=True)
        raise typer.Exit(1)
    typer.echo(render_block(block, format))


@app.command(name="list-pages")
def list_pages(
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """List top-level pages in the current space."""
    client = get_client(token_arg=token)
    pages = client.get_top_level_pages()
    typer.echo(render_search_results(pages, format))


@app.command(name="get-database")
def get_database(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    sample_rows: int = typer.Option(5, "--sample", "-s", help="Number of sample rows to show"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Fetch a database schema and sample rows."""
    client = get_client(token_arg=token)
    collection = _resolve_collection(client, database_id)
    if collection is None:
        typer.echo(f"Database not found: {database_id}", err=True)
        raise typer.Exit(1)
    typer.echo(render_database(collection, sample_rows=sample_rows, format=format))


@app.command(name="query-database")
def query_database(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to return"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Query a database and return rows."""
    client = get_client(token_arg=token)
    collection = _resolve_collection(client, database_id)
    if collection is None:
        typer.echo(f"Database not found: {database_id}", err=True)
        raise typer.Exit(1)
    rows = collection.get_rows()[:limit] if hasattr(collection, "get_rows") else []
    typer.echo(render_rows(rows, format))


# ---------------------------------------------------------------------------
# Write commands (gated by NOTION_ALLOW_WRITE=1)
# ---------------------------------------------------------------------------

@app.command(name="create-page")
def create_page(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    title: str = typer.Option(..., "--title", help="Title for the new page"),
    icon: str = typer.Option("", "--icon", help="Optional emoji icon (e.g. '📄')"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create a new page under a parent block."""
    _check_write_enabled()
    from notion.block import PageBlock
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    page = parent.children.add_new(PageBlock, title=title)
    if icon:
        page.icon = icon
    typer.echo(f"Created page: {page.get_browseable_url()}")


@app.command(name="append-blocks")
def append_blocks(
    page_id: str = typer.Argument(..., help="Parent page URL or ID"),
    blocks: str = typer.Option(..., "--blocks", "-b", help='JSON array, e.g. \'[{"type":"text","text":"Hello"},{"type":"todo","text":"Task","checked":true}]\''),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Append blocks to a page. Supports: text, todo, header, subheader, callout, bulleted_list, numbered_list, quote, code, divider."""
    _check_write_enabled()
    from notion.block import (
        TextBlock, TodoBlock, HeaderBlock, SubheaderBlock, CalloutBlock,
        BulletedListBlock, NumberedListBlock, QuoteBlock, CodeBlock, DividerBlock,
    )
    client = get_client(token_arg=token)
    parent = client.get_block(page_id)
    if parent is None:
        typer.echo(f"Page not found: {page_id}", err=True)
        raise typer.Exit(1)
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
    typer.echo(f"Added {count} block(s) to {page_id}")


@app.command(name="update-block")
def update_block(
    block_id: str = typer.Argument(..., help="Block URL or ID"),
    field: str = typer.Option(..., "--field", help="Field to update: 'title' or 'checked'"),
    value: str = typer.Option(..., "--value", help="New value (text, or 'true'/'false' for checked)"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Update a block field ('title' or 'checked')."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    block = client.get_block(block_id)
    if block is None:
        typer.echo(f"Block not found: {block_id}", err=True)
        raise typer.Exit(1)
    if field == "title":
        block.title = value
    elif field == "checked":
        block.checked = value.lower() in ("true", "1", "yes")
    else:
        typer.echo(f"Unsupported field: {field} (try 'title' or 'checked')", err=True)
        raise typer.Exit(1)
    typer.echo(f"Updated {field} on block {block_id}")


@app.command(name="delete-block")
def delete_block(
    block_id: str = typer.Argument(..., help="Block URL or ID"),
    permanently: bool = typer.Option(False, "--permanently", help="Permanently delete (cannot undo)"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Delete a block (soft delete by default)."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    block = client.get_block(block_id)
    if block is None:
        typer.echo(f"Block not found: {block_id}", err=True)
        raise typer.Exit(1)
    block.remove(permanently=permanently)
    action = "Permanently deleted" if permanently else "Deleted (soft)"
    typer.echo(f"{action} block {block_id}")


@app.command(name="move-block")
def move_block(
    block_id: str = typer.Argument(..., help="Block to move (URL or ID)"),
    target_id: str = typer.Argument(..., help="Target block (URL or ID)"),
    position: str = typer.Option("after", "--position", "-p", help="before | after | first-child"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Move a block relative to a target block."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    block = client.get_block(block_id)
    if block is None:
        typer.echo(f"Block not found: {block_id}", err=True)
        raise typer.Exit(1)
    target = client.get_block(target_id)
    if target is None:
        typer.echo(f"Target not found: {target_id}", err=True)
        raise typer.Exit(1)
    block.move_to(target, position)
    typer.echo(f"Moved {block_id} {position} {target_id}")


@app.command(name="add-alias")
def add_alias(
    block_id: str = typer.Argument(..., help="Block to alias (URL or ID)"),
    target_page_id: str = typer.Argument(..., help="Page to add the alias to (URL or ID)"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Add an alias (linked copy) of a block to a target page."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    block = client.get_block(block_id)
    if block is None:
        typer.echo(f"Block not found: {block_id}", err=True)
        raise typer.Exit(1)
    target = client.get_block(target_page_id)
    if target is None:
        typer.echo(f"Target page not found: {target_page_id}", err=True)
        raise typer.Exit(1)
    target.children.add_alias(block)
    typer.echo(f"Added alias of {block_id} to {target_page_id}")


@app.command(name="add-database-row")
def add_database_row(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    properties: str = typer.Option(..., "--properties", "-p", help='JSON object, e.g. \'{"Name":"New row","Tags":["A"]}\''),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Add a row to a database."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    collection = _resolve_collection(client, database_id)
    if collection is None:
        typer.echo(f"Database not found: {database_id}", err=True)
        raise typer.Exit(1)
    props = json.loads(properties)
    row = collection.add_row(**props)
    typer.echo(f"Created row: {row.id}")


@app.command(name="update-database-row")
def update_database_row(
    row_id: str = typer.Argument(..., help="Row block ID"),
    properties: str = typer.Option(..., "--properties", "-p", help='JSON object, e.g. \'{"Name":"Updated"}\''),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Update a database row's properties."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    row = client.get_block(row_id)
    if row is None:
        typer.echo(f"Row not found: {row_id}", err=True)
        raise typer.Exit(1)
    props = json.loads(properties)
    for k, v in props.items():
        setattr(row, k, v)
    typer.echo(f"Updated row {row_id}")


@app.command(name="delete-database-row")
def delete_database_row(
    row_id: str = typer.Argument(..., help="Row block ID"),
    permanently: bool = typer.Option(False, "--permanently", help="Permanently delete"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Delete a database row."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    row = client.get_block(row_id)
    if row is None:
        typer.echo(f"Row not found: {row_id}", err=True)
        raise typer.Exit(1)
    try:
        row.remove(permanently=permanently)
    except TypeError:
        row.remove()
    typer.echo(f"Deleted row {row_id}")


# ---------------------------------------------------------------------------
# Auth commands
# ---------------------------------------------------------------------------

@auth_app.command(name="whoami")
def whoami(
    token: str = typer.Option(None, "--token", "-t"),
) -> None:
    """Show current token (masked) and space."""
    from notion.auth import resolve_auth
    try:
        cfg = resolve_auth(token_arg=token)
    except Exception as e:
        typer.echo(f"Auth error: {e}", err=True)
        raise typer.Exit(1)
    tok = cfg["token"]
    masked = f"{tok[:12]}...{tok[-6:]}" if len(tok) > 20 else tok
    typer.echo(f"token: {masked}")
    typer.echo(f"space_id: {cfg.get('space_id') or '(not set — use `notion auth use-space <id>`)'}")


@auth_app.command(name="use-space")
def use_space(
    space_id: str = typer.Argument(..., help="Space ID to set as current"),
) -> None:
    """Set the current space (persisted to config file)."""
    from notion.auth import save_space
    save_space(space_id)
    typer.echo(f"Saved space_id={space_id} to config.")


@auth_app.command(name="spaces")
def spaces(
    token: str = typer.Option(None, "--token", "-t"),
) -> None:
    """List all spaces the token has access to."""
    client = get_client(token_arg=token)
    from notion.auth import resolve_auth
    cfg = resolve_auth(token_arg=token)
    store = client._store
    space_ids = list(store._values.get("space", {}).keys())
    if not space_ids:
        typer.echo("No spaces found.")
        return
    for sid in space_ids:
        space = client.get_space(sid)
        if space:
            name = space.name if hasattr(space, "name") else "(unknown)"
            marker = " *" if sid == cfg.get("space_id") else ""
            typer.echo(f"  {sid}  {name}{marker}")


if __name__ == "__main__":
    app()