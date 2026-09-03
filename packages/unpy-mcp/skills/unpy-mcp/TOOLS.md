# Notion MCP — Full Tool Reference

## Read tools (8 — always available)

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
{"page_id": "44444444-4444-4444-8444-444444444444", "depth": 2}
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
{"block_id": "44444444-4444-4444-8444-444444444444"}
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
| `full_schema` | bool | false | Also dump full column definitions (relation targets, rollup configs, formula expressions, select options) — for idempotent provisioning diffs |

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
| `fetch_all` | bool | false | Fetch every row regardless of limit (the internal API has no cursor — one request returns the full set) |

**Example call:**
```json
{"database_id": "308bd4f4-b4de-80a5-9199-efa43e7f3bee", "limit": 50}
```

**Returns:** Markdown listing of database rows with all properties.

---

---

### `get_comments`

Read all comment threads attached to a page or block.

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Page/block URL or ID (required) |
| `include_resolved` | bool | true | If false, skip resolved (closed) threads |

**Example call:**
```json
{"block_id": "44444444-4444-4444-8444-444444444444", "include_resolved": false}
```

**Returns:** Markdown list of discussions, each with its comments
(author, text, timestamps, resolved state).

---

### `get_image`

Download an image block and return it as an MCP image content block —
the client renders it natively as an image (~157 tokens for a typical
diagram) instead of base64 text (~37k tokens). Notion's image proxy needs
token_v2 auth, so this fetch happens through the server's session.

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Image block URL or ID (required) |

**Example call:**
```json
{"block_id": "44444444-4444-4444-8444-444444444444"}
```

**Returns:** MCP ImageContent (rendered as an image by the client).
On error, a text message (block not found or not an image block).

## Write tools (19 — gated by `NOTION_ALLOW_WRITE=1`)

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

### `create_database`

Create a new database (collection) under a parent page.

| Arg | Type | Default | Description |
|---|---|---|---|
| `parent_id` | string | — | Parent page URL or ID (required) |
| `title` | string | — | Database title (required) |
| `columns` | string | "" | JSON array of column specs (optional) |
| `icon` | string | "" | Emoji icon (optional) |
| `full_page` | bool | false | If true, creates full-page database |

**Column spec format:**
```json
[
  {"name": "Status", "type": "select", "options": ["Todo", "Done"]},
  {"name": "Priority", "type": "select", "options": ["High", "Low"]},
  {"name": "Done", "type": "checkbox"}
]
```

**Supported column types:** title, text, number, select, multi_select, date, person, checkbox, url, email, phone_number, file, relation, formula, rollup, status, created_time, last_edited_time, created_by, last_edited_by.

**Example call:**
```json
{"parent_id": "page-id", "title": "Tasks", "columns": "[{\"name\":\"Task\",\"type\":\"title\"},{\"name\":\"Status\",\"type\":\"select\",\"options\":[\"Todo\",\"Done\"]},{\"name\":\"Project\",\"type\":\"relation\",\"target_database_id\":\"<db-id>\",\"reverse_name\":\"Tasks\"}]"}
```

**Two-way relations:** a relation spec with `reverse_name` creates a mirrored
property on the target database in the same transaction (Notion's native
two-way shape). Self-relations (target = same database) use one property
pointing at itself.

**Returns:** Database block ID.

---

### `add_column`

Add a column to an existing database.

| Arg | Type | Default | Description |
|---|---|---|---|
| `database_id` | string | — | Database URL or ID (required) |
| `name` | string | — | Column name (required) |
| `type` | string | — | Column type (required) |
| `options` | string | "" | select/multi_select/status: JSON array of values. relation: `{"target_database_id","limit":1?,"reverse_name"?}` — `reverse_name` creates a two-way synced relation: a mirrored property on the target database (forward+reverse written in one transaction); omitting it creates a one-way relation. formula: `{"expression"}` (refs as `{"Prop Name"}`). rollup: `{"relation_property","target_property","aggregation"?}` |

**Example call:**
```json
{"database_id": "db-id", "name": "Due Date", "type": "date"}
```

**Returns:** Confirmation message with new column ID.

---

### `rename_column`

Rename a database column (low-risk, reversible).

