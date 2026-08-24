# Changelog

All notable changes to npy-mcp are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.8] - 2026-08-21

### Fixed
- Image blocks now emit `[image] <source>` instead of being silently skipped in `get_page`
- Embed/video/file/audio/pdf blocks emit `[type] <source>` markers
- Simple tables (`type=table`) render as markdown table from children
- `collection_view` blocks with lazy-loaded collections now resolve via `view_ids → collection_view record → collection_pointer → get_collection()` — previously showed `(no collection)` or crashed
- `get_database` and `query_database` no longer crash on lazy-loaded collections (`'NoneType' object has no attribute 'items'`)
- `get_database` returns helpful error message for blocks without collections (was raw Python error)
- Bookmark/figma/tweet/gist/drive/loom/typeform/codepen/maps/invision/framer blocks emit `[type] <source>` markers

## [0.2.7] - 2026-08-21

### Fixed
- `get_page` now emits `[inline database] <name> — use get_database("<id>")` stubs for `collection_view`/`collection_view_page` blocks — previously silently skipped, making pages with inline DBs appear empty
- `search` and `list_pages` now show DB name for `collection_view` blocks instead of empty title
- `_get_inline_db_name()` resolves DB name via `view_ids → collection_view record → collection_pointer → collection` (handles lazy-loaded collections where `.collection` is None)
- Collection name parsed from Notion rich-text format to plain text

## [0.2.6] - 2026-08-20

### Added
- All requests now mimic browser headers: `User-Agent` (Chrome), `Accept: application/json`, `Referer`, `Origin`, `x-notion-active-user-header`, `x-notion-space-id` — reduces bot detection risk and rate-limit differences vs browser sessions

## [0.2.5] - 2026-08-20

### Changed
- Formula/rollup limitation documented in `get_database` and `query_database` docstrings + TOOLS.md "Known limitations" section — Notion evaluates these browser-side (JavaScript), the internal API does not return values; read source relation columns directly instead

## [0.2.4] - 2026-08-20

### Fixed
- User rendering now consistent across `get_database` and `query_database` — uses `.get()` from store data instead of lazy property attrs (was returning email on one call, name on another for the same user)
- `CollectionRowBlock` checked before `User` in `_render_property` — both have `.email`/`.role`/`.id`, but only CollectionRowBlock has `.title_plaintext` (was rendering relation titles as UUIDs)
- Formula/rollup columns now show `(computed)` instead of empty cells — Notion computes these browser-side, the API doesn't return values

## [0.2.3] - 2026-08-20

### Fixed
- Non-emoji icons (URL, attachment, SVG path) stripped from `list_pages` and `search` titles — emoji icons kept inline
- `query_database` now returns a real markdown table instead of key/value blocks (saves tokens for wide databases)
- `list_pages` skips entries with empty titles (was showing `[page]` with no content)
- User rendering now consistent across `get_database` and `query_database` (name → email → id fallback)

## [0.2.2] - 2026-08-20

### Fixed
- Notion property values now render as readable strings instead of Python repr (User → email/name, CollectionRowBlock → title, NotionDate → ISO date)
- Column keys use original schema names instead of transliterated slugs (e.g. "Folder ใบเสนอราคา" not "folder_aibesn_raakhaa")
- `get_block` returns type hint for non-text blocks instead of empty string
- Icon prefix stripped from page titles in `_block_summary`
- `query_database` docstring corrected: "Markdown listing" not "Markdown table"
- Invalid/expired token no longer crashes MCP server — returns helpful error message instead
- All `uvx`/`pip` commands now use `#subdirectory=packages/npy-mcp` (build was failing without it)
- `--refresh` flag added to all uvx configs so MCP server auto-updates from git on restart

### Added
- Claude Code config (`.mcp.json` / `~/.claude.json`) for all 3 stdio setup options
- Codex config (`~/.codex/config.toml`) for all 3 stdio setup options
- "Setting your space ID" section with 3 methods + resolution order
- "How to find your space ID" with 3 methods (CLI, DevTools, URL)

## [0.2.1] - 2026-08-20

