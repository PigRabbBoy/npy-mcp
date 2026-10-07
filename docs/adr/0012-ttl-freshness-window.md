# ADR 0012: TTL freshness window on forced reads

**Status**: Accepted (v2.0.0), amended (v2.2.4 — forced reads bypass the window)

## Context

Two facts from the v1.3.2 survey pulled in opposite directions:

1. v1 `RecordStore.get()` on a cached record WITHOUT `force_refresh` never
   re-fetched (plain reads were already "cache forever").
2. The MCP read tools all default `force_refresh=True`, so every AI-driven
   read re-fetched the record over the network even a second after the
   previous fetch. Under agent workloads (search → get_page → get_database
   chains) most fetches were redundant seconds-scale refreshes.

Simply turning `force_refresh` off by default would change data freshness
semantics that AI clients rely on (issue #22 — edits made outside the
session must be visible).

## Decision

A freshness window (`Freshness Window`, default 15 seconds, `UNPY_CACHE_TTL`)
gated on record fetch timestamps in the RecordStore:

- A record fetched (from network or local replay) inside the window is
  served from cache for UNFORCED reads.
- **Amendment (v2.2.4, issue #43):** a FORCED read (`force_refresh=True`)
  always bypasses the window. The original "even forced reads serve the
  cached copy inside the window" rule made long-lived MCP clients read
  stale snapshots — get_page → update_block/delete_block acted on data the
  user had already changed in the Notion UI ("the edit seems to not
  stick"), so the freshness tradeoff collided with correctness. Plain
  (unforced) reads keep the window; `get_page(refresh=True)` additionally
  force-refreshes the page's direct children (one batched
  `refresh_blocks` call).
- `UNPY_CACHE_TTL=0` or `UNPY_LEGACY=1` restores the always-refresh
  behavior in full.
- Unforced reads keep exact v1 semantics (never re-fetch cached records).
- Every Write Operation stamps freshness (write-through invalidation), so
  locally-mirrored changes are never shadowed by the window.

The alternative — per-tool TTL knobs or a cross-request cache in the MCP
layer — was rejected: the RecordStore is shared territory for CLI, MCP and
library users, and one knob (`UNPY_CACHE_TTL`) covers all layers without
per-tool drift.

## Consequences

- Repeat UNFORCED reads inside 15s cost zero round trips.
- FORCED reads always reflect the server's current state (may pay one
  round trip) — correctness over latency for edit-driving reads.
- External edits are now visible to any `refresh=true` read immediately;
  only unforced reads keep the (documented) staleness tradeoff.
- Timestamp bookkeeping is a monotonic-clock dict write per record update:
  negligible CPU; the dict shares the store's existing lock regime.