# ADR-0009: Shell installers with Merge Write, not a package-based installer

Date: 2026-09-02
Status: Accepted

## Context

Users install npy-mcp into AI clients (Claude Desktop, Cursor, VS Code,
Codex, opencode, Windsurf) by hand-editing 7 different config formats —
JSON with `mcpServers`, JSON with `servers`, TOML with `mcp_servers`,
JSON with `mcp` + array-shaped `command`. The manual flow is the largest
friction point in adoption, and each format has per-OS path differences.

We need a single-command install (`curl | bash` / `irm | iex`) that:
collects a Notion token, optional space, and write preference; picks
target clients via multiselect; checks for `uvx` and installs it if
missing; and writes correct configs everywhere.

## Decision

- Two scripts, not three: `scripts/install.sh` covers macOS **and** Linux
  (they share bash and differ only in the Claude Desktop path);
  `scripts/install.ps1` covers Windows. A third dispatch script would
  only add a hop.
- The installer **merges** into existing config files: it loads the file,
  adds or updates only the `notion-py` entry, and writes back — never
  dropping other servers. Before every write it copies the original to a
  timestamped `<file>.bak-<timestamp>`.
- `uvx` is resolved to an **absolute path** at install time, because GUI
  apps on macOS do not inherit the shell PATH and `command: "uvx"` fails
  in Claude Desktop when uv was installed via the astral installer
  (`~/.local/bin`). `uvx` manages its own Python, so Python is not
  checked or installed separately.
- Both interactive and flag modes are supported (`--client`, `--token`,
  `--space`, `--allow-write`, `--scope`); flags switch the script into
  non-interactive mode for scripting/CI.
- Scope question (global vs project config) is asked only for clients
  that have both (Claude Code, Cursor). Default is global: project
  configs like `.mcp.json` are typically committed to git, which risks
  leaking the Notion token.
- `NOTION_ALLOW_WRITE` defaults to **off** with an explicit y/N prompt,
  consistent with [ADR-0005](0005-read-write-scope-gated.md).
- `NOTION_SPACE_ID` is optional; empty means "first space found", which
  matches the library's own resolution order.
- Paired uninstallers remove only the `notion-py` entry, same
  merge-with-backup discipline.

## Consequences

- Config edits are safe to re-run: same command updates values in place.
- If a user moves or upgrades uv to a different path, configs written with
  the old absolute path must be re-run through the installer.
- The client catalog (7 clients) is a hardcoded table in each script;
  adding a client means editing both scripts. Acceptable at this scale;
  a shared manifest would be over-engineering.
- Windows editing of `config.toml` is line-based (strip-and-append of the
  `[mcp_servers.notion-py]` block) because PowerShell has no built-in
  TOML parser; acceptable because we only ever manage our own block.