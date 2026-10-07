"""Batch database-row operations shared by unpy-mcp and unpy-cli (issue #43).

add_rows creates N rows inside ONE batched transaction — the row records,
their property writes, per-view page_sort insertions, select-option schema
ops and two-way relation mirrors all buffer into the enclosing batched
transaction and flush in chunks of batch_max_ops (~1 HTTP call per chunk
instead of 2+ per row). update_rows applies property maps to many existing
rows the same way.

Both reuse the same setters (setattr on CollectionRowBlock) as the
single-row tools, so every edge case (schema auto-add for new select
options, relation mirroring) behaves identically — only the transport is
batched.
"""

from __future__ import annotations

from unpy.utils import extract_id


def _debug_or_str(exc) -> str:
    detail = str(exc)
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            detail = resp.json().get("debugMessage") or detail
        except Exception:
            pass
    return detail


def add_rows(client, collection, rows: list):
    """Create many rows in a database in ONE batched transaction.

    rows: list of property dicts ({"Name": "...", "Status": "Todo"}); an
    empty object creates an empty row. Values use the same columns-by-name
    conversion as add_database_row.

    Returns (row_ids, failures): row_ids in input order (only rows whose
    whole buffered tx committed), failures with 1-based row numbers.
    """
    from unpy.collection import CollectionRowBlock

    failures: list[str] = []
    if not isinstance(rows, list):
        return [], ["rows must be a JSON array of property objects"]
    if not rows:
        return [], failures

    # resolve column names ONCE up front — bad names fail before any write
    schemas = collection.get_schema_properties()
    known_slugs = {p["slug"] for p in schemas} | {p["id"] for p in schemas}
    known_slugs.add("title")
    bad_rows: set[int] = set()
    for i, props in enumerate(rows):
        if not isinstance(props, dict):
            failures.append(f"row {i + 1}: expected an object, got {type(props).__name__}")
            bad_rows.add(i)
            continue
        for name in props:
            from unpy.utils import slugify

            if name not in known_slugs and slugify(name) not in known_slugs:
                failures.append(f"row {i + 1}: no column named '{name}'")
                bad_rows.add(i)

    row_ids: list[str] = []
    with client.batched_transaction():
        for i, props in enumerate(rows):
            if i in bad_rows or not isinstance(props, dict):
                continue  # unknown column — fail that row before any write
            try:
                row_id = client.create_record("block", collection, type="page")
                row = CollectionRowBlock(client, row_id)
                for key, val in props.items():
                    if hasattr(row, key):
                        setattr(row, key, val)
                    else:
                        row.set_property(key, val)
                row_ids.append(row_id)
            except Exception as exc:
                failures.append(f"row {i + 1} failed: {_debug_or_str(exc)}")

    return row_ids, failures


def update_rows(client, updates: list):
    """Update property maps on many rows in ONE batched transaction.

    updates: [{"row_id": …, "properties": {column_name: value}, …}] — the
    same per-row setattr semantics as update_database_row, batched.

    Returns (count_updated, failures); unknown row ids are reported before
    any write.
    """
    failures: list[str] = []
    if not isinstance(updates, list):
        return 0, ["updates must be a JSON array of {row_id, properties} objects"]
    if not updates:
        return 0, failures

    found: list[tuple[str, dict]] = []
    for i, upd in enumerate(updates):
        row_id = upd.get("row_id") if isinstance(upd, dict) else None
        props = upd.get("properties") if isinstance(upd, dict) else None
        if not isinstance(row_id, str) or not row_id.strip():
            failures.append(f"update {i + 1}: 'row_id' must be a non-empty string")
            continue
        if not isinstance(props, dict):
            failures.append(f"update {i + 1}: 'properties' must be an object")
            continue
        found.append((row_id, props))

    ids: list[str] = []
    for rid, _ in found:
        try:
            ids.append(extract_id(rid))
        except Exception:
            failures.append(f"row {rid} not found (invalid id)")
    blocks = list(client.fetch_many_blocks(ids)) if ids else []
    resolved: list[tuple[str, dict, object]] = []
    for (rid, props), block in zip(found, blocks):
        if block is None:
            failures.append(f"row {rid} not found")
        else:
            resolved.append((rid, props, block))
    if not resolved:
        return 0, failures

    updated = 0
    with client.batched_transaction():
        for rid, props, row in resolved:
            try:
                for key, val in props.items():
                    if hasattr(row, key):
                        setattr(row, key, val)
                    else:
                        row.set_property(key, val)
                updated += 1
            except Exception as exc:
                failures.append(f"row {rid} failed: {_debug_or_str(exc)}")

    return updated, failures


def delete_rows(client, row_ids: list, permanently: bool = False):
    """Delete many database rows — thin alias of remove_blocks (rows ARE
    blocks); identical batching and failure semantics."""
    from unpy.blocks import remove_blocks

    return remove_blocks(client, row_ids, permanently=permanently)