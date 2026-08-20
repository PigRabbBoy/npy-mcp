# Changelog

All notable changes to npy-mcp are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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