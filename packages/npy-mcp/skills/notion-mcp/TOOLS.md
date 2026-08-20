# Notion MCP — Full Tool Reference

## Read tools (6 — always available)

### `search`

Search Notion blocks/pages in the current space.

| Arg | Type | Default | Description |
|---|---|---|---|
| `query` | string | — | Search query (required) |
| `limit` | int | 20 | Maximum results |

**Example call:**
```json
{"query": "project status", "limit": 10}
```

**Returns:** Markdown list of matching blocks with type, title, and URL.

---

### `get_page`

Fetch a Notion page and its children tree as markdown.

| Arg | Type | Default | Description |
|---|---|---|---|
| `page_id` | string | — | Page URL or ID (required) |
| `depth` | int | 1 | 0=metadata only, 1=direct children, 2=grandchildren, -1=full tree |

**Example call:**
```json
{"page_id": "670bd233-7435-4dac-9f60-ba9cdb5a10e4", "depth": 2}
```

**Returns:** Markdown rendering of the page and its children (indented by level).

---

### `get_block`

Fetch a single Notion block as markdown.

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Block URL or ID (required) |

**Example call:**
```json
{"block_id": "670bd233-7435-4dac-9f60-ba9cdb5a10e4"}
```

**Returns:** Markdown rendering of the block.

---

### `list_pages`

List top-level pages in the current space.

| Arg | Type | Default | Description |
|---|---|---|---|
| (none) | | | |

**Example call:**
```json
{}
```

**Returns:** Markdown list of pages with title and URL.

---

### `get_database`

Fetch a Notion database schema and sample rows.

| Arg | Type | Default | Description |
|---|---|---|---|
| `database_id` | string | — | Database block URL/ID or collection ID (required) |
| `sample_rows` | int | 5 | Number of sample rows to show |

**Example call:**
```json
{"database_id": "308bd4f4-b4de-80a5-9199-efa43e7f3bee", "sample_rows": 3}
```

**Returns:** Database name, column schema (name + type), and sample row data as markdown.

---

### `query_database`

Query a Notion database and return rows.

| Arg | Type | Default | Description |
|---|---|---|---|
| `database_id` | string | — | Database block URL/ID or collection ID (required) |
| `limit` | int | 20 | Maximum rows to return |

**Example call:**
```json
{"database_id": "308bd4f4-b4de-80a5-9199-efa43e7f3bee", "limit": 50}
```

**Returns:** Markdown listing of database rows with all properties.

---

## Write tools (9 — gated by `NOTION_ALLOW_WRITE=1`)

### `create_page`

Create a new page under a parent block.

| Arg | Type | Default | Description |
|---|---|---|---|
| `parent_id` | string | — | Parent page URL or ID (required) |
| `title` | string | — | Title for the new page (required) |
| `icon` | string | "" | Optional emoji icon (e.g. `"📄"`) |

**Example call:**
```json
{"parent_id": "23cbd4f4-b4de-8087-8ec0-c7a2ebfb18d1", "title": "Meeting Notes", "icon": "📝"}
```

**Returns:** URL of the created page.

---

### `append_blocks`

Append blocks to a page. The `blocks` arg is a **JSON array string**.

| Arg | Type | Default | Description |
|---|---|---|---|
| `page_id` | string | — | Parent page URL or ID (required) |
| `blocks` | string | — | JSON array string (required) |

**Supported block types:**

| `type` | Extra fields | Example |
|---|---|---|
| `text` | — | `{"type":"text","text":"Hello"}` |
| `todo` | `checked` (bool) | `{"type":"todo","text":"Task","checked":true}` |
| `header` | — | `{"type":"header","text":"Title"}` |
| `subheader` | — | `{"type":"subheader","text":"Subtitle"}` |
| `callout` | `icon` (string) | `{"type":"callout","text":"Note","icon":"⚠️"}` |
| `bulleted_list` | — | `{"type":"bulleted_list","text":"Item"}` |
| `numbered_list` | — | `{"type":"numbered_list","text":"First"}` |
| `quote` | — | `{"type":"quote","text":"A quote"}` |
| `code` | — | `{"type":"code","text":"print('hi')"}` |
| `divider` | — | `{"type":"divider"}` |

**Example call:**
```json
{
  "page_id": "4449ef90-c445-40ac-9e4f-9ef101e0c5d9",
  "blocks": "[{\"type\":\"header\",\"text\":\"Agenda\"},{\"type\":\"todo\",\"text\":\"Review PR\",\"checked\":false},{\"type\":\"divider\"}]"
}
```

**Returns:** Confirmation with count of blocks added.

