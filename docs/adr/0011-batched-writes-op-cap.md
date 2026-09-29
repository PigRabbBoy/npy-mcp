# ADR 0011: Batched transactions with a hard op cap

**Status**: Accepted (v2.0.0)

## Context

Profiling (`scripts/bench.py`) showed the dominant cost of bulk write tools
(`append_blocks`, `create_page`, `import_csv`, `create_columns`) was not
CPU but HTTP round trips: v1 issued one `saveTransactionsFanout` request
per block/row (~2 ops each). A 10,000-row CSV import cost ~10,000+ HTTP
requests. The client already supported buffering operations inside an
`as_atomic_transaction()` context, so the mechanism existed — it was just
never applied to multi-block write paths.

## Decision

All multi-block write paths buffer their operations and flush through a
single capped batching layer:

1. `submit_transaction` enforces a hard cap (`UNPY_BATCH_MAX_OPS`, default
   100) on the FINAL (post-`update_last_edited`-expansion) operation list —
   oversized buffers are split into multiple requests transparently.
2. The write tools wrap their whole spec loop in one
   `batched_transaction()` context; nested transaction contexts join the
   outer one (unchanged v1 nesting rule).
3. The unit of failure is the chunk. When a chunk is rejected, the flush
   stops, remaining specs are reported as failures, and earlier chunks stay
   committed — the caller can retry the remainder (issue #19 semantics).
4. `UNPY_LEGACY=1` restores one transaction per block.

We deliberately did NOT adopt asyncio/httpx for this. The client's public
API is synchronous and rewrite cost is high; batching alone eliminates most
round trips with a fraction of the risk (per the grilling decision Q3).

## Consequences

- N-block writes cost ceil(N/cap) requests instead of N.
- Failure semantics change: a failure inside a chunk can void the whole
  chunk (buffered ops are not resumable mid-chunk), so partial-success
  reporting backs up to the last committed chunk boundary.
- Large single requests are bounded — Notion throttles huge transactions.
- Breaking change (error surfaces and request patterns differ) → major
  release; `UNPY_LEGACY=1` is the escape hatch.