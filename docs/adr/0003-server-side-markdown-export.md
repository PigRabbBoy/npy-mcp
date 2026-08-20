# Server-side Markdown export, not client-side tree-walking

Read tools return Markdown by default, produced by Notion's
`getBlockExport` endpoint (the same one the UI's "Export to Markdown"
uses). Rejected alternative: walking the block tree in Python and calling
`notion_to_markdown` per block. The server-side path costs one extra API
call per read but produces output that matches the UI exactly, including
nested blocks and complex annotations. For blocks that cannot be
server-exported (non-page blocks without an export endpoint), we fall back
to the client-side `notion_to_markdown()` converter. The latency is
acceptable for the interactive CLI and MCP use case; the alternative would
diverge from what users see in Notion and require us to track Notion's
markdown dialect.