# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**unpy-mcp** (**un**official Notion **p**ython) — Unofficial Python 3.12+ client for Notion.so's internal API (v3). Provides a core
library, CLI, and MCP server — all powered by the `token_v2` cookie from a logged-in
Notion browser session. Works for Guest users (unlike the official Notion API).
Renamed from notion-py (v0.x) to unpy-mcp in v1.0.0: imports are `unpy`,
`unpy_cli`, `unpy_mcp`; config lives in `~/.config/unpy-mcp` (legacy
`~/.config/notion-py` is auto-migrated on first run).

**Authentication**: Uses `token_v2` cookie from a logged-in Notion browser session.

## Monorepo Structure (v2)

```
unpy-mcp/
├── pyproject.toml              ← uv workspace root
├── packages/
│   ├── unpy-core/src/unpy/    ← Core library (was `notion/` before the unpy rename)
│   ├── unpy-cli/src/unpy_cli/ ← CLI (Typer, 25 commands)
│   └── unpy-mcp/src/unpy_mcp/ ← MCP server (stdio + HTTP, 27 tools)
├── tests/                      ← pytest + vcr.py (126 tests)
├── docs/adr/                   ← 5 Architecture Decision Records
├── CONTEXT.md                  ← Domain glossary
└── run_smoke_test.py           ← Legacy smoke test (live Notion)
```

## Commands

```bash
# Install (dev)
uv sync --extra dev

# Run tests (126 tests, no live Notion calls)
python -m pytest tests/ -v

# Run smoke test (requires live Notion credentials)
python run_smoke_test.py --page [NOTION_PAGE_URL] --token [NOTION_TOKEN_V2]
# Or set NOTION_TOKEN env var instead of --token

# CLI
PYTHONPATH=packages/unpy-core/src:packages/unpy-cli/src python -m unpy_cli --help

# MCP server (stdio for Claude Desktop)
PYTHONPATH=packages/unpy-core/src:packages/unpy-mcp/src python -m unpy_mcp

# MCP server (HTTP with auth)
NOTION_MCP_AUTH_TOKEN=secret python -m unpy_mcp --transport http --port 8000
```

## Environment Variables

- `NOTION_TOKEN_V2` — primary auth token (cookie value)
- `NOTION_TOKEN` — legacy fallback token
- `NOTION_SPACE_ID` — space to bind as current space
- `NOTION_ALLOW_WRITE` — set to `1` to enable write commands/tools
- `NOTION_MCP_AUTH_TOKEN` — Bearer token for MCP HTTP transport
- `NOTION_MCP_ALLOWED_HOSTS` — comma-separated Host allowlist (e.g. `mcp.example.com:*`)
  that keeps DNS-rebinding protection on for non-loopback HTTP binds; loopback binds
  are protected automatically
- `NOTION_MCP_FILE_ROOT` — directory the file-reading write tools (`import_csv`,
  `create_media`) may open; default is the working directory, `/` disables the limit
- `NOTION_CONFIG_DIR` — config directory (default `~/.config/unpy-mcp`)
- `NOTIONPY_LOG_LEVEL` — logging level: debug, info, warning, error, disabled

## Architecture (v2)

### Core (`unpy-core`)

- **`NotionClient`** (`client.py`): Main entry point. HTTP session with retry logic,
  RecordStore, auth, transaction submission via `saveTransactionsFanout` endpoint.
- **`Record`** (`records.py`): Base class. All data proxied through RecordStore.
- **`Block`** (`block.py`): 38+ subclasses registered in `BLOCK_TYPES` dict.
- **`Collection` / `CollectionRowBlock`** (`collection.py`): Databases and rows.
  Row properties auto-generated from schema as slugified attributes.
- **`RecordStore`** (`store.py`): Thread-safe central cache.
- **`auth.py`**: Token + Space resolution (env → config → prompt).
- **`markdown.py`**: Notion rich-text ↔ CommonMark conversion.
- **`operations.py`**: Transaction operation builder.

### CLI (`unpy-cli`)

- **Typer** framework, 25 commands + 3 auth subcommands.
- Write commands gated by `NOTION_ALLOW_WRITE=1` env var.
- Output: Markdown (default) or JSON (`--format json`).

### MCP Server (`unpy-mcp`)

- **MCP Python SDK v2** (`MCPServer` + decorator pattern).
- 27 tools (8 read + 19 write), write tools gated by `NOTION_ALLOW_WRITE=1`.
- Two transports: `stdio` (local, default) and `streamable-http` (remote).
- HTTP transport supports Bearer token auth via `NOTION_MCP_AUTH_TOKEN`.

### Key Fixes from v1 → v2

1. `settings.py`: `BASE_URL` changed `www.notion.so` → `app.notion.com`
2. `client.py`: Handles nested `value.value` in `user_root` records
3. `client.py`: `submitTransaction` → `saveTransactionsFanout` with new payload format
   (pointer-based operations wrapped in transactions)
4. All regex patterns fixed to use raw strings (no SyntaxWarnings on Python 3.12)

### Data Flow

```
NotionClient (client.py)
  ├── HTTP Session (requests + retry for 429/502/503/504)
  ├── RecordStore (store.py) — central thread-safe cache
  └── Record instances (Block, Collection, User, Space)
        └── Always read/write through RecordStore, never hold state locally
```

## Testing

- **57 tests** in `tests/`:
  - `test_markdown.py` (21) — markdown ↔ notion conversion
  - `test_auth.py` (17) — token/space resolution logic
  - `test_operations.py` (6) — operation builder
  - `test_client.py` (8) — integration via vcr.py recordings
  - `test_mcp_server.py` (5) — MCP tool registration + schemas
- **vcr.py recordings** in `tests/fixtures/recordings/` — captured once from
  live Notion, replayed in tests (no live calls in CI).
- **Smoke test** (`run_smoke_test.py`) — integration test against live Notion,
  creates and deletes a page tree. Requires real credentials.

## Design Decisions

See `docs/adr/` for 5 ADRs covering: canonical terminology, space binding,
markdown export strategy, auth model, and write gate. See `CONTEXT.md` for
the domain glossary.

## Release Policy

**When to release**: After any code change that affects runtime behavior
(bug fixes, new features, API changes), create a new release. Pure doc-only
changes that don't affect code behavior do NOT require a release.

**Release process**: Use the release skill (`packages/unpy-mcp/skills/release/`).
Steps:
1. Run tests: `python -m pytest tests/ -v`
2. Determine version bump: `fix:` → patch, `feat:` → minor, `breaking` → major
3. Update version in 4 `pyproject.toml` files (root + 3 packages)
4. Update `CHANGELOG.md` (move `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`)
5. Commit: `git commit -m "release: vX.Y.Z"`
6. Tag: `git tag vX.Y.Z`
7. Push: `git push origin master --tags`
8. GitHub Release: `gh release create vX.Y.Z --generate-notes -R PigRabbBoy/npy-mcp`
9. Docker (optional): build + tag + push to `pigrabbboy/npy-mcp:X.Y.Z` + `:latest`

**Never skip releases after behavioral code changes** — users rely on
`--refresh` to pull the latest fix from git. An unreleased fix means users
keep hitting the old bug.