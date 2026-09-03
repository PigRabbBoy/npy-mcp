# Changelog

All notable changes to unpy-mcp are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **File-reading write tools are confined to a directory** (`unpy-mcp`).
  `import_csv` and `create_media` would open any path the server process
  could read and push it into Notion — an exfiltration path for a remote
  Bearer holder over HTTP, or for prompt injection over stdio. They now
  refuse paths outside `NOTION_MCP_FILE_ROOT` (default: the working
  directory; set `/` to allow any path). The CLI is unaffected.
- **HTTP transport binds the Notion token per request** (`unpy-mcp`). The
  Streamable HTTP app now runs stateless, so each request re-resolves its
  own `X-Notion-Token`. Previously the SDK froze the token from the
  `initialize` request for the whole session, so a later `X-Notion-Token`
  was ignored and a client that omitted it on the first request silently
  used the server's own `NOTION_TOKEN_V2` identity.
- **Bounded the per-token client cache** and keyed it by token digest
  instead of the raw token, so a caller sending many distinct tokens can no
  longer grow it without limit or leave raw tokens in a process-wide dict.
- **Installer hardening** (`scripts/install.*`): configs holding the token
  are written mode `0600`, only the most recent `.bak` is kept (also
  `0600`), and a project-scoped config is added to `.gitignore` with a
  warning so the token is not committed. The `uvx --from git+…` reference
  is pinned to a release tag instead of tracking `master`.
- `uv.lock` is now committed so Docker builds and installs resolve a
  reproducible dependency set.
- **Removed a live `file_token` cookie and device identifiers from the vcr
  cassettes.** Response `Set-Cookie` headers were never filtered
  (`filter_headers` only covers request headers), so `client_init.yaml`
  carried a real Notion `file_token` plus `device_id` /
  `notion_browser_id`. All response `Set-Cookie` headers are stripped from
  the cassettes, and a `before_record_response` hook keeps them out of
  future re-records. The leaked token must be invalidated separately
  (Notion → Settings → Log out of all devices).
- **`token_v2` cookie is scoped to Notion hosts** (`unpy-core`). The
  session cookie was created without a domain, so `requests` attached it to
  every URL the session fetched — external image sources, S3 presigned
  URLs, redirect targets. It is now set only for `.notion.com` and
  `.notion.so`.
- **`get_image` never sends the session to third parties.** An image block
  whose source is an external URL is downloaded with a plain cookie-less
  request; only Notion hosts go through the authenticated session. Non
  http(s) sources are rejected.
- Real space/page IDs used as examples in `README*.md` and `TOOLS.md`
  replaced with placeholder IDs.
- **Sanitized vcr test recordings** (`tests/fixtures/recordings/`): the
  cassettes were captured from a live session with the token already
  replaced (`FAKE_TOKEN_FOR_TESTS_ONLY`), but still carried personal
  data — real name, personal email, Google avatar URL, user/space/page
  UUIDs, and private page titles. All replaced with stable fake values
  (`Test User`, `test-user@example.com`, `11111111-…`-style IDs, "Sample
  Project Workspace"). Recordings stay committed (tests replay them
  offline); `tests/fixtures/recordings/README.md` documents the
  sanitization policy for future re-records.

### Fixed
- **HTTP transport on a non-loopback bind answered 421 to every real
  hostname** (`--host 0.0.0.0`, the Docker default). The SDK's
  DNS-rebinding protection was configured for localhost only because
  `streamable_http_app()` was called without `host=`. The bind host is now
  passed through: loopback binds keep the automatic localhost-only
  protection, and the new `NOTION_MCP_ALLOWED_HOSTS` env var (comma-separated,
  e.g. `mcp.example.com:*`) turns it on for public hostnames.
- `docker-compose.yml` still pointed at the pre-rename
  `packages/npy-mcp/Dockerfile`.

## [1.0.0] - 2026-09-03

### BREAKING — project renamed: notion-py → **unpy-mcp**

**unpy** = **un**official Notion **p**ython.

- **Python imports**: `notion` → `unpy`, `notion_cli` → `unpy_cli`,
  `notion_mcp` → `unpy_mcp`. Code that did `from notion.client import
  NotionClient` must change to `from unpy.client import NotionClient`.
- **Packages**: `npy-core`/`npy-cli`/`npy-mcp` → `unpy-core`/`unpy-cli`/
  `unpy-mcp` (uv workspace + install names).