| Arg | Type | Default | Description |
|---|---|---|---|
| `database_id` | string | — | Database URL or ID (required) |
| `column` | string | — | Current column name or property id (required) |
| `new_name` | string | — | The new column name (required) |

**Example call:**
```json
{"database_id": "44444444-4444-4444-8444-444444444444", "column": "Old Name", "new_name": "New Name"}
```

**Returns:** Confirmation with the property id and new name.

---

### `delete_column`

Delete a database column. Destroys the data in that property for every
row — confirm with the user before calling. Notion keeps the property
recoverable in its deleted-schema store.

| Arg | Type | Default | Description |
|---|---|---|---|
| `database_id` | string | — | Database URL or ID (required) |
| `column` | string | — | Column name or property id (required) |
| `permanently` | bool | false | Deprecated/ignored (Notion's own flow always soft-removes) |

**Example call:**
```json
{"database_id": "44444444-4444-4444-8444-444444444444", "column": "Kill"}
```

**Returns:** Confirmation with the removed column's id. The title column
cannot be deleted.

---

### `create_media`

Create a media block (image, video, audio, file, pdf) from URL or file upload.

| Arg | Type | Default | Description |
|---|---|---|---|
| `parent_id` | string | — | Parent page URL or ID (required) |
| `type` | string | — | Media type: image, video, audio, file, pdf (required) |
| `url` | string | "" | Source URL |
| `file_path` | string | "" | Local file path for upload |
| `caption` | string | "" | Optional caption |

**Example call:**
```json
{"parent_id": "page-id", "type": "image", "url": "https://example.com/cat.png"}
```

**Returns:** Confirmation with created block ID.

---

### `create_embed`

Create an embed block (tweet, figma, gist, miro, html, etc.).

| Arg | Type | Default | Description |
|---|---|---|---|
| `parent_id` | string | — | Parent page URL or ID (required) |
| `type` | string | — | Embed type (required) |
| `url` | string | — | Source URL to embed (required) |
| `caption` | string | "" | Optional caption |

**Supported types:** embed, bookmark, tweet, gist, figma, loom, typeform, codepen, maps, invision, framer, drive, html, miro, excalidraw, replit, deepnote, sketch, abstract, mixpanel.

**Example call:**
```json
{"parent_id": "page-id", "type": "bookmark", "url": "https://example.com"}
```

**Returns:** Confirmation with created block ID.

---

### `create_table`

Create a simple table (not a database) with specified dimensions.

| Arg | Type | Default | Description |
|---|---|---|---|
| `parent_id` | string | — | Parent page URL or ID (required) |
| `rows` | int | 3 | Number of rows |
| `cols` | int | 2 | Number of columns |

**Example call:**
```json
{"parent_id": "44444444-4444-4444-8444-444444444444", "rows": 3, "cols": 3}
```

**Returns:** Confirmation with created table block ID.

---

### `create_columns`

Create a column layout with N columns.

| Arg | Type | Default | Description |
|---|---|---|---|
| `parent_id` | string | — | Parent page URL or ID (required) |
| `num_columns` | int | 2 | Number of columns (1-10) |

**Example call:**
```json
{"parent_id": "44444444-4444-4444-8444-444444444444", "num_columns": 3}
```

**Returns:** Confirmation with column_list block ID and individual column block IDs.

---

### `import_csv`

Import a CSV file as a new database.

| Arg | Type | Default | Description |
|---|---|---|---|
| `parent_id` | string | — | Parent page URL or ID (required) |
| `file_path` | string | — | Path to CSV file (required) |
| `title` | string | "" | Database title (defaults to filename) |

**Example call:**
```json
{"parent_id": "44444444-4444-4444-8444-444444444444", "file_path": "/tmp/tasks.csv", "title": "Imported Tasks"}
```

**Returns:** Confirmation with created database block ID and row count.

---

### `add_comment`

Add a comment to a page — starts a new thread, or replies into an
existing one when `discussion_id` is given.

| Arg | Type | Default | Description |
|---|---|---|---|
| `block_id` | string | — | Page/block URL or ID (required) |
| `text` | string | — | Comment text (required, plain text) |
| `discussion_id` | string | "" | Existing thread id to reply into (omit = new thread) |

**Example call (new thread):**
```json
{"block_id": "44444444-4444-4444-8444-444444444444", "text": "Please review section 2 before Friday"}
```

**Example call (reply to a thread):**
```json
{"block_id": "44444444-4444-4444-8444-444444444444", "text": "Done, left two notes", "discussion_id": "faabf819-a8b9-400e-b2d7-92eb97b4cf3e"}
```

**Returns:** Confirmation with the new comment id and discussion id.
On failure, an error message (e.g. invalid thread id).

---

## Environment variables

| Variable | Effect on tools |
|---|---|
| `NOTION_TOKEN_V2` | Notion session token. Required for all tools. |
| `NOTION_SPACE_ID` | Bind to a specific space. Affects `search`, `list_pages`. |
| `NOTION_ALLOW_WRITE` | Set to `1` to enable 19 write tools. Without it, only 8 read tools appear. |
| `X-Notion-Token` header | Per-request Notion token (HTTP only). Overrides `NOTION_TOKEN_V2`. |
| `NOTION_MCP_AUTH_TOKEN` | Bearer token for HTTP auth (not used in stdio). |

## Known limitations

### Formula and rollup columns

`get_database` and `query_database` evaluate formulas via a **full Notion
formula interpreter** (`formula_eval.py`) — the internal API never returns
computed values, so we parse the schema's `formula2.code` and run it
client-side. Coverage matches the official function list
(https://www.notion.com/help/formula-syntax):

- **Logic**: `if`, `ifs`, ternary `? :`, `and/or/not`, comparisons
- **Variables**: `let`, `lets`
- **Math**: full operator set (`+ - * / % ^`), `add…sign`, `round(2-arg)`,
  `pi/e/log/exp/sqrt/cbrt`
- **Dates**: `now/today/dateAdd/dateSubtract/dateBetween (all units)/
  parseDate/formatDate/year/month/day/date/week/hour/minute/timestamp/
  fromTimestamp/dateStart/dateEnd`
- **Lists**: `at/first/last/slice/concat/sort(+key λ)/reverse/join/split/
  unique/includes/find/findIndex/filter/map/some/every/flat/length`
- **Text**: `contains/test/match/replace/replaceAll/lower/upper/trim/repeat/
  substring/format/formatNumber/toNumber/link/style(unstyled output)`,
  plus bundle-only extras verified against Notion's production JS:
  `padStart/padEnd`, `splice(list, start, deleteCount?, ...items)`,
  `seconds`/`milliseconds` units for dateAdd/Subtract/Between,
  `formatDate(date, fmt, timezone?)`
- **People**: `.name()/.email()`
- **Empty semantics**: blank operands propagate as blanks (matching Notion),
  never render as `(computed)`.

Unsupported shapes fall back to `(computed)`; a rollup with no related rows shows `(empty)`; evaluated booleans render as Notion's own 'true'/'false'.
Legacy v1 string-expression formulas (`{"expression": ...}`) are not parsed.

## Error messages

| Error | Cause | Fix |
|---|---|---|
| `Page not found: <id>` | Block ID doesn't exist or token lacks access | Verify the ID; check `list_pages` for valid IDs |
| `Database not found: <id>` | Not a database block, or wrong ID | Call `get_database` with the correct collection_view block ID |
| `401 Client Error: Unauthorized` | token_v2 is invalid or expired | Extract a fresh `token_v2` from browser DevTools |
| `Write commands require NOTION_ALLOW_WRITE=1` | Write attempted without gate env var | Set `NOTION_ALLOW_WRITE=1` on the server |
| `Unsupported field: <name>` | `update_block` called with invalid field | Use `"title"` or `"checked"` only |
| `Cannot add rollup column: relation property 'X' not found…` | Rollup names a relation property that doesn't exist on this database | Check the property name with `get_database(full_schema=true)` first |
| `Relation target database '<id>' not found` | Relation target doesn't exist or token lacks access | Verify the target database ID |

### Column blocks and depth >1

`get_page` at `depth > 1` may not render column block children. Notion's
`loadPageChunk` endpoint returns 400 for column blocks — the server falls
back to `syncRecordValues` which loads the block but not its children. Use
`depth: 1` for pages with column layouts, or fetch individual column block
IDs returned by `create_columns`.