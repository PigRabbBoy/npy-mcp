# npy-mcp — Notion MCP Server + CLI

Unofficial Python 3.12+ client for Notion's internal API (v3). Three packages
in one repo:

- **npy-mcp** — MCP server (25 tools) for Claude Desktop, Cursor, VS Code, Codex, Claude Code
- **npy-cli** — command-line tool (25 commands, same capabilities)
- **npy-core** — Python library you can build on directly

Everything is powered by the `token_v2` cookie from your logged-in Notion
browser session — so it **works for Guest users**, which the official API
doesn't.

> ⚠️ **Heads-up**: this uses Notion's undocumented internal API, not the
> official one. That means it can break when Notion changes, and it's on you
> to stay within Notion's ToS. See [docs/adr/](docs/adr/) for design decisions.

---

## Table of contents

1. [Quick start](#quick-start)
2. [What your AI can do](#what-your-ai-can-do)
3. [CLI](#cli)
4. [Getting your token_v2](#getting-your-token_v2)
5. [Setting your space ID](#setting-your-space-id)
6. [Remote (HTTP) — shared/team access](#remote-http--sharedteam-access)
7. [Python library](#python-library)
8. [AI skills for agents](#ai-skills)
9. [Development](#development)

---

## Quick start

**1. Get your token** (2 min): open [app.notion.com](https://app.notion.com) →
F12 → **Application** → **Cookies** → copy the `token_v2` value (starts with
`v03%3A...`). [Details](#getting-your-token_v2)

**2. Pick an install option and paste the config:**

<details open>
<summary><b>Option 1 — uvx (recommended, no install)</b></summary>

Install [uv](https://docs.astral.sh/uv/) once: `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows) / **Cursor** (`.cursor/mcp.json`) / **Claude Code** (`.mcp.json`):
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

**VS Code** (`.vscode/mcp.json`) — same but with `"type": "stdio"` and under `"servers"`:
```json
{
  "servers": {
    "notion-py": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp", "notion-mcp"],
      "env": { "NOTION_TOKEN_V2": "v03%3AeyJ..." }
    }
  }
}
```

**Codex** (`~/.codex/config.toml`):
```toml
[mcp_servers.notion-py]
command = "uvx"
args = ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp", "notion-mcp"]
env = { NOTION_TOKEN_V2 = "v03%3AeyJ..." }
```
</details>

<details>
<summary><b>Option 2 — Docker (no Python/uv needed)</b></summary>

Same configs as above, but with docker as the command:

```json
{
  "mcpServers": {
    "notion-py": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"],
      "env": { "NOTION_TOKEN_V2": "v03%3AeyJ..." }
    }
  }
}
```

Codex: `command = "docker"`, `args = ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"]`
</details>

<details>
<summary><b>Option 3 — pip install (Python developers)</b></summary>

```bash
pip install "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/npy-mcp"
```

```json
{
  "mcpServers": {
    "notion-py": {
      "command": "python",
      "args": ["-m", "notion_mcp"],
      "env": { "NOTION_TOKEN_V2": "v03%3AeyJ..." }
    }
  }
}
```
</details>

**3. Restart your AI client and ask it something:**
> "Find pages about project status in Notion" — that's it.

<details>
<summary>💡 Want write access too (create/update/delete)?</summary>

The server starts in **read-only** mode (8 read tools). To unlock the 17 write
tools, add one line to the `env` block:

```json
"env": {
  "NOTION_TOKEN_V2": "v03%3AeyJ...",
  "NOTION_ALLOW_WRITE": "1"
}
```

This is deliberate: it stops an AI from editing your workspace unless you
explicitly opt in. See [ADR-0005](docs/adr/0005-read-write-scope-gated.md).
</details>

---

## What your AI can do

All **25 tools** (8 read + 17 write):

| Read — always available | |
|---|---|
| `search` | Search pages/blocks across the workspace |
| `get_page` | Page content as Markdown or JSON (depth control) |
| `get_block` | Single block by URL/ID |
| `get_image` | Download an image/file block and return it inline |
| `list_pages` | Recent pages (workspace or under a parent) |
| `get_database` | Schema + sample rows (`full_schema` dumps everything, for provisioning) |
| `query_database` | Filter/sort rows — formulas and rollups fully evaluated |
| `get_comments` | Read comment threads on a page/block |

| Write — needs `NOTION_ALLOW_WRITE=1` | |
|---|---|
| `create_page` | New page under a parent |
| `append_blocks` | Add blocks (13 types) to a page |
| `update_block` | Edit text / toggle checkbox |
| `delete_block` | Trash or permanently remove |
| `move_block` | Reparent a block |
| `add_alias` | Alias a page into another parent |
| `add_database_row` / `update_database_row` / `delete_database_row` | Manage rows |
| `create_database` / `add_column` | Provision databases with **relation / formula / rollup** columns |
| `create_media` | Attach image/file via URL or local upload |
| `create_embed` | Embed 20 providers (YouTube, Figma, Maps…) |
| `create_table` / `create_columns` | Table blocks / column layouts |
| `import_csv` | CSV → inline database |
| `add_comment` | Comment on a page (new thread or reply) |

Full reference: [`TOOLS.md`](packages/npy-mcp/skills/notion-mcp/TOOLS.md)

<details>
<summary><b>Schema provisioning example</b> — relations, formulas, rollups</summary>

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

- **`reverse_name`** creates a genuine **two-way synced relation** — a mirrored
  property appears on the target database (written in one transaction, exactly
  like Notion's own client), and row-level links propagate to both sides.
- Dates accept ISO strings (`"2026-01-31"`, `"2026-01-31T14:30"`).
- `files` properties accept local paths (uploaded to Notion automatically).
</details>

---

## CLI

Prefer the terminal? Same capabilities, 25 commands:

```bash
# install from source (provides the `notion` command)
git clone https://github.com/PigRabbBoy/npy-mcp.git && cd notion-py
uv sync
export NOTION_TOKEN_V2="v03%3AeyJ..."
uv run notion --help
```

```bash
# Read
uv run notion search "project"                    # search pages/blocks
uv run notion get-page <PAGE_ID> --depth 2        # page tree as markdown
uv run notion list-pages                          # recent top-level pages
uv run notion get-database <DB_ID> --sample 5     # schema + sample rows
uv run notion query-database <DB_ID> --limit 20   # query rows
uv run notion get-image <BLOCK_ID>                # download an image
uv run notion get-comments <PAGE_ID>              # read comments

# Write (requires NOTION_ALLOW_WRITE=1)
uv run notion create-page <PARENT_ID> --title "New Page"
uv run notion append-blocks <PAGE_ID> --blocks '[{"type":"todo","text":"Ship it"}]'
uv run notion add-database-row <DB_ID> --properties '{"Name":"New row","Status":"Todo"}'
uv run notion create-database <PARENT_ID> --title "Tasks" \
  --columns '[{"name":"Name","type":"title"},{"name":"Done","type":"checkbox"}]'
uv run notion add-comment <PAGE_ID> --text "Look at this"

# Auth
uv run notion auth whoami && uv run notion auth spaces
```

> Tip: `source .venv/bin/activate` once and you can drop the `uv run` prefix.

Run `notion <command> --help` for every option. Write commands refuse to run
without `NOTION_ALLOW_WRITE=1`.

---

## Getting your token_v2

1. Open [app.notion.com](https://app.notion.com) in Chrome (logged in)
2. **F12** → **Application** tab → **Cookies** → `https://app.notion.com`
3. Copy the **Value** of `token_v2` — a long string starting with `v03%3A...`

> 🔐 **Security**: `token_v2` = full access to your Notion account. Never
> commit or share it. To invalidate, Notion → Settings → Log out of all
> sessions. Tokens expire periodically — if you get `401 Unauthorized`,
> grab a fresh one the same way.

---

## Setting your space ID

Only needed if your token sees **multiple workspaces**. Otherwise skip — the
first space found is used.

```bash
# List your spaces (the * marks the current one)
uv run notion auth spaces

# Set default (persisted to ~/.config/notion-py/config.toml)
uv run notion auth use-space <SPACE_ID>
```

Or via env var / MCP config: `"NOTION_SPACE_ID": "<space-id>"`

Resolution order: `NOTION_SPACE_ID` env → `~/.config/notion-py/config.toml` → first space in token data.

<details>
<summary>Other ways to find your space ID</summary>

**Browser DevTools:** F12 → Network → click any Notion page → find
`api/v3/loadUserContent` → in the response, the key under `"space": {...}` is
your space ID.

Space IDs look like UUIDs: `1b6d9f59-d372-43b7-8cfc-332e473b1f2c`
</details>

---

## Remote (HTTP) — shared/team access

Run one shared server over HTTP with Bearer auth:

```bash
NOTION_TOKEN_V2="your-token" \
NOTION_MCP_AUTH_TOKEN="shared-secret" \
python -m notion_mcp --transport http --host 0.0.0.0 --port 8000
```

Point your AI client at it:

```json
{
  "mcpServers": {
    "notion-py": {
      "url": "http://your-server:8000/mcp",
      "headers": { "Authorization": "Bearer shared-secret" }
    }
  }
}
```

<details>
<summary>Multi-client: one server, per-user Notion tokens</summary>

Each client can send its own Notion token via the `X-Notion-Token` header —
the server builds a separate (cached) `NotionClient` per token:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer shared-secret" \
  -H "X-Notion-Token: v03%3AeyJ..." \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

No header → falls back to the server's `NOTION_TOKEN_V2`.
</details>

<details>
<summary><b>Docker deployment</b></summary>

```bash
# Pull prebuilt (recommended)
docker pull pigrabbboy/npy-mcp:latest

# Build yourself (from repo root)
docker build -t notion-mcp -f packages/npy-mcp/Dockerfile .

# Run as HTTP server
docker run -d -p 8000:8000 \
  -e NOTION_TOKEN_V2="your-token_v2" \
  -e NOTION_MCP_AUTH_TOKEN="shared-secret" \
  -e NOTION_ALLOW_WRITE=0 \
  pigrabbboy/npy-mcp:latest

# Or docker compose
cd packages/npy-mcp && cp .env.example .env && docker compose up -d
```
</details>

---

## Python library

Use `npy-core` directly in your own code:

```python
from notion.client import NotionClient

client = NotionClient(token_v2="v03%3AeyJ...")

# read
page = client.get_block("<PAGE_URL_OR_ID>")
print(page.title_plaintext)

# query a database with formulas/rollups evaluated
from notion.collection import CollectionQuery
cv = client.get_collection_view("<DB_URL>")
for row in cv.build_query().execute():
    print(row.title, row.get_property("Budget Rollup"))

# write (properties by slug name; two-way relations stay in sync)
row = cv.collection.add_row(Name="My row", Status="Todo")
row.Done = True
```

---

## AI skills for agents

Ship-ready skills so your agent knows which tool to use when:

```bash
# notion-mcp skill: tool selection, workflows, write safety
cp -r packages/npy-mcp/skills/notion-mcp ~/.claude/skills/notion-mcp   # Claude Code
cp -r packages/npy-mcp/skills/notion-mcp ~/.config/opencode/skills/    # opencode
# (same pattern for ~/.agents/skills/)

# release skill: versioning, changelog, tagging
cp -r packages/npy-mcp/skills/release ~/.claude/skills/release
```

- `SKILL.md` — when to use which tool, common workflows, write safety rules
- `TOOLS.md` — full 25-tool reference (args, types, examples, error messages)

---

## Development

```bash
uv sync --extra dev                       # install with dev deps
python -m pytest tests/ -v                # 126 tests, no live Notion calls
python run_smoke_test.py --page <URL> --token <TOKEN_V2>   # live integration test
```

```
notion-py/
├── packages/
│   ├── npy-core/src/notion/       ← Core library
│   │   ├── client.py              ← NotionClient (HTTP, auth, transactions)
│   │   ├── block.py               ← Block + 38 subclasses
│   │   ├── collection.py          ← Databases, rows, query builder
│   │   ├── store.py               ← RecordStore (thread-safe cache)
│   │   ├── markdown.py            ← rich-text ↔ CommonMark
│   │   ├── auth.py                ← token + space resolution
│   │   └── operations.py          ← transaction op builder
│   ├── npy-cli/src/notion_cli/    ← CLI (Typer, 25 commands)
│   └── npy-mcp/src/notion_mcp/    ← MCP server (25 tools, stdio + HTTP)
├── tests/                         ← 126 tests (pytest + vcr.py)
├── docs/adr/                      ← 8 Architecture Decision Records
├── CONTEXT.md                     ← Domain glossary
└── run_smoke_test.py              ← live integration test
```

## Design decisions

See [docs/adr/](docs/adr/) for the key decisions:
1. "Database" is the canonical term (not "Collection")
2. Current Space is bound at client init (no runtime switching)
3. Server-side Markdown export via `getBlockExport`
4. Single-user auth, no browser capture
5. Read+Write scope gated by `NOTION_ALLOW_WRITE=1`

## License

MIT