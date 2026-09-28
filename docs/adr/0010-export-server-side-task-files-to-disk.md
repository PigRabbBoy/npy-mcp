# Export = server-side partitionedExportBlock task, files to disk

Date: 2026-09-28

## Context

Users want to take Page/Database content out of Notion as real files
(PDF, HTML, Markdown & CSV) — the same thing the UI's Export dialog
does. Notion's server runs this as an async task
(`enqueueTask` → `partitionedExportBlock` → poll `getTasks` → signed zip
URL), not a synchronous endpoint. We already had a dead
`Block.extract_markdown()` from the archived upstream that used the
legacy `exportBlock` event name and returned a single string.

## Decision

- One capability, named **Export**, exposed as MCP tool `export` and CLI
  `unpy export <id>` — the id may be a Page or a Database.
- All three formats from day one (`pdf` | `html` | `markdown`).
- Delivery is always **files under an output directory** (MCP default:
  `NOTION_MCP_FILE_ROOT`; CLI default: cwd). The zip is unpacked
  automatically; a single-file zip (markdown non-recursive) also returns
  the text inline for direct consumption.
- All dialog options exposed: recursive (include subpages),
  `database_views` (current/all), `page_content`
  (everything/no_files), `create_folders` (off →
  `flattenExportFiletree`), `pdf_format`, `export_comments`,
  `timezone` (default local).
- The call blocks until the task finishes (default timeout 120s,
  adjustable). No status tool.
- Not gated by `NOTION_ALLOW_WRITE` — it mutates no Notion state; local
  file writes are confined by `NOTION_MCP_FILE_ROOT`.
- The request uses the current UI event name `partitionedExportBlock`
  with `preferredViewMap: {}` (verified accepted live).

## Consequences

- Export is slow by nature (seconds to a minute); tools document this.
- `collectionViewExportType` accepts `currentView` and `all`; the value
  `allViews` hangs the server task forever (live-verified) — a trap the
  tests pin down.
- The dead `extract_markdown` (legacy event name, hardcoded options,
  `www.notion.so` host) is removed and replaced by `unpy.export`.
- ADR-0003's "read tools default to server-side markdown" never matched
  the shipped code; that ADR is revised and the concept split is:
  **Page Read** (client-side, interactive) vs **Export** (server-side
  task → files).