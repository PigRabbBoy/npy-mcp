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

  get-comments     Read comment threads on a page (read)
  add-comment      Comment on a page — new thread or reply (write)

  get-image        Download an image/file block (read)
  export           Export a page/database to PDF/HTML/Markdown & CSV (read)
  create-database  Create a database with full schema — relation/formula/
                   rollup columns (write)
  add-column       Add a column (all types incl. relation/formula/rollup) (write)
  create-media     Image/video/audio/file/pdf from URL or upload (write)
  create-embed     Embed blocks (20 providers) (write)
  create-table     Simple table block (write)
  create-columns   Column layout (write)
  import-csv       CSV → inline database (write)

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
    """Gate write commands behind NOTION_ALLOW_WRITE=1 env var (or
    allow_write = true in the unpy config file)."""
    if os.environ.get("NOTION_ALLOW_WRITE") != "1":
        config_file = os.path.join(
            os.environ.get("NOTION_CONFIG_DIR", os.path.expanduser("~/.config/unpy-mcp")),
            "config.toml",
        )
        if os.path.exists(config_file):
            try:
                import tomllib

                with open(config_file, "rb") as f:
                    if tomllib.load(f).get("allow_write"):
                        return
            except Exception:
                pass
        typer.echo(
            "Write commands require NOTION_ALLOW_WRITE=1 env var "
            "(or allow_write = true in ~/.config/unpy-mcp/config.toml).\n"
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
    full_schema: bool = typer.Option(False, "--full-schema", help="Include full column definitions (relation targets, rollup configs, formula expressions, select options) — rich enough to diff for idempotent provisioning"),
    format: str = typer.Option("markdown", "--format", "-f", help="markdown | json"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Fetch a database schema and sample rows."""
    client = get_client(token_arg=token)
    block = client.get_block(database_id)
    collection = _resolve_collection(client, database_id)
    if collection is None:
        typer.echo(f"Database not found: {database_id}", err=True)
        raise typer.Exit(1)
    try:
        name = collection.name if hasattr(collection, "name") else "(unnamed)"
        schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    except Exception as exc:
        typer.echo(f"Failed to read database schema: {exc}", err=True)
        raise typer.Exit(1)
    if full_schema:
        # rich readback shared with the MCP tool (issue #31) — names, not ids
        from unpy.schema import full_schema_entries
        entries = full_schema_entries(collection, client)
        if format == "json":
            import dataclasses
            payload = {
                "name": name,
                "block_id": block.id if block is not None else None,
                "data_source_id": collection.id,
                "schema": entries,
            }
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=lambda o: dataclasses.asdict(o) if dataclasses.is_dataclass(o) else str(o)))
            return
        lines = [f"# {name}", ""]
        lines.append(f"  block id: {block.id if block is not None else '(none; looked up by data source id)'}")
        lines.append(f"  data source id: {collection.id}")
        lines.append("")
        lines.append("## Columns")
        for prop in schema:
            lines.append(f"  - **{prop.get('name', '?')}** ({prop.get('type', '?')})")
        lines.append("")
        lines.append("## Full schema")
        from unpy.schema import render_full_schema_markdown
        lines.extend(render_full_schema_markdown(collection, client))
        typer.echo("\n".join(lines))
        return
    if format == "json":
        payload = {
            "name": name,
            "block_id": block.id if block is not None else None,
            "data_source_id": collection.id,
            "schema": [{"name": p.get("name", "?"), "type": p.get("type", "?")} for p in schema],
        }
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return
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
    if limit <= 0:
        # 0 or negative = fetch every row
        rows = collection.get_rows(limit=-1)
        if len(rows) == 100:
            # Notion's server-side default page size — the query above may
            # have been capped; re-fetch with an explicit large limit
            rows = collection.get_rows(limit=1000000)
    else:
        rows = collection.get_rows(limit=limit)
    typer.echo(render_rows(rows, format))


# ---------------------------------------------------------------------------
# Write commands (gated by NOTION_ALLOW_WRITE=1)
# ---------------------------------------------------------------------------

@app.command(name="create-page")
def create_page(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    title: str = typer.Option(..., "--title", help="Title for the new page"),
    icon: str = typer.Option("", "--icon", help="Optional emoji icon (e.g. '📄')"),
    blocks: str = typer.Option("", "--blocks", "-b", help='Optional JSON array (same format as append-blocks) — create the page with content in one step'),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create a new page under a parent block, optionally with content."""
    _check_write_enabled()
    from unpy.block import PageBlock
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    page = parent.children.add_new(PageBlock, title=title)
    if icon:
        page.icon = icon
    if blocks:
        from unpy.blocks import add_blocks_from_specs_core, batch_denominator
        specs = json.loads(blocks)
        count, failures = _add_blocks_from_specs_impl(page, specs)
        if failures:
            typer.echo(
                f"Added {count} of {batch_denominator(specs, failures)} block(s); "
                + "; ".join(failures),
                err=True,
            )
            raise typer.Exit(1)
    typer.echo(f"Created page {page.id} — {page.get_browseable_url()}")


def _add_blocks_from_specs_impl(page, specs):
    """Thin wrapper over the core block-spec builder with the CLI type map."""
    from unpy.blocks import add_blocks_from_specs_core

    from unpy.block import (
        BulletedListBlock, CalloutBlock, CodeBlock, DividerBlock,
        EquationBlock, HeaderBlock, NumberedListBlock, QuoteBlock,
        SubheaderBlock, SubsubheaderBlock, TextBlock, TodoBlock, ToggleBlock,
    )

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
    return add_blocks_from_specs_core(page, specs, TYPE_MAP)


@app.command(name="append-blocks")
def append_blocks(
    page_id: str = typer.Argument(..., help="Parent page URL or ID"),
    blocks: str = typer.Option(..., "--blocks", "-b", help='JSON array, e.g. \'[{"type":"text","text":"Hello"},{"type":"todo","text":"Task","checked":true}]\''),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Append blocks to a page. Supports: text, todo, header, subheader, subsubheader, callout, bulleted_list, numbered_list, quote, code (language field), divider, toggle, equation."""
    _check_write_enabled()
    from unpy.blocks import batch_denominator

    client = get_client(token_arg=token)
    parent = client.get_block(page_id)
    if parent is None:
        typer.echo(f"Page not found: {page_id}", err=True)
        raise typer.Exit(1)
    specs = json.loads(blocks)
    count, failures = _add_blocks_from_specs_impl(parent, specs)
    if failures:
        typer.echo(
            f"Added {count} of {batch_denominator(specs, failures)} block(s) to {page_id}; "
            + "; ".join(failures),
            err=True,
        )
        raise typer.Exit(1)
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
    from unpy.auth import resolve_auth
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
    from unpy.auth import save_space
    save_space(space_id)
    typer.echo(f"Saved space_id={space_id} to config.")


@auth_app.command(name="spaces")
def spaces(
    token: str = typer.Option(None, "--token", "-t"),
) -> None:
    """List all spaces the token has access to."""
    client = get_client(token_arg=token)
    from unpy.auth import resolve_auth
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

# ---------------------------------------------------------------------------
# Schema provisioning + content commands (write; get_image is read)
# ---------------------------------------------------------------------------

@app.command(name="get-image")
def get_image(
    block_id: str = typer.Argument(..., help="Image/file block URL or ID"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Download an image/file block's source and save it locally."""
    client = get_client(token_arg=token)
    block = client.get_block(block_id)
    if block is None:
        typer.echo(f"Block not found: {block_id}", err=True)
        raise typer.Exit(1)
    from unpy.block import ImageBlock, FileBlock, PDFBlock, VideoBlock, AudioBlock

    if not isinstance(block, (ImageBlock, FileBlock, PDFBlock, VideoBlock, AudioBlock)):
        typer.echo(f"Block is not a media block: {type(block).__name__}", err=True)
        raise typer.Exit(1)
    url = block.get("source") or ""
    if not url:
        typer.echo("Block has no source URL", err=True)
        raise typer.Exit(1)
    import requests as _rq

    resp = _rq.get(url, timeout=60)
    resp.raise_for_status()
    from pathlib import Path

    filename = url.split("?")[0].split("/")[-1] or "download.bin"
    out = Path(filename)
    out.write_bytes(resp.content)
    typer.echo(f"Saved {len(resp.content)} bytes to {out}")


@app.command(name="export")
def export(
    page_or_database_id: str = typer.Argument(..., help="Page or Database URL or ID"),
    format: str = typer.Option("markdown", "--format", "-f", help="pdf | html | markdown"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Include subpages"),
    output: str = typer.Option(None, "--output", "-o", help="Output directory (default: current directory)"),
    database_views: str = typer.Option("current", "--database-views", help="current | all (views exported as CSV)"),
    page_content: str = typer.Option("everything", "--page-content", help="everything | no_files"),
    flat: bool = typer.Option(False, "--flat", help="Disable 'create folders for subpages' (recursive markdown/html only)"),
    pdf_format: str = typer.Option("Letter", "--pdf-format", help="PDF page size: Letter, Legal, Tabloid, A0-A6"),
    export_comments: bool = typer.Option(False, "--export-comments", help="Include page comments"),
    timezone: str = typer.Option(None, "--timezone", help="IANA timezone (default: local)"),
    timeout: int = typer.Option(120, "--timeout", help="Max seconds to wait for the export task"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Export a Page or Database to PDF/HTML/Markdown & CSV files."""
    from unpy.export import ExportError, export_block

    client = get_client(token_arg=token)
    block = client.get_block(page_or_database_id)
    if block is None:
        typer.echo(f"Block not found: {page_or_database_id}", err=True)
        raise typer.Exit(1)
    try:
        result = export_block(
            client,
            block.id,
            format=format,
            recursive=recursive,
            output_dir=output,
            database_views=database_views,
            page_content=page_content,
            create_folders=not flat,
            pdf_format=pdf_format,
            export_comments=export_comments,
            timezone=timezone,
            timeout=float(timeout),
        )
    except (ExportError, ValueError) as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Exported {block.id} → {result['output_dir']} ({len(result['files'])} file(s))")
    for path in result["files"]:
        typer.echo(f"  {path}")
    if result.get("text"):
        typer.echo()
        typer.echo(result["text"])


@app.command(name="create-database")
def create_database(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    title: str = typer.Option(..., "--title", help="Database title"),
    columns: str = typer.Option("", "--columns", "-c", help='JSON array of column specs, e.g. \'[{"name":"Status","type":"select","options":["Todo","Done"]}]\' — supports relation ({"target_database_id","limit":1?,"reverse_name"?}), formula ({"expression"}), rollup ({"relation_property","target_property","aggregation"?})'),
    icon: str = typer.Option("", "--icon", help="Emoji icon"),
    full_page: bool = typer.Option(False, "--full-page", help="Create a full-page database instead of inline"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create a new database (collection) under a parent page."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    from unpy.block import CollectionViewBlock, CollectionViewPageBlock

    from unpy.operations import build_collection_schema_update
    from unpy.schema import build_collection_schema  # unpy-core, not unpy_mcp (#32)

    deferred = []
    if columns:
        col_specs = json.loads(columns)
        space_id = client.current_space.id if client.current_space else ""
        schema = build_collection_schema(
            [s for s in col_specs if s.get("type") not in ("rollup", "formula")],
            client,
            space_id,
        )
        own_pointer = {"id": "<own>", "table": "collection", "spaceId": space_id}
        for spec in col_specs:
            if spec.get("type") in ("rollup", "formula"):
                spec["_own_schema"] = schema
                spec["_own_pointer"] = own_pointer
                spec["_space_id"] = space_id
        schema = build_collection_schema(col_specs, client, space_id)
        # Two-way relations: a forward prop with a "property" back-ref is
        # rejected unless the reverse prop lands in the same transaction,
        # and create_record can't batch cross-collection schema writes —
        # so strip reverse-bearing relations out of the create payload and
        # write each forward+reverse pair afterwards (matches the MCP tool).
        for spec in col_specs:
            if spec.get("type") == "relation" and spec.get("reverse_name"):
                fwd_pid = spec.get("id")
                fwd = schema.pop(fwd_pid, None)
                if fwd:
                    deferred.append((spec, fwd_pid, fwd))
    else:
        schema = {"title": {"name": "Name", "type": "title"}}
    if full_page:
        cvb = parent.children.add_new(CollectionViewPageBlock)
    else:
        cvb = parent.children.add_new(CollectionViewBlock)
    collection_id = client.create_record("collection", parent=cvb, schema=schema)
    cvb.collection = client.get_collection(collection_id)
    cvb.title = title
    if icon:
        cvb.icon = icon
    cvb.views.add_new(view_type="table")
    if deferred:
        space_id = client.current_space.id if client.current_space else ""
        ops = [build_collection_schema_update(collection_id, fwd_pid, fwd)
               for _, fwd_pid, fwd in deferred]
        for spec, fwd_pid, fwd in deferred:
            reverse_prop = {
                "name": spec.get("reverse_name") or spec.get("name"),
                "type": "relation",
                "collection_id": collection_id,
                "collection_pointer": {
                    "id": collection_id,
                    "table": "collection",
                    "spaceId": space_id,
                },
                "property": fwd_pid,
                "version": "v2",
                "autoRelate": {"enabled": False},
            }
            target_id = fwd.get("collection_id", "")
            if target_id and target_id != collection_id:
                ops.append(build_collection_schema_update(
                    target_id, fwd["property"], reverse_prop
                ))
            else:
                # self-referencing: single prop points at itself
                fwd["property"] = fwd_pid
                ops = [build_collection_schema_update(
                    collection_id, fwd_pid, fwd
                )]
        client.submit_transaction(ops)
    typer.echo(f"Created database: {cvb.id}")


@app.command(name="add-column")
def add_column(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    name: str = typer.Option(..., "--name", help="Column name"),
    type: str = typer.Option(..., "--type", help="Column type (text, number, select, relation, formula, rollup, ...)"),
    options: str = typer.Option("", "--options", "-o", help='select: ["A","B"]; relation: {"target_database_id":...,"limit":1?,"reverse_name"?}; formula: {"expression":"..."} (refs as {"Prop Name"}); rollup: {"relation_property","target_property","aggregation"?}'),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Add a column to an existing database."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    from unpy.schema import add_column_prop, resolve_collection_for_write

    collection = resolve_collection_for_write(client, database_id)
    if isinstance(collection, str):
        typer.echo(collection, err=True)
        raise typer.Exit(1)
    try:
        msg, _pid = add_column_prop(client, collection, name, type, options)
    except ValueError as exc:
        typer.echo(f"Cannot add column: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(msg)


@app.command(name="rename-column")
def rename_column(
    database_id: str = typer.Argument(..., help="Database URL or ID"),
    column: str = typer.Option(..., "--column", "-c", help="Current column name or property id"),
    new_name: str = typer.Option(..., "--name", "-n", help="The new column name"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Rename a database column (low-risk, reversible)."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    from unpy.operations import build_collection_schema_update
    from unpy.schema import find_column, resolve_collection_for_write
    collection = resolve_collection_for_write(client, database_id)
    if isinstance(collection, str):
        typer.echo(collection, err=True)
        raise typer.Exit(1)
    schema = collection.get("schema") or {}
    prop_id, prop = find_column(schema, column)
    if prop_id is None:
        typer.echo(f"Column not found: '{column}'. Use get-database to list columns.", err=True)
        raise typer.Exit(1)
    new_prop = dict(prop)
    new_prop["name"] = new_name
    client.submit_transaction([
        build_collection_schema_update(collection.id, prop_id, new_prop)
    ])
    typer.echo(f"Renamed column '{prop.get('name')}' to '{new_name}' (id: {prop_id})")


@app.command(name="delete-column")
def delete_column(
    database_id: str = typer.Argument(..., help="Database URL or ID"),
    column: str = typer.Argument(..., help="Column name or property id"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Delete a database column (destroys that property's data in every row; recoverable in Notion's UI)."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    from unpy.schema import find_column, resolve_collection_for_write
    collection = resolve_collection_for_write(client, database_id)
    if isinstance(collection, str):
        typer.echo(collection, err=True)
        raise typer.Exit(1)
    schema = collection.get("schema") or {}
    prop_id, prop = find_column(schema, column)
    if prop_id is None:
        typer.echo(f"Column not found: '{column}'. Use get-database to list columns.", err=True)
        raise typer.Exit(1)
    if prop.get("type") == "title":
        typer.echo("Error: the title column cannot be deleted — every database must have exactly one title.", err=True)
        raise typer.Exit(1)
    # Mirror the Notion UI exactly (captured from TableHeaderCell.handleDeleteAccept):
    # move the property into deleted_schema, then null it out of the live schema.
    client.submit_transaction([
        {
            "id": collection.id,
            "path": ["deleted_schema"],
            "table": "collection",
            "command": "updateCollectionDeletedPropertySchema",
            "args": {"primitiveOp": {"command": "update", "args": {prop_id: prop}}},
        },
        {
            "id": collection.id,
            "path": ["schema"],
            "table": "collection",
            "command": "updateCollectionPropertySchema",
            "args": {"primitiveOp": {"command": "update", "args": {prop_id: None}}},
        },
    ])
    typer.echo(f"Deleted column '{prop.get('name')}' (id: {prop_id})")


@app.command(name="set-column-description")
def set_column_description(
    database_id: str = typer.Argument(..., help="Database URL or ID (or collection id)"),
    column: str = typer.Option(..., "--column", "-c", help="Column name or property id"),
    description: str = typer.Option(..., "--description", "-d", help="Description text (empty string clears it)"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Set (or clear) a property's description (the hover help text)."""
    _check_write_enabled()
    from unpy.schema import resolve_collection_for_write, set_property_description

    client = get_client(token_arg=token)
    collection = resolve_collection_for_write(client, database_id)
    if isinstance(collection, str):
        typer.echo(collection, err=True)
        raise typer.Exit(1)
    try:
        prop_id, _old = set_property_description(client, collection, column, description)
    except ValueError as exc:
        typer.echo(f"Cannot set description: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Description of column '{column}' set (id: {prop_id})")


@app.command(name="create-view")
def create_view(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    name: str = typer.Option(..., "--name", help="View name (a view with the same name is updated in place)"),
    type: str = typer.Option("table", "--type", help="table | board | list | gallery | calendar | timeline"),
    filter: str = typer.Option("", "--filter", help='Hand-writable JSON: {"property","operator","value"}, {"and":[...]}/{"or":[...]} (nestable), or {"property","raw":{...}}'),
    sort: str = typer.Option("", "--sort", help='JSON [{"property","direction"}] or shorthand "Name,-Due"'),
    group_by: str = typer.Option("", "--group-by", help="Group by a select/status/person/checkbox/relation column name"),
    properties: str = typer.Option("", "--properties", help='Visible properties in display order: ["Name","Status"] or [{"property","width"?,"visible"?}]'),
    date_property: str = typer.Option("", "--date-property", help="Date column for calendar/timeline views (default: first date column)"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create or update a database view (idempotent by --name)."""
    _check_write_enabled()
    from unpy.collection import CollectionView, COLLECTION_VIEW_TYPES
    from unpy.views import (
        build_view_payload, find_view_by_name,
    )

    client = get_client(token_arg=token)
    collection = _resolve_collection(client, database_id)
    if collection is None:
        typer.echo(f"Database not found: {database_id}", err=True)
        raise typer.Exit(1)

    existing = find_view_by_name(collection, name)
    if existing is not None and getattr(existing, "type", "") != type:
        typer.echo(
            f"Warning: view '{name}' exists as '{existing.type}' — updating in place, keeping type '{existing.type}'",
            err=True,
        )
    existing = find_view_by_name(collection, name)  # resolve again for payload
    try:
        payload = build_view_payload(
            client, collection, type, name,
            filter_spec=filter, sort_spec=sort, group_by=group_by,
            properties=properties, date_property=date_property,
            existing_view=existing,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    for w in payload.get("warnings") or []:
        typer.echo(f"Warning: {w}", err=True)

    if existing is None:
        # create: the view record must live on the database block
        block = getattr(collection, "parent", None)
        block._client._store  # ensure store warmed
        view_id = client.create_record(
            "collection_view",
            parent=block,
            type=type,
            name=name,
            format=payload.get("format") or {},
            **({"query2": payload["query2"]} if payload.get("query2") else {}),
        )
        # mirror parent's view_ids locally so find/list sees it
        ids = block.get("view_ids") or []
        if view_id not in ids:
            ids = ids + [view_id]
            block.set("view_ids", ids)
        typer.echo(f"Created view '{name}' ({type}): {view_id}")
        return

    # update in place (idempotent)
    cls = COLLECTION_VIEW_TYPES.get(existing.get("type", ""), CollectionView)
    vid = existing.id
    ops = []
    if payload.get("query2"):
        ops.append({"table": "collection_view", "id": vid,
                    "path": ["query2"], "command": "update",
                    "args": {"primitiveOp": {"command": "update",
                                             "args": dict(payload["query2"])}}})
    else:
        ops.append({"table": "collection_view", "id": vid,
                    "path": ["query2"], "command": "set", "args": {}})
    if payload.get("format"):
        ops.append({"table": "collection_view", "id": vid,
                    "path": ["format"], "command": "update",
                    "args": {"primitiveOp": {"command": "update",
                                             "args": dict(payload["format"])}}})
    client.submit_transaction(ops)
    typer.echo(f"Updated view '{name}' ({type}): {vid}")


@app.command(name="list-views")
def list_views(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    format: str = typer.Option("json", "--format", "-f", help="json | markdown"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """List a database's views with property NAMES (for provisioning diff)."""
    from unpy.views import list_views as _list_views

    client = get_client(token_arg=token)
    collection = _resolve_collection(client, database_id)
    if collection is None:
        typer.echo(f"Database not found: {database_id}", err=True)
        raise typer.Exit(1)
    views = _list_views(collection, client)
    if format == "json":
        typer.echo(json.dumps({"views": views}, indent=2, ensure_ascii=False))
        return
    if not views:
        typer.echo("(no views)")
        return
    for v in views:
        flags = []
        if v.get("group_by"):
            flags.append(f"group by {v['group_by']}")
        if v.get("date_property"):
            flags.append(f"date {v['date_property']}")
        typer.echo(f"- **{v['name'] or v['id']}** ({v['type']})"
                   + (f" — {', '.join(flags)}" if flags else ""))
        if v.get("sort"):
            typer.echo("    sort: " + ", ".join(
                f"{s['property']} {'↑' if s['direction'] == 'ascending' else '↓'}"
                for s in v["sort"]))
        typer.echo(f"    visible: {', '.join(v.get('visible_properties') or [])}")


@app.command(name="create-template")
def create_template(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    title: str = typer.Option(..., "--title", help="Template title (an existing template with the same title is updated in place)"),
    properties: str = typer.Option("", "--properties", help='Default property values by NAME: {"Status":"Draft","Priority":"Medium"} — options checked strictly against the schema'),
    blocks: str = typer.Option("", "--blocks", "-b", help='Body blocks JSON (same format as append-blocks); replaces the existing body'),
    icon: str = typer.Option("", "--icon", help="Emoji icon"),
    default: bool = typer.Option(False, "--default", help="Make this the default template for every view"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create or update a database template (idempotent by --title)."""
    _check_write_enabled()
    from unpy.schema import resolve_collection_for_write
    from unpy.templates import create_template as _create

    client = get_client(token_arg=token)
    collection = resolve_collection_for_write(client, database_id)
    if isinstance(collection, str):
        typer.echo(collection, err=True)
        raise typer.Exit(1)
    try:
        _row, message = _create(
            client, collection, title,
            properties=properties, blocks=blocks, icon=icon, default=default,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    typer.echo(message)


@app.command(name="list-templates")
def list_templates(
    database_id: str = typer.Argument(..., help="Database block URL/ID or collection ID"),
    format: str = typer.Option("json", "--format", "-f", help="json | markdown"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """List a database's templates with property NAMES (provisioning readback)."""
    from unpy.schema import resolve_collection_for_write
    from unpy.templates import list_templates as _list

    client = get_client(token_arg=token)
    collection = resolve_collection_for_write(client, database_id)
    if isinstance(collection, str):
        typer.echo(collection, err=True)
        raise typer.Exit(1)
    templates = _list(collection, client)
    if format == "json":
        typer.echo(json.dumps({"templates": templates}, indent=2, ensure_ascii=False))
        return
    if not templates:
        typer.echo("(no templates)")
        return
    for t in templates:
        star = " (default)" if t.get("default") else ""
        typer.echo(f"- **{t['title'] or t['id']}**{star}")
        if t.get("icon"):
            typer.echo(f"    icon: {t['icon']}")
        for k, v in (t.get("properties") or {}).items():
            typer.echo(f"    {k}: {v}")
        if t.get("body_blocks"):
            typer.echo(f"    body: {len(t['body_blocks'])} block(s)")


@app.command(name="create-media")
def create_media(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    type: str = typer.Option(..., "--type", help="image | video | audio | file | pdf"),
    url: str = typer.Option("", "--url", help="Source URL"),
    file_path: str = typer.Option("", "--file", help="Local file path to upload"),
    caption: str = typer.Option("", "--caption", help="Caption text"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create a media block from a URL or by uploading a local file."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    from unpy.block import ImageBlock, VideoBlock, AudioBlock, FileBlock, PDFBlock

    TYPE_MAP = {"image": ImageBlock, "video": VideoBlock, "audio": AudioBlock, "file": FileBlock, "pdf": PDFBlock}
    cls = TYPE_MAP.get(type)
    if cls is None:
        typer.echo(f"Unsupported media type: {type}", err=True)
        raise typer.Exit(1)
    block = parent.children.add_new(cls)
    if file_path:
        block.upload_file(file_path)
    elif url:
        block.source = url
        block.display_source = url
    else:
        typer.echo("Either --url or --file is required", err=True)
        raise typer.Exit(1)
    if caption:
        block.caption = caption
    typer.echo(f"Created {type} block: {block.id}")


@app.command(name="create-embed")
def create_embed(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    type: str = typer.Option("embed", "--type", help="embed, bookmark, tweet, gist, figma, loom, typeform, codepen, maps, invision, framer, drive, html, miro, excalidraw, replit, deepnote, sketch, abstract, mixpanel"),
    url: str = typer.Option(..., "--url", help="Source URL to embed"),
    caption: str = typer.Option("", "--caption", help="Caption text"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create an embed block."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    from unpy.block import (
        AbstractBlock, BookmarkBlock, CodepenBlock, DeepnoteBlock, DriveBlock,
        EmbedBlock, ExcalidrawBlock, FigmaBlock, FramerBlock, GistBlock,
        HtmlBlock, InvisionBlock, LoomBlock, MapsBlock, MixpanelBlock,
        MiroBlock, ReplitBlock, SketchBlock, TweetBlock, TypeformBlock,
    )

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
        typer.echo(f"Unsupported embed type: {type} (supported: {supported})", err=True)
        raise typer.Exit(1)
    block = parent.children.add_new(cls)
    block.source = url
    block.display_source = url
    if caption:
        block.caption = caption
    typer.echo(f"Created {type} block: {block.id}")


@app.command(name="create-table")
def create_table(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    rows: int = typer.Option(3, "--rows", help="Number of rows"),
    columns: int = typer.Option(3, "--columns", help="Number of columns"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create a simple table block."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    import uuid as _uuid

    table_id = str(_uuid.uuid4())
    client.create_record(
        "block",
        parent=parent,
        type="table",
        format={"table_columns": columns, "table_blocks": []},
        id=table_id,
    )
    typer.echo(f"Created table ({rows}x{columns}): {table_id}")


@app.command(name="create-columns")
def create_columns(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    count: int = typer.Option(2, "--count", "-n", help="Number of columns"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Create a column layout with N empty columns."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    from unpy.block import ColumnListBlock, ColumnBlock

    cl = parent.children.add_new(ColumnListBlock)
    for _ in range(max(1, count)):
        cl.children.add_new(ColumnBlock)
    typer.echo(f"Created column layout: {cl.id} ({count} columns)")


@app.command(name="import-csv")
def import_csv(
    parent_id: str = typer.Argument(..., help="Parent page URL or ID"),
    file: str = typer.Option(..., "--file", "-f", help="Path to a .csv file"),
    title: str = typer.Option("Imported CSV", "--title", help="Database title"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Import a CSV file as a new inline database."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    parent = client.get_block(parent_id)
    if parent is None:
        typer.echo(f"Parent not found: {parent_id}", err=True)
        raise typer.Exit(1)
    from unpy.csv_import import import_csv_impl

    try:
        db_id = import_csv_impl(client, parent, file, title)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(f"Created database from CSV: {db_id}")


@app.command(name="get-comments")
def get_comments(
    block_id: str = typer.Argument(..., help="Page/block URL or ID"),
    include_resolved: bool = typer.Option(True, "--include-resolved/--open-only", help="Include resolved threads"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Read all comment threads on a page or block."""
    client = get_client(token_arg=token)
    try:
        discussions = client.get_comments(block_id, include_resolved=include_resolved)
    except Exception as exc:
        typer.echo(f"Failed to read comments: {exc}", err=True)
        raise typer.Exit(1)
    if not discussions:
        typer.echo("(no comments)")
        return
    for d in discussions:
        status = " [resolved]" if d["resolved"] else ""
        typer.echo(f"- thread {d['id']}{status} — on: {d['context'] or '(page)'}")
        for c in d["comments"]:
            if not c["alive"]:
                continue
            typer.echo(f"    - {c['text']}  ({c['created_time']}, by {c['author']})")


@app.command(name="add-comment")
def add_comment(
    block_id: str = typer.Argument(..., help="Page/block URL or ID"),
    text: str = typer.Option(..., "--text", help="Comment text"),
    discussion_id: str = typer.Option("", "--thread", help="Existing discussion id to reply into (omit = new thread)"),
    token: str = typer.Option(None, "--token", "-t", help="token_v2 (overrides env/config)"),
) -> None:
    """Add a comment to a page (new thread, or reply with --thread)."""
    _check_write_enabled()
    client = get_client(token_arg=token)
    try:
        result = client.add_comment(
            block_id, text, discussion_id=discussion_id or None
        )
    except Exception as exc:
        typer.echo(f"Failed to add comment: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(
        f"Comment added: {result['comment_id']} (discussion: {result['discussion_id']})"
    )
