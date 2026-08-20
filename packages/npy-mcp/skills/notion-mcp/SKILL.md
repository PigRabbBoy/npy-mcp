---
name: notion-mcp
description: >-
  Interact with Notion via MCP tools — search, read, create, update, delete
  pages, blocks, and database rows. Use when the user asks to read or write
  Notion content, search Notion, manage Notion databases, or when a Notion
  page URL or ID is mentioned.
---

# Notion MCP

## Tool selection guide

| User wants to... | Use this tool |
|---|---|
| Find a page or block by name | `search` |
| Read a page + its children | `get_page` |
| Read a single block | `get_block` |
| See all top-level pages | `list_pages` |
| See a database's columns + sample rows | `get_database` |
| List rows from a database | `query_database` |
| Create a new page | `create_page` |
| Add content blocks to a page | `append_blocks` |
| Edit a block's text or checkbox | `update_block` |
| Delete a page or block | `delete_block` |
| Move a block | `move_block` |
| Add a linked copy of a block | `add_alias` |
| Add a row to a database | `add_database_row` |
| Edit a database row's properties | `update_database_row` |
| Delete a database row | `delete_database_row` |

**6 read tools** are always available. **9 write tools** require
`NOTION_ALLOW_WRITE=1` on the server — if they're missing, write is disabled.

## Common workflows

### Read a page you don't have the ID for
1. Call `list_pages` to see top-level pages, OR call `search` with a keyword.
2. Copy the page ID or URL from the result.
3. Call `get_page` with that ID (`depth=1` for direct children, `depth=2` for deeper).

### Create a new page with content
1. Call `list_pages` or `search` to find the parent page ID.
2. Call `create_page` with `parent_id` and `title`.
3. Call `append_blocks` on the new page ID with a JSON array of blocks.

### Work with a database
1. Call `search` or `list_pages` to find the database ID.
2. Call `get_database` to see columns + sample rows (understand the schema).
3. Call `query_database` to list rows, or `add_database_row` to add one.

### Update a todo checkbox
1. Call `get_page` to find the todo block ID.
2. Call `update_block` with `field="checked"` and `value="true"` (or `"false"`).

## Write safety

- **Write tools may be hidden** — if `NOTION_ALLOW_WRITE` is not set, only read
  tools appear. Don't assume write tools are available; check first.
- **Always confirm before deleting** — ask the user before calling `delete_block`
  or `delete_database_row`. Use `permanently=false` (soft delete) by default;
  only use `permanently=true` if the user explicitly asks.
- **`append_blocks` takes a JSON string** — the `blocks` argument is a JSON array
  string, not individual arguments. Example:
  `[{"type":"text","text":"Hello"},{"type":"todo","text":"Task","checked":true}]`

## Output format

All tools return **markdown strings** by default. Read tools return formatted
markdown (headers, lists, tables). Write tools return confirmation messages
with IDs or URLs. If you need structured JSON, use the CLI with `--format json`
instead.

## Full tool reference

See [TOOLS.md](./TOOLS.md) for every tool's arguments, types, and examples.