---

### `update_block`

Update a block field.

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Block URL or ID (required) |
| `field` | string | — | `"title"` or `"checked"` (required) |
| `value` | string | — | New value: text for title, `"true"`/`"false"` for checked (required) |

**Example call:**
```json
{"block_id": "0f33e7b5-6c51-4565-835d-165d14ebc3a3", "field": "title", "value": "Updated text"}
```

**Returns:** Confirmation message.

---

### `delete_block`

Delete a block (soft delete by default).

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Block URL or ID (required) |
| `permanently` | bool | false | If true, permanently delete (cannot undo) |

**Example call:**
```json
{"block_id": "4449ef90-c445-40ac-9e4f-9ef101e0c5d9"}
```

**Returns:** Confirmation message.

---

### `move_block`

Move a block relative to a target block.

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Block to move (required) |
| `target_id` | string | — | Target block (required) |
| `position` | string | "after" | `"before"`, `"after"`, or `"first-child"` |

**Example call:**
```json
{"block_id": "aaa-111", "target_id": "bbb-222", "position": "before"}
```

**Returns:** Confirmation message.

---

### `add_alias`

Add an alias (linked copy) of a block to a target page.

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Block to alias (required) |
| `target_page_id` | string | — | Page to add the alias to (required) |

**Example call:**
```json
{"block_id": "aaa-111", "target_page_id": "ccc-333"}
```

**Returns:** Confirmation message.

---

### `add_database_row`

Add a row to a database.

| Arg | Type | Default | Description |
|---|---|---|---|
| `database_id` | string | — | Database block URL/ID or collection ID (required) |
| `properties` | string | — | JSON object string of column_name → value (required) |

**Example call:**
```json
{
  "database_id": "308bd4f4-b4de-80a5-9199-efa43e7f3bee",
  "properties": "{\"page\":\"New Task\",\"tags\":[\"Overview\"]}"
}
```

**Returns:** ID of the created row.

---

### `update_database_row`

Update a database row's properties.

| Arg | Type | Default | Description |
|---|---|---|---|
| `row_id` | string | — | Row block ID (required) |
| `properties` | string | — | JSON object string of column_name → value (required) |

**Example call:**
```json
{
  "row_id": "0298262a-3150-4b83-9def-e806a5bc2a27",
  "properties": "{\"page\":\"Updated title\"}"
}
```

**Returns:** Confirmation message.

---

### `delete_database_row`

Delete a database row.

| Arg | Type | Default | Description |
|---|---|---|---|
| `row_id` | string | — | Row block ID (required) |
| `permanently` | bool | false | If true, permanently delete |

**Example call:**
```json
{"row_id": "0298262a-3150-4b83-9def-e806a5bc2a27"}
```

**Returns:** Confirmation message.

---

## Environment variables

| Variable | Effect on tools |
|---|---|
| `NOTION_TOKEN_V2` | Notion session token. Required for all tools. |
| `NOTION_SPACE_ID` | Bind to a specific space. Affects `search`, `list_pages`. |
| `NOTION_ALLOW_WRITE` | Set to `1` to enable 9 write tools. Without it, only 6 read tools appear. |
| `X-Notion-Token` header | Per-request Notion token (HTTP only). Overrides `NOTION_TOKEN_V2`. |
| `NOTION_MCP_AUTH_TOKEN` | Bearer token for HTTP auth (not used in stdio). |

## Known limitations

### Formula and rollup columns

`get_database` and `query_database` show `(computed)` for formula and rollup
columns. Notion evaluates these **browser-side** (JavaScript) and does not return
values via the internal API. This is a limitation of the cookie-based API, not a
bug — the Python library cannot evaluate Notion formulas without reimplementing
Notion's formula engine.

If you need formula/rollup values, read the source relation columns directly
(e.g. read `ผู้ประสานงาน` column instead of the `ชื่อผู้ประสานงาน` formula that
derives from it).

## Error messages

| Error | Cause | Fix |
|---|---|---|
| `Page not found: <id>` | Block ID doesn't exist or token lacks access | Verify the ID; check `list_pages` for valid IDs |
| `Database not found: <id>` | Not a database block, or wrong ID | Call `get_database` with the correct collection_view block ID |
| `401 Client Error: Unauthorized` | token_v2 is invalid or expired | Extract a fresh `token_v2` from browser DevTools |
| `Write commands require NOTION_ALLOW_WRITE=1` | Write attempted without gate env var | Set `NOTION_ALLOW_WRITE=1` on the server |
| `Unsupported field: <name>` | `update_block` called with invalid field | Use `"title"` or `"checked"` only |