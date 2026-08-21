# Changelog

All notable changes to npy-mcp are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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