# npy-mcp — Notion MCP Server + CLI

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
git clone https://github.com/PigRabbBoy/npy-mcp.git
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
| `npy-cli` | CLI tool with 23 commands (full MCP parity) | `uv add npy-cli` |
| `npy-mcp` | MCP server (stdio + HTTP) with 27 tools | `uv add npy-mcp` |

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

### Local (stdio)

Three ways to run the MCP server locally over stdio. Pick one based on your setup.

#### Option 1: `uvx` (recommended — no install needed)

Install [uv](https://docs.astral.sh/uv/) once:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp", "notion-mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Cursor** (`.cursor/mcp.json` in project root):
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp", "notion-mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**VS Code** (`.vscode/mcp.json` in project root):
```json
{
  "servers": {
    "notion-py": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp", "notion-mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Claude Code** (`.mcp.json` in project root, or `~/.claude.json` for global):
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp", "notion-mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Codex** (`~/.codex/config.toml` or `.codex/config.toml` in project root):
```toml
[mcp_servers.notion-py]
command = "uvx"
args = ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp", "notion-mcp"]
env = { NOTION_TOKEN_V2 = "v03%3AeyJ..." }
```

#### Option 2: Docker (no Python needed)

Pull the image and run via stdio. No Python or uv installation required.

**Claude Desktop:**
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**VS Code** (`.vscode/mcp.json`):
```json
{
  "servers": {
    "notion-py": {
      "type": "stdio",
      "command": "docker",
      "args": ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Claude Code** (`.mcp.json` or `~/.claude.json`):
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Codex** (`~/.codex/config.toml` or `.codex/config.toml`):
```toml
[mcp_servers.notion-py]
command = "docker"
args = ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"]
env = { NOTION_TOKEN_V2 = "v03%3AeyJ..." }
```

#### Option 3: pip install (for developers with Python)

```bash
pip install "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp"
```

**Claude Desktop:**
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "python",
      "args": ["-m", "notion_mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "python",
      "args": ["-m", "notion_mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**VS Code** (`.vscode/mcp.json`):
```json
{
  "servers": {
    "notion-py": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "notion_mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Claude Code** (`.mcp.json` or `~/.claude.json`):
```json
{
  "mcpServers": {
    "notion-py": {
      "command": "python",
      "args": ["-m", "notion_mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**Codex** (`~/.codex/config.toml` or `.codex/config.toml`):
```toml
[mcp_servers.notion-py]
command = "python"
args = ["-m", "notion_mcp"]
env = { NOTION_TOKEN_V2 = "v03%3AeyJ..." }
```

#### Enabling write tools (stdio)

Add `"NOTION_ALLOW_WRITE": "1"` to the `env` block in any of the configs above to unlock 18 write tools (create, update, delete, move, etc.). Without it, only 9 read tools are available.

#### All 27 tools

| Tool | What it does |
|---|---|
| **Read (9)** | |
| `search` | Search pages/blocks across the workspace |
| `get_page` | Page content as Markdown or JSON (depth control) |
| `get_block` | Single block by URL/ID |
| `get_image` | Download an image block/file and return it inline |
| `list_pages` | Recent pages (workspace or under a parent) |
| `get_database` | Database schema + sample rows (`full_schema` dumps relation/rollup/formula definitions for provisioning) |
| `query_database` | Filter/sort rows (full formula evaluation; `fetch_all` for every row) |
| `get_comments` | Read comment threads on a page/block (author, text, timestamps) |
| `add_comment` | Comment on a page — new thread or reply |
| **Write (18)** — requires `NOTION_ALLOW_WRITE=1` | |
| `create_page` | New page under a parent, with icon |
| `append_blocks` | Add blocks (13 types) to a page |
| `update_block` | Edit text / toggle checked |
| `delete_block` | Trash or permanently remove |
| `move_block` | Reparent a block |
| `add_alias` | Alias a page into another parent |
| `add_database_row` | Insert a row (props by name) |
| `update_database_row` | Edit row properties |
| `delete_database_row` | Remove a row |
| `create_database` | Inline or full-page database with schema — incl. **relation** (target db, single mode, reverse name), **formula** (`{"Prop Name"}` refs), **rollup** (by property name, optional aggregation) |
| `add_column` | Add a property column (all types — same relation/formula/rollup specs) |
| `create_media` | Attach image/file via URL or upload |
| `create_embed` | Embed (20 providers) |
| `create_table` | Simple table block |
| `create_columns` | Column layout with N children |
| `import_csv` | CSV → inline database |

Full args/types/examples: [`TOOLS.md`](packages/npy-mcp/skills/notion-mcp/TOOLS.md).

#### Schema provisioning example

Relation, formula, and rollup columns are fully supported (verified rendering
in the Notion web UI):

```json
[
  {"name": "Task", "type": "title"},
  {"name": "Project", "type": "relation",
   "target_database_id": "<db url or id>",
   "limit": 1, "reverse_name": "Tasks"},
  {"name": "Done", "type": "checkbox"},
  {"name": "Status", "type": "formula",
   "expression": "if({\"Done\"}, \"✅ done\", \"⬜ open\")"},
  {"name": "Budget Rollup", "type": "rollup",
   "relation_property": "Project", "target_property": "Budget",
   "aggregation": "sum"}
]
```

Date properties also accept ISO strings (`"2026-01-31"`,
`"2026-01-31T14:30"`), and `files` properties accept local paths (uploaded
automatically).

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

By default, the MCP server exposes only **9 read tools**. Set
`NOTION_ALLOW_WRITE=1` to unlock the **18 write tools** — see the
["All 27 tools"](#all-27-tools) table above for the full list (search,
get_page, get_block, get_image, list_pages, get_database, query_database —
plus create/update/delete/move, database provisioning with
relation/formula/rollup columns, media/embed/table/columns, CSV import).

## AI Skills

Two AI skills are included to help AI agents (Claude Desktop, Claude Code, Codex, Cursor, VS Code, opencode) use
the MCP tools and manage releases.

### Notion MCP skill

Tells the agent which tool to use for each task, common workflows, and write safety rules.

```bash
# For opencode / Claude Desktop / Claude Code / Codex / Cursor / VS Code
cp -r packages/npy-mcp/skills/notion-mcp ~/.config/opencode/skills/notion-mcp
cp -r packages/npy-mcp/skills/notion-mcp ~/.claude/skills/notion-mcp
cp -r packages/npy-mcp/skills/notion-mcp ~/.agents/skills/notion-mcp
```

Contains:
- `SKILL.md` — trigger description, tool selection guide, common workflows, write safety
- `TOOLS.md` — full reference for all 27 tools (args, types, examples, error messages)

### Release skill

Automates version bump, changelog update, git tag, and GitHub Release creation.

```bash
# For opencode / Claude Desktop / Claude Code / Codex / Cursor / VS Code
cp -r packages/npy-mcp/skills/release ~/.config/opencode/skills/release
cp -r packages/npy-mcp/skills/release ~/.claude/skills/release
cp -r packages/npy-mcp/skills/release ~/.agents/skills/release
```

Contains:
- `SKILL.md` — pre-release checklist, 7-step release workflow, confirmation gates
- `REFERENCE.md` — version rules, changelog format, gh/docker commands, rollback procedures

## Getting your token_v2

1. Open https://app.notion.com in Chrome (logged in)
2. F12 → **Application** tab → **Cookies** → `https://app.notion.com`
3. Find `token_v2` → copy the **Value** (a long string starting with `v03%3A...`)

⚠️ **Security**: `token_v2` = full session access. Anyone with this token can
read/write everything you can. Don't commit it to git, don't share it, and
invalidate it (Notion Settings → Log out of all sessions) when done.

## Setting your space ID

If your token has access to multiple Notion workspaces (spaces), you need to
specify which space to use. Without it, the client picks the first space it
finds — which may not be the one you want.

### Option 1: Environment variable

```bash
export NOTION_SPACE_ID="1b6d9f59-d372-43b7-8cfc-332e473b1f2c"
```

Or add it to the MCP server config:

```json
"env": {
  "NOTION_TOKEN_V2": "v03%3AeyJ...",
  "NOTION_SPACE_ID": "1b6d9f59-d372-43b7-8cfc-332e473b1f2c"
}
```

### Option 2: CLI (persisted to config file)

```bash
# List all spaces your token can access
python -m notion_cli auth spaces

# Set one as the default (saved to ~/.config/notion-py/config.toml)
python -m notion_cli auth use-space 1b6d9f59-d372-43b7-8cfc-332e473b1f2c

# Check current auth state
python -m notion_cli auth whoami
```

### Option 3: Config file

Write `~/.config/notion-py/config.toml`:

```toml
space_id = "1b6d9f59-d372-43b7-8cfc-332e473b1f2c"
```

### Resolution order

1. `NOTION_SPACE_ID` env var
2. `~/.config/notion-py/config.toml` (written by `notion auth use-space`)
3. First space found in token data (default fallback)

### How to find your space ID

**Method 1 — CLI (easiest):**
```bash
python -m notion_cli auth spaces
```
Lists every space your token can access, with ID + name. The `*` marks the current one.

**Method 2 — Browser DevTools:**
1. Open https://app.notion.com in Chrome (logged in)
2. F12 → **Network** tab
3. Click any page in Notion
4. Look for a request to `api/v3/loadUserContent` or `getPublicSpaceData`
5. In the response, find `"space": {"<space-id>": {...}}` — the key is your space ID

**Method 3 — Notion URL (indirect):**
The page URL contains the **page ID**, not the space ID. But the first page you see after login belongs to your default space. Use Method 1 to get the actual space ID.

> Space IDs look like UUIDs: `1b6d9f59-d372-43b7-8cfc-332e473b1f2c`

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
│   │   ├── cli.py                ← 23 commands
│   │   ├── render.py             ← Markdown/JSON formatters
│   │   └── client_factory.py     ← Client builder from auth config
│   └── npy-mcp/src/notion_mcp/   ← MCP server
│       ├── server.py             ← MCPServer + 27 tools
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