# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unofficial Python 3.12+ client for Notion.so's internal API (v3). Provides a core
library, CLI, and MCP server — all powered by the `token_v2` cookie from a logged-in
Notion browser session. Works for Guest users (unlike the official Notion API).

**Authentication**: Uses `token_v2` cookie from a logged-in Notion browser session.

## Monorepo Structure (v2)

```
notion-py/
├── pyproject.toml              ← uv workspace root
├── packages/
│   ├── npy-core/src/notion/    ← Core library (was notion/ in v1)
│   ├── npy-cli/src/notion_cli/ ← CLI (Typer, 15 commands)
│   └── npy-mcp/src/notion_mcp/ ← MCP server (stdio + HTTP, 15 tools)
├── tests/                      ← pytest + vcr.py (57 tests)
├── docs/adr/                   ← 5 Architecture Decision Records
├── CONTEXT.md                  ← Domain glossary
└── run_smoke_test.py           ← Legacy smoke test (live Notion)
```

## Commands

```bash
# Install (dev)
uv sync --extra dev

# Run tests (57 tests, no live Notion calls)
python -m pytest tests/ -v

# Run smoke test (requires live Notion credentials)
python run_smoke_test.py --page [NOTION_PAGE_URL] --token [NOTION_TOKEN_V2]
# Or set NOTION_TOKEN env var instead of --token

# CLI
PYTHONPATH=packages/npy-core/src:packages/npy-cli/src python -m notion_cli --help

# MCP server (stdio for Claude Desktop)
PYTHONPATH=packages/npy-core/src:packages/npy-mcp/src python -m notion_mcp

# MCP server (HTTP with auth)
NOTION_MCP_AUTH_TOKEN=secret python -m notion_mcp --transport http --port 8000
```

## Environment Variables

- `NOTION_TOKEN_V2` — primary auth token (cookie value)
- `NOTION_TOKEN` — legacy fallback token
- `NOTION_SPACE_ID` — space to bind as current space
- `NOTION_ALLOW_WRITE` — set to `1` to enable write commands/tools
- `NOTION_MCP_AUTH_TOKEN` — Bearer token for MCP HTTP transport
- `NOTION_CONFIG_DIR` — config directory (default `~/.config/notion-py`)
- `NOTIONPY_LOG_LEVEL` — logging level: debug, info, warning, error, disabled

## Architecture (v2)

### Core (`npy-core`)

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

### CLI (`npy-cli`)

- **Typer** framework, 15 commands (6 read + 9 write) + 3 auth subcommands.
- Write commands gated by `NOTION_ALLOW_WRITE=1` env var.
- Output: Markdown (default) or JSON (`--format json`).

### MCP Server (`npy-mcp`)

- **MCP Python SDK v2** (`MCPServer` + decorator pattern).
- 15 tools (6 read + 9 write), write tools gated by `NOTION_ALLOW_WRITE=1`.
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