### Added
- AI skill for MCP tools (`SKILL.md` + `TOOLS.md`) with tool selection guide, workflows, and full reference
- Release skill (`SKILL.md` + `REFERENCE.md`) for version bump, tag, changelog, and GitHub Release
- "AI Skill" section in README with install instructions for opencode / Claude Desktop / Cursor

### Changed
- README title from `notion-py v2` to `npy-mcp — Notion MCP Server + CLI`
- Repo URL updated to `PigRabbBoy/npy-mcp`
- Added 3 stdio setup methods (uvx, Docker, pip) for Claude Desktop/Cursor/VS Code

## [0.2.0] - 2026-08-20

### Added
- Monorepo structure (uv workspace): `npy-core`, `npy-cli`, `npy-mcp`
- Core library: NotionClient with API v3 fixes (`saveTransactionsFanout`, `value.value` nesting, `app.notion.com` base URL)
- CLI: Typer-based, 15 commands (6 read + 9 write) + 3 auth subcommands
- MCP server: MCP SDK v2, 15 tools (6 read + 9 write gated by `NOTION_ALLOW_WRITE=1`)
- MCP HTTP transport: streamable-http + Bearer auth + RFC 9728 discovery + per-request `X-Notion-Token`
- Docker support: multi-stage Dockerfile (196MB) + docker-compose with healthcheck
- Auth model: `token_v2` env → config file, no browser capture (ADR-0004)
- Write gate: `NOTION_ALLOW_WRITE=1` gates 9 write tools/commands (ADR-0005)
- 57 tests (markdown 21, auth 17, operations 6, client 8, MCP server 5) with vcr.py recordings
- 5 ADRs + CONTEXT.md domain glossary

### Changed
- `settings.py` BASE_URL: `www.notion.so` → `app.notion.com`
- `client.py` `submitTransaction` → `saveTransactionsFanout` with pointer-based payload
- All regex patterns fixed to use raw strings (no SyntaxWarnings on Python 3.12)

## [0.1.0] - 2021-01-28

### Added
- Initial release of notion-py by jamalex
- Cookie-based Notion client (unofficial)
- Block, Collection, User, Space models
- Markdown export support
## [0.2.9] - 2026-08-21

### Added
- Image blocks now emit downloadable Notion proxy URL (`https://app.notion.com/image/<attachment>?table=block&id=<block_id>&spaceId=...&userId=...`) — auth via token_v2 cookie, works with `curl` or any HTTP client
- `_build_image_url()` constructs proxy URL from `attachment:<file_id>:<filename>` source
- Image marker shows filename + proxy URL: `[image] image.png — https://app.notion.com/image/...`

## [0.3.0] - 2026-08-21

### Added
- New `get_image(block_id)` read tool — downloads image blocks through the server's authenticated session and returns base64 data URI (`data:<mime>;base64,<data>`). Agent can read Notion images directly without needing cookie auth.
- Image marker in `get_page` now shows `use get_image("<block_id>") to download` instead of dead proxy URL
- 7 read tools + 9 write tools = 16 total (was 15)

## [0.3.1] - 2026-08-21

### Fixed
- `get_image` now returns MCP `ImageContent` (native image block) instead of base64 text — client renders as image (~157 tokens) not text (~37k tokens). Fixes "result exceeds maximum allowed tokens" error.
- Uses `mcp.server.mcpserver.Image(data=bytes, format=fmt)` with `structured_output=False`

## [0.4.0] - 2026-08-21

### Added
- Full read coverage for all 52 Notion block types (was 38)
- 14 new block classes: Heading 4 (sub_sub_sub_header), SyncedBlock, SimpleTable, TableOfContents, LinkToPage, HTML, Miro, Excalidraw, Replit, Deepnote, Sketch, Abstract, Mixpanel, PdfEmbed
- Column rendering: column_list renders children with `--- Column N ---` headers, column is transparent container
- Synced block rendering: renders children recursively (no data loss)
- New block type markers: breadcrumb, factory, link_to_collection, table_of_contents, link_to_page
- Extended embed type list: html, miro, excalidraw, replit, deepnote, sketch, abstract, mixpanel
- test_block_types_registered test (58 total tests)

### Fixed
- No more silent data loss: column_list, column, synced_block, breadcrumb, factory, link_to_collection, link_to_page now render instead of returning empty string

## [0.4.1] - 2026-08-21