- **Entry points**: `notion` CLI command → `unpy`; `notion-mcp` MCP
  command → `unpy-mcp` (`python -m unpy_mcp`).
- **Config directory**: `~/.config/notion-py` → `~/.config/unpy-mcp`.
  A one-time automatic migration copies `config.toml` + `token` from the
  legacy directory on first run (legacy dir left in place).
- **MCP server registration name** (the key inside AI-client configs):
  `notion-py` → `unpy-mcp`. Re-running the installer updates existing
  configs; manual setups must rename the key.
- **Env vars unchanged**: `NOTION_TOKEN_V2`, `NOTION_SPACE_ID`,
  `NOTION_ALLOW_WRITE`, `NOTION_MCP_AUTH_TOKEN`, `NOTION_CONFIG_DIR`,
  `NOTION_TOKEN` — all keep their names.
- GitHub repo (`PigRabbBoy/npy-mcp`) and Docker Hub (`pigrabbboy/npy-mcp`)
  keep their names; installer raw-URLs are unchanged.
- Dockerfile ENTRYPOINT → `unpy-mcp`; docker-compose service/image renamed.
- Internal data dir default `~/.notion-py` → `~/.unpy-mcp` (rarely used;
  override with `NOTION_DATA_DIR`).

### Fixed
- `python -m unpy_cli` module path in docs; `argparse` prog name.

### Added
- **One-command installer** ([ADR-0009](docs/adr/0009-shell-installer-merge-write.md)):
  - macOS/Linux: `curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.sh | bash`
  - Windows: `irm https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.ps1 | iex`
  - Multiselect target clients (Claude Desktop, Claude Code, Cursor, VS Code,
    Codex, opencode, Windsurf), guided `NOTION_TOKEN_V2` / `NOTION_SPACE_ID`
    collection with how-to hints, opt-in write gate, automatic uv install,
    and Merge Write into each client's config (timestamped backups, other
    MCP servers untouched). Re-running updates values in place.
  - Flag mode for scripting: `--client`, `--token`, `--space`,
    `--allow-write`, `--scope global|project`.
- Paired uninstallers: `scripts/uninstall.sh` / `scripts/uninstall.ps1` —
  remove only the `unpy-mcp` entry from chosen clients.

## [0.11.0] - 2026-09-02

