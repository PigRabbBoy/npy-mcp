# Single-user auth, env/config only, no browser capture

The Token is read from `NOTION_TOKEN_V2` env var, then
`~/.config/unpy-mcp/token` config file. No browser automation to capture
cookies. Rejected alternative: launching Playwright to log the user in and
extract `token_v2` automatically. Browser capture is convenient on a local
dev machine but useless for remote MCP HTTP deployment, adds a ~400MB
dependency, and silently handles a credential that equals full account
access. Users extract the cookie manually from DevTools once; this is
documented in the README. Multi-user auth (token store, OAuth) is
explicitly out of scope for v2.