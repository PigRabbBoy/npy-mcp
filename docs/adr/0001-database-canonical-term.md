# Database is the canonical term, not Collection

The legacy codebase uses `Collection` everywhere (class names, attribute
names, file names). Users, the Notion UI, and our CLI/MCP tool names use
"Database". We adopt "Database" as the canonical term in all user-facing
surfaces (tool names, CLI commands, docs, error messages) and keep
`Collection` only as an internal code identifier for backward compatibility
with the existing class hierarchy. CLI command is `get-database`, not
`get-collection`. MCP tool is `get_database`. Renaming the underlying
`Collection` Python class is out of scope — too invasive for too little gain.