# unpy-mcp

A cookie-based client for Notion's internal API (v3), exposing read and write
operations through a CLI and an MCP server (stdio + HTTP). **unpy** =
**un**official Notion **p**ython. Built on the archived notion-py codebase,
modernised for Python 3.12+ and renamed from notion-py (v0.x) to unpy-mcp.

## Language

**Token**:
A `token_v2` cookie value extracted from a logged-in Notion browser session.
Grants full-session access to every Space the owning user is a member of.
_Avoid_: cookie, session, API key, credential

**Space**:
A Notion workspace. A Token may have access to multiple Spaces; exactly one
is the Current Space at any time.
_Avoid_: workspace, account

**Current Space**:
The Space bound to a Client instance at init time. All search and create
operations are scoped to it. Switching requires re-initialising the Client.
_Avoid_: active space, selected space

**Page**:
A Notion page block. Has a title, icon, and a list of child blocks.
_Avoid_: document, note

**Block**:
A single content node inside a Page (text, header, todo, callout, embed, etc.).
May itself contain children (column, toggle).
_Avoid_: node, element

**Database**:
A Notion database (the `Collection` type in the legacy code). Has a schema of
columns and contains rows. The canonical user-facing term; `collection` is
an internal alias only.
_Avoid_: collection, table

**Row**:
A single record in a Database. Properties follow the Database schema.
_Avoid_: collection row, item, entry

**View**:
A saved presentation of a Database (table, board, gallery, calendar, list).
_Avoid_: collection view

**Write Operation**:
Any call that mutates Notion state: create, append, update, move, delete,
add alias, add Database Row, update Row property, delete Row.
_Avoid_: mutation, change

**Markdown Export**:
Server-side export of a Page or Block to CommonMark via Notion's
`getBlockExport` endpoint. The default output format for read tools.
_Avoid_: extract, render, dump

**Recording**:
A saved HTTP request/response pair captured from a live Notion session,
replayed by the test suite to avoid hitting Notion in CI.
_Avoid_: fixture, snapshot, mock

**Embed Block**:
A block that renders external content inline (tweet, figma, gist, miro, etc.).
Has a source URL and a Notion-assigned type. Distinguished from Media blocks
which can be uploaded.
_Avoid_: widget, iframe, integration

**Media Block**:
A block that holds binary content (image, video, audio, file, pdf). Can be
created from a URL or uploaded via `getUploadFileUrl` → S3 PUT.
_Avoid_: attachment, upload, binary block

**Inline Database**:
A database embedded as a block within a page (`collection_view`), as opposed
to a full-page database (`collection_view_page`).
_Avoid_: inline table, embedded database

**Import Operation**:
A Write Operation that creates Pages or Databases from external file formats
(CSV, Markdown, etc.). Parses files locally and creates blocks via
`saveTransactionsFanout`.
_Avoid_: file import, data import

**Synced Block**:
A block whose content is mirrored from a source block. Edits to the source
propagate to all synced copies.
_Avoid_: mirror block, duplicate block

**Property Type**:
The data type of a Database column (title, text, number, select, date, etc.).
Determined by the schema's `type` field. The `status` type is handled as an
alias of `select` in the internal API.
_Avoid_: column type, field type, data type

**Installer**:
The one-command bootstrap script (`scripts/install.sh` on macOS/Linux,
`scripts/install.ps1` on Windows) that prepares uvx, collects credentials,
and writes MCP configs for the user's chosen AI clients.
_Avoid_: setup script, bootstrap, one-click install

**Target Client**:
An AI application the Installer can configure (Claude Desktop, Claude Code,
Cursor, VS Code, Codex, opencode, Windsurf). Each has its own config file
path and entry shape; the Installer hides this variety behind one flow.
_Avoid_: app, editor, host

**Merge Write**:
The Installer's way of editing a client config: load the existing file,
change only the `unpy-mcp` entry, save — never touching other entries —
after copying the original to a timestamped `.bak-*` backup. Re-running the
Installer updates the existing entry in place.
_Avoid_: overwrite, replace, reset