# Read+Write scope with explicit write gate and fixed tool list

We expose both read and write tools. Write tools are gated by an
`NOTION_ALLOW_WRITE=1` env var — without it, the MCP server advertises
only read tools and the CLI refuses write commands. This satisfies the
"use AI as a reader by default" safety posture without losing the write
capability. The full write tool list is fixed: `create_page`,
`append_blocks`, `update_block`, `delete_block`, `move_block`,
`add_alias`, `add_database_row`, `update_database_row`,
`delete_database_row`. Schema mutations (add/remove columns) are out of
scope for v2 — too easy to corrupt a Database.