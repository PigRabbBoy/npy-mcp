# notion-py v2

A cookie-based client for Notion's internal API (v3), exposing read and write
operations through a CLI and an MCP server (stdio + HTTP). Built on the
archived notion-py codebase, modernised for Python 3.12+.

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