---
name: unpy-mcp
description: >-
  Interact with Notion via MCP tools — search, read, create, update, delete
  pages, blocks, database rows, and comments. Use when the user asks to read
  or write Notion content, search Notion, manage Notion databases, comment on
  a Notion page, or when a Notion page URL or ID is mentioned.
---

# Notion MCP

## Tool selection guide

| User wants to... | Use this tool |
|---|---|
| Find a page or block by name | `search` |
| Read a page + its children | `get_page` |
| Read a single block | `get_block` |
| View an image/file from a page | `get_image` |
| See all top-level pages | `list_pages` |
| See a database's columns + sample rows | `get_database` |
| List rows from a database | `query_database` |
| Read comments on a page | `get_comments` |
| Create a new page | `create_page` |
| Add content blocks to a page | `append_blocks` |
| Edit a block's text or checkbox | `update_block` |
| Delete a page or block | `delete_block` |
| Move a block | `move_block` |
| Add a linked copy of a block | `add_alias` |
| Add a row to a database | `add_database_row` |
| Edit a database row's properties | `update_database_row` |
| Delete a database row | `delete_database_row` |
| Create a database with typed columns | `create_database` |
| Add a column to an existing database | `add_column` |
| Attach an image/file | `create_media` |
| Embed external content (YouTube, Figma…) | `create_embed` |
| Add a table / column layout | `create_table` / `create_columns` |
| Import a CSV as a database | `import_csv` |
| Comment on a page (new thread or reply) | `add_comment` |

**8 read tools** are always available. **17 write tools** require
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

### Read and join a discussion on a page
1. Call `get_comments` with the page ID to see existing threads.
2. To reply, call `add_comment` with the same `block_id`, your text, and the
   `discussion_id` of the thread. Omit `discussion_id` to start a new thread.

### Build a two-way relation between databases
1. Call `get_database` on both databases to confirm their IDs.
2. Call `add_column` on one with `type="relation"`, `options` containing
   `{"target_database_id": "<other-db-id>", "reverse_name": "<mirror name>"}`.
3. The mirrored property appears on the target database automatically —
   links propagate to both sides.

## Write safety

- **Write tools may be hidden** — if `NOTION_ALLOW_WRITE` is not set, only read
  tools appear. Don't assume write tools are available; check first.
- **Always confirm before deleting** — ask the user before calling `delete_block`
  or `delete_database_row`. Use `permanently=false` (soft delete) by default;
  only use `permanently=true` if the user explicitly asks.
- **`append_blocks` takes a JSON string** — the `blocks` argument is a JSON array
  string, not individual arguments. Example:
  `[{"type":"text","text":"Hello"},{"type":"todo","text":"Task","checked":true}]`
- **`add_comment` posts publicly** — anyone with page access sees it. Confirm
  wording with the user if the request is ambiguous.

## Output format

All tools return **markdown strings** by default. Read tools return formatted
markdown (headers, lists, tables). Write tools return confirmation messages
with IDs or URLs. `get_image` returns a native MCP image content block.
If you need structured JSON, use the CLI with `--format json` instead.

## Full tool reference

See [TOOLS.md](./TOOLS.md) for every tool's arguments, types, and examples.