# Server-side Markdown export, not client-side tree-walking

**Status:** Superseded in part by ADR-0010 (2026-09-28). The original
decision described below was never actually wired into the read tools —
the MCP/CLI `get_page`/`get_block` render **client-side** from the
RecordStore, and that is what shipped and works well today.

Original decision: read tools return Markdown produced by Notion's
`getBlockExport` endpoint (the same one the UI's "Export to Markdown"
uses), falling back to client-side `notion_to_markdown()` only for
blocks that cannot be server-exported. Rejected alternative: walking the
block tree in Python and calling `notion_to_markdown` per block.

What actually happened: the server-side export path is an async task
(enqueue → poll → download zip), costing seconds per read — unusable for
interactive get tools, and the client-side renderer proved good enough
that the fallback became the implementation. Rather than resurrect the
original plan, ADR-0010 separates the two concepts: interactive **Page
Read** stays client-side; **Export** (the user-asked-for file export —
PDF/HTML/Markdown & CSV) uses the server-side task system.