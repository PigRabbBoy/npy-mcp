# notion-py v2

Unofficial Python 3.12+ client for Notion's internal API (v3). Provides a core
library, CLI, and MCP server — all powered by the `token_v2` cookie from a
logged-in Notion browser session.

> **Warning**: This uses Notion's internal (undocumented) API via session cookie,
> not the official Notion API. It works for Guest users (unlike the official API)
> but carries risks: ToS violation, cookie expiry, API changes without notice.
> See [docs/adr/](docs/adr/) for design decisions.

## Quick start

```bash
# Install (from source)
git clone https://github.com/pigrabb/notion-py.git
cd notion-py
uv sync

# Set your token (extract from browser DevTools → Application → Cookies → token_v2)
export NOTION_TOKEN_V2="your-token_v2-here"

# Use the CLI
python -m notion_cli list-pages
python -m notion_cli search "project"
python -m notion_cli get-page <PAGE_ID>

# Run the MCP server (for Claude Desktop)
python -m notion_mcp --transport stdio

# Run the MCP server over HTTP (for remote access)
NOTION_MCP_AUTH_TOKEN="your-secret" python -m notion_mcp --transport http --port 8000
```

## Packages

This is a monorepo with three packages:

| Package | Description | Install |
|---|---|---|
| `npy-core` | Core library (NotionClient, Block, Collection, markdown) | `uv add npy-core` |
| `npy-cli` | CLI tool with 15 commands | `uv add npy-cli` |
| `npy-mcp` | MCP server (stdio + HTTP) with 15 tools | `uv add npy-mcp` |

## CLI

```bash
# Read commands
notion search "query" [--limit 20] [--format markdown|json]
notion get-page <PAGE_ID> [--depth 1] [--format markdown|json]
notion get-block <BLOCK_ID> [--format markdown|json]
notion list-pages [--format markdown|json]
notion get-database <DATABASE_ID> [--sample 5]
notion query-database <DATABASE_ID> [--limit 20]

# Write commands (require NOTION_ALLOW_WRITE=1)
notion create-page <PARENT_ID> --title "New Page" [--icon "📄"]
notion append-blocks <PAGE_ID> --blocks '[{"type":"text","text":"Hello"}]'
notion update-block <BLOCK_ID> --field title --value "New title"
notion delete-block <BLOCK_ID> [--permanently]
notion move-block <BLOCK_ID> <TARGET_ID> [--position after]
notion add-alias <BLOCK_ID> <TARGET_PAGE_ID>
notion add-database-row <DATABASE_ID> --properties '{"Name":"New row"}'
notion update-database-row <ROW_ID> --properties '{"Name":"Updated"}'
notion delete-database-row <ROW_ID>

# Auth commands
notion auth whoami
notion auth spaces
notion auth use-space <SPACE_ID>
```

## MCP server

### Local (stdio) — for Claude Desktop

```json
{
  "mcpServers": {
    "notion-py": {
      "command": "python",
      "args": ["-m", "notion_mcp"],
      "env": {
        "NOTION_TOKEN_V2": "your-token_v2-here"
      }
    }
  }
}
```

### Remote (HTTP) — for shared/team access

```bash
# Start server with Bearer auth
NOTION_TOKEN_V2="your-notion-token" \
NOTION_MCP_AUTH_TOKEN="shared-secret" \
python -m notion_mcp --transport http --host 0.0.0.0 --port 8000
```

### Docker — for easy deployment

```bash
# Build image (from repo root)
docker build -t notion-mcp -f packages/npy-mcp/Dockerfile .

# Run container
docker run -d -p 8000:8000 \
  -e NOTION_TOKEN_V2="your-token_v2-here" \
  -e NOTION_MCP_AUTH_TOKEN="shared-secret" \
  -e NOTION_ALLOW_WRITE=0 \
  notion-mcp

# Or with docker compose
cd packages/npy-mcp
cp .env.example .env  # edit with your tokens
docker compose up -d
```

### Per-request Notion token (multi-client)

By default, all HTTP clients share the server's `NOTION_TOKEN_V2`. For
multi-client setups, each client can send its own Notion token via the
`X-Notion-Token` header:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "X-Notion-Token: v03%3AeyJ..." \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

When `X-Notion-Token` is present, the server creates a separate
`NotionClient` for that token (cached per-token). When absent, it falls
back to the server's `NOTION_TOKEN_V2` env var.

Claude Desktop config for remote:
```json
{
  "mcpServers": {
    "notion-py": {
      "url": "http://your-server:8000/mcp",
      "headers": {
        "Authorization": "Bearer shared-secret"
      }
    }
  }
}
```

### Write gate

By default, the MCP server exposes only **6 read tools**. Set
`NOTION_ALLOW_WRITE=1` to unlock **9 additional write tools**:

- Read: `search`, `get_page`, `get_block`, `list_pages`, `get_database`, `query_database`
- Write: `create_page`, `append_blocks`, `update_block`, `delete_block`, `move_block`, `add_alias`, `add_database_row`, `update_database_row`, `delete_database_row`

## Getting your token_v2

1. Open https://app.notion.com in Chrome (logged in)
2. F12 → **Application** tab → **Cookies** → `https://app.notion.com`
3. Find `token_v2` → copy the **Value** (a long string starting with `v03%3A...`)

⚠️ **Security**: `token_v2` = full session access. Anyone with this token can
read/write everything you can. Don't commit it to git, don't share it, and
invalidate it (Notion Settings → Log out of all sessions) when done.

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests (57 tests, no live Notion calls needed)
python -m pytest tests/ -v

# Run smoke test (requires live Notion credentials)
python run_smoke_test.py --page <PAGE_URL> --token <TOKEN_V2>
```

## Architecture

```
notion-py/
├── packages/
│   ├── npy-core/src/notion/      ← Core library
│   │   ├── client.py             ← NotionClient (HTTP session, auth, transactions)
│   │   ├── block.py              ← Block + 38 subclasses
│   │   ├── collection.py         ← Database, Row, View, query builder
│   │   ├── store.py              ← RecordStore (thread-safe cache)
│   │   ├── markdown.py           ← Notion rich-text ↔ CommonMark
│   │   ├── auth.py               ← Token + Space resolution
│   │   └── operations.py         ← Transaction operation builder
│   ├── npy-cli/src/notion_cli/   ← CLI (Typer)
│   │   ├── cli.py                ← 15 commands
│   │   ├── render.py             ← Markdown/JSON formatters
│   │   └── client_factory.py     ← Client builder from auth config
│   └── npy-mcp/src/notion_mcp/   ← MCP server
│       ├── server.py             ← MCPServer + 15 tools
│       ├── transport_http.py     ← HTTP transport + Bearer auth
│       └── __main__.py           ← Entry point (--transport stdio|http)
├── tests/                        ← 57 tests (unit + integration via vcr.py)
├── docs/adr/                     ← 5 Architecture Decision Records
├── CONTEXT.md                    ← Domain glossary
└── pyproject.toml                ← uv workspace root
```

## Design decisions

See [docs/adr/](docs/adr/) for the 5 key decisions:
1. "Database" is the canonical term (not "Collection")
2. Current Space is bound at client init (no runtime switching)
3. Server-side Markdown export via `getBlockExport`
4. Single-user auth, no browser capture
5. Read+Write scope gated by `NOTION_ALLOW_WRITE=1`

## License

MIT