### Added
- `create_database` tool — creates inline database with optional full schema. Supports all property types (title, text, number, select, multi_select, date, person, checkbox, url, email, phone_number, file, relation).
- `add_column` tool — adds a column to an existing database. Supports all property types including status.
- `status` property type — handled as alias of select in collection.py for both read and write.
- 18 total tools (7 read + 11 write).

## [0.4.2] - 2026-08-21

### Added
- `create_media` tool — creates image/video/audio/file/pdf blocks from URL or local file upload.
- `create_embed` tool — creates embed blocks for all 20 embed types (embed, bookmark, tweet, gist, figma, loom, typeform, codepen, maps, invision, framer, drive, html, miro, excalidraw, replit, deepnote, sketch, abstract, mixpanel).
- `create_table` tool — creates a simple table block with specified dimensions.
- Extended `append_blocks` — now supports toggle, equation, subsubheader (13 types total, was 10).
- 21 total tools (7 read + 14 write).

## [0.5.0] - 2026-08-21

### Added
- `import_csv` tool — parses CSV file locally, creates inline database with headers as columns, inserts all rows.
- `create_columns` tool — creates a column_list layout with N empty column blocks.
- 23 total tools (7 read + 16 write).

### Changed
- MAJOR version bump: new capability (import). Import is a new tool category that creates databases from external file formats.

## [0.5.1] - 2026-08-21

### Fixed
- `import_csv`: use slugify() for column names — no more duplicate "Name 1" column bug.
- Column block read: fallback from `loadPageChunk` to `syncRecordValues` for non-page blocks. 400 errors logged at debug level instead of error.
- `_tree_to_markdown`: None guard for blocks that fail to load (no crash on column blocks at depth >1).
- `create_database`: added `full_page` parameter — creates full-page database (collection_view_page) when true.

### Updated
- TOOLS.md: 23 tools (7 read + 16 write), all new tools documented, column block depth limitation noted.

## [0.5.2] - 2026-08-21

### Fixed
- `create_media` file upload: now uses `getUploadSpaceFileUrl` endpoint with `record:{table:'block',id,spaceId}` in request body. Reads `putHeaders` from response and sends `x-amz-tagging` header with S3 PUT (was causing 403 Forbidden). Verified: upload PNG → get_image downloads it back successfully.

## [0.5.3] - 2026-08-21

### Fixed
- Column children now render at depth=2 (was requiring depth≥4). Container blocks (column_list, column, synced_block) no longer consume a depth level — they pass depth through to children. Verified: `get_page(depth=2)` shows column headers + children content.

## [0.6.0] - 2026-08-21

### Added
- **Formula/rollup evaluator** — `get_database` and `query_database` now compute real values for 12 common formula shapes instead of showing `(computed)`:
  rollups, `.at(0)` derefs, `.map().join()`, chained derefs (formula→block),
  `sort().reverse().at(0)` (renders row title), `.length()`, filtered counts/sums,
  `dateBetween` (Notion floor semantics), `dateAdd` with fractional years/months,
  and rate×qty multiplication.
- Stub-aware lazy fetch: relation targets left as property-less stubs by
  queryCollection are now transparently refetched.

### Changed
- Complex expressions (`if`/`lets`/nested arithmetic) still render as `(computed)`
  — read their source columns and compute agent-side when needed.
- Verified against live BML MA Dashboard: days-until-renewal matches browser
  values on 9/11 projects exactly (±1 day on multi-year dateAdd rounding).

## [0.7.0] - 2026-08-21

### Added
- **Full Notion formula interpreter** (`formula_eval.py`) — replaces pattern-matching with a real tokenizer + recursive-descent parser + AST evaluator implementing the complete official function set (notion.com/help/formula-syntax): if/ifs/ternary, let/lets, full math operators & functions, all date functions, list lambdas (filter/map/sort/every/...), text functions, person .name()/.email(), Notion blank-propagation semantics.
- 17 new unit tests for the interpreter language core (75 total).

### Changed
- Formula evaluation coverage on live BML MA Dashboard workspace: **(computed) count went from 480+ → 0** across all 8 databases (~720 formula cells in Subscription DB alone).
- Empty formula bodies now render as "" instead of "(computed)".