### Fixed
- **`reverse_name` on relation columns now actually creates the two-way
  synced property on the target database** (issue #5). Previously
  `autoRelate` was recorded on the forward property but no reverse property
  was ever created — relations were silently one-way and rollups naming the
  missing reverse failed. Notion's own client builds two-way relations by
  writing a property on *both* collections in one transaction (captured live
  via `CollectionSettingsSetupRelation.handleAddRelation`); unpy-mcp now
  replicates that exactly: forward + reverse properties with symmetric
  `"property"` back-references, `version: v2`, `autoRelate` disabled.
- Schema writes now use Notion's current `updateCollectionPropertySchema`
  command with a `primitiveOp` wrapper — plain `set`/`update` on the schema
  path is rejected with 400 by the API. The record store unwraps these ops
  locally so caches stay consistent.
- A forward relation carrying a `property` back-reference is rejected by
  Notion (400) unless the reverse property lands in the same transaction —
  `create_database` and `add_column` now write forward+reverse pairs
  together. Self-referencing relations (target == own database) use a single
  property pointing at itself, matching Notion's own shape.
- **Row-level two-way sync**: setting a two-way relation on a row
  (`row.Prop = [...]`) now maintains the reverse side automatically (adds
  this row to the targets' reverse property, removes it from rows that were
  unlinked) — Notion's server only does this for its own client.
- Rollup failures in `add_column` now surface the real reason
  (`Cannot add rollup column: relation property 'X' not found…`) instead of
  a bare `Error executing tool add_column`.
- `create_database`/`add_column` docstrings: `"limit": 1` documented
  correctly as capping the relation at one linked row (was misleadingly
  described as "single-property mode", easy to confuse with the official
  API's one-way `single_property`).

### Added
- `build_collection_schema_update()` in `notion.operations` — builds the
  `updateCollectionPropertySchema` op shape for schema writes.
- `CollectionRowBlock._sync_two_way_relation()` — maintains the reverse
  property on linked rows in one transaction.
- 4 new tests (126 total): two-way relation op shape, store unwrapping of
  `updateCollectionPropertySchema`, row-level reverse sync add/remove.

### Verified live
- Forward+reverse pairs created via `add_column(reverse_name=…)` and
  `create_database(columns=[{type: relation, reverse_name: …}])` render as
  two-way synced relations in the Notion UI (screenshot-verified), and
  linking a row through the forward property populates the reverse property
  on the target row.

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
- All `uvx`/`pip` commands now use `#subdirectory=packages/unpy-mcp` (build was failing without it)
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
- README title from `unpy-mcp v2` to `npy-mcp — Notion MCP Server + CLI`
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
- Initial release of unpy-mcp by jamalex
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

## [0.7.1] - 2026-08-21

### Added
- Cross-checked interpreter against **Notion's production JS bundle** (extracted webpack chunk map → downloaded 2,170 lazy chunks → located formula registry). Findings now implemented:
  - `padStart(text, targetLength, padString=" ")` / `padEnd(...)` — undocumented in help docs
  - `splice(list, startIndex, deleteCount = 0, ...items)` (list operator; also works on text)
  - `"seconds"` / `"milliseconds"` units for `dateAdd/dateSubtract/dateBetween`
  - `formatDate(date, format, timezone?)` optional third arg accepted
- All 18 registry operators confirmed already supported (`unaryMinus/unaryPlus/larger/smaller/largerEq/smallerEq/...`).
- +4 unit tests (79 total). Live sweep: computed=0 across all dashboard databases.

## [0.7.2] - 2026-08-24

### Security
- **Timing-safe Bearer comparison**: `BearerTokenVerifier` now uses `hmac.compare_digest` instead of `==`, preventing timing side-channel token extraction.
- **Bind guard against open exposure**: `run_http` now refuses to start an unauthenticated server on a non-loopback host (`0.0.0.0` etc.) — previously the Docker default entrypoint (HTTP on 0.0.0.0, no auth env) silently exposed full Notion read/write to the network. Override with `NOTION_MCP_ALLOW_OPEN=1` or set `NOTION_MCP_AUTH_TOKEN`.

### Changed
- Dockerfile: pinned `uv` image tag (`latest` → `0.9.13`) for supply-chain reproducibility; container now runs as non-root user.

### Audited (no action needed)
- OSV/pip-audit over all 57 locked dependencies: **0 known vulnerabilities**; lockfile already at latest versions.
- Code scan: no `eval`/`exec`/unsafe deserialization/shell-out; request logging never emits auth headers.
- New tests: 6 security tests (85 total).

## [0.7.3] - 2026-08-24

### Fixed
- Smoke test flakiness: Notion's search index is eventually consistent and can lag well past a minute, so the space-wide search retry window was raised from ~60s (20×3s) to up to ~300s (60×5s), and now checks before sleeping so fast-indexed runs return instantly.

## [0.8.0] - 2026-08-24

### Fixed
- **Date write corruption** (highest value): writing a plain string to a date
  property silently stored an empty value (`isinstance` check never matched
  strings). Strings are now coerced via `NotionDate.from_isoformat()` —
  `"2026-01-31"` and `"2026-01-31T14:30"` work; invalid strings raise.
- Relation columns render as `Title (URL)` instead of bare titles or reprs.
- CLI no longer leaks raw Python reprs (`<CollectionRowBlock ...>`,
  `<NotionDate ...>`) in markdown or `--format json` — CLI and MCP now share
  one renderer (`notion.render`, npy-core).

### Added
- **Relation column creation**: `target_database_id` + optional `limit: 1`
  (single-property mode) + optional `reverse_name` (two-way sync).
- **Formula column creation**: `expression` with `{"Prop Name"}` refs; fpp
  metas carry property ids + collection pointers (verified rendering in the
  Notion web UI), `result_type` in the shape the UI requires.
- **Rollup column creation**: relation/target resolved by property NAME,
  `aggregation` optional; evaluation path now resolves target collection via
  the row's relation schema when the rollup has no pointer.
- **get_database `full_schema`**: relation targets, rollup configs, formula
  expressions, select options — rich enough for idempotent provisioning.
- **query_database `fetch_all`**: internal queryCollection has NO cursor
  pagination (probed: startCursor/after/searchAfter all ignored) but one
  request can return the full set — fetch_all uses CollectionQuery's
  limit=-1 remote-total path and reports the row count.
- **Local file upload for `files` properties**: pass a filesystem path to a
  files-type row property → uploads via getUploadSpaceFileUrl + S3 PUT and
  attaches (URL-only before).
- `NotionDate.__str__/__repr__`; `render_property`/`render_properties`
  exported from npy-core.

### Verified live
- Full provisioning round-trip (Projects DB + Tasks DB with relation, formula
  `if({"Done"},...)`, rollup sum) rendered correctly in the Notion web UI —
  schema shape matched against UI-created databases (fpp `property` +
  `collection` metas, `result_type` snake_case, rollup `version: v2`).
- 112 tests (+27).

## [0.8.1] - 2026-09-02

### Fixed
- **Issue #1**: writing a local file path to a `files` property crashed with
  `NameError: name 'mimetype' is not defined` — the MIME type was inlined
  into the upload payload but never bound; the S3 PUT then read the missing
  name. Now bound once at the top of the local-path branch (matching
  block.py), live-verified with a real upload.

### Docs (Issue #2)
- TOOLS.md: `add_column` documents relation/formula/rollup specs including
  `autoRelate` semantics (omitting `reverse_name` = one-way, no backref
  column); create_database type list includes formula/rollup/time columns;
  write-tools heading corrected 9 → 16; `full_schema`/`fetch_all` documented.
- README: Write gate section now points at the "All 23 tools" table instead
  of maintaining a second, stale enumeration (7 read / 16 write).

## [0.9.0] - 2026-09-02

### Added
- **Issue #3 — row identity in reads**: `query_database` (MCP) prepends an
  `id` column to its table; `get_database` sample rows start with
  `id: …` lines; the CLI's `query-database`/`get-database` return
  `{"id", "url", "properties": {…}}` per row (nested so a user column named
  "id" can't shadow identity). Read-then-write loops now work end-to-end
  with no extra search round-trip.
- **Issue #4 — full CLI/MCP parity (15 → 23 commands)**: new
  `get-image`, `create-database`, `add-column`, `create-media`,
  `create-embed`, `create-table`, `create-columns`, `import-csv`.
  Schema provisioning (relation/formula/rollup) is now scriptable —
  `notion create-database --columns '<json>'`,
  `notion add-column --options '<json>'`, plus
  `get-database --full-schema` and `query-database --fetch-all` flags.
  Shared implementations live in npy-mcp (`_import_csv_impl`,
  `_embed_type_map`) so CLI and MCP never drift.

### Fixed
- **Core**: resolving a pre-existing block mid-transaction returned None
  (in-transaction fetches were deferred to post-commit), which made
  `add_row(Project=["<id>"])` fail on fresh clients when the target wasn't
  in the local store. The store now performs a real syncRecordValues
  round-trip when a mid-transaction read misses. Relation writes raise a
  clear `Relation target not found` instead of a bare AttributeError.
- Live-verified: full provisioning (2 DBs, relation+formula+rollup) +
  read-modify-write loop entirely through the CLI.
- 117 tests (+4).

## [0.10.0] - 2026-09-02

### Added — Comments support (read + write)
- **`get_comments(block_id)`** (npy-core) / **`get_comments`** MCP tool / **`notion get-comments`** CLI:
  reads every comment thread on a page or block — discussion context, comment
  text (user mentions as `@…`), author, created/edited timestamps, resolved
  state. Discussions ride in the block's own loadPageChunk recordmap; the
  authoritative comment list is re-synced per thread.
- **`add_comment(block_id, text, discussion_id?)`** (npy-core) / **`add_comment`**
  MCP tool (write-gated) / **`notion add-comment`** CLI: posts a comment as a
  new thread or a reply. Op shapes captured from the web client:
  new threads create the discussion via an *update* op + `block.discussions`
  listAfter (PageDiscussion.useSubmitNewDiscussion); replies set the comment
  record + `discussion.comments` listAfter. Live-verified both paths persist
  and render in the Notion UI.
- MCP surface: 27 tools (9 read / 18 write). CLI gains `get-comments` and
  `add-comment`.

### Notable
- `get_comments` returns only `alive` comments in rendered output; resolved
  threads can be filtered with `include_resolved=false` / `--open-only`.
- 122 tests (+2).
