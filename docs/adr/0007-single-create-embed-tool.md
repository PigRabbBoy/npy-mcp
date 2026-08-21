# All embed types go through one create_embed tool

Notion has 20+ embed block types (tweet, figma, gist, miro, etc.), each with
a corresponding block class. We decided on a single `create_embed(type, url)`
tool where `type` maps to the block class, rather than 20 separate tools.
The API shape is identical for all embeds — only the `_type` string differs.
This keeps the tool surface small and extensible (adding a new embed type
is one dict entry, not a new tool). The alternative was separate tools per
category (social, design, code), but that adds complexity without value.