"""Block-spec builders shared by unpy-mcp and unpy-cli (issue #32).

`[{type, text, checked?, icon?, language?}]` → child blocks, with up-front
validation (all-or-nothing for input errors, issue #24) and partial-success
reporting (issue #19). Pure unpy-core: no MCP imports.
"""

from __future__ import annotations

from requests import HTTPError

from unpy.utils import extract_id


def validate_block_specs(block_specs, type_map: dict) -> list[str]:
    """Up-front spec validation (issue #24): reject malformed input before
    any write so input errors keep the batch all-or-nothing.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    if not isinstance(block_specs, list):
        errors.append(
            f"blocks must be a JSON array of objects, got {type(block_specs).__name__}"
        )
        return errors
    known = set(type_map) if type_map else None
    for i, spec in enumerate(block_specs):
        where = f"block {i + 1}"
        if not isinstance(spec, dict):
            errors.append(f"{where}: expected an object, got {type(spec).__name__}")
            continue
        btype = spec.get("type", "text")
        if not isinstance(btype, str):
            errors.append(
                f"{where}: 'type' must be a string, got {type(btype).__name__}"
            )
            continue
        if known is not None and btype not in known:
            errors.append(f"{where}: unknown type '{btype}'")
        text = spec.get("text", "")
        if not isinstance(text, str):
            errors.append(f"{where}: 'text' must be a string, got {type(text).__name__}")
        checked = spec.get("checked")
        if checked is not None and not isinstance(checked, bool):
            errors.append(
                f"{where}: 'checked' must be a boolean, got {type(checked).__name__}"
            )
        icon = spec.get("icon")
        if icon is not None and not isinstance(icon, str):
            errors.append(f"{where}: 'icon' must be a string, got {type(icon).__name__}")
        language = spec.get("language")
        if language is not None and not isinstance(language, str):
            errors.append(
                f"{where}: 'language' must be a string, got {type(language).__name__}"
            )
    return errors


def batch_denominator(specs, failures: list) -> int:
    """Denominator for the issue-#19 'Added X of N' reports (issue #26): the
    batch size — not the number of failure messages, which shrinks to the
    invalid-spec count when up-front validation rejects the whole batch.
    For a non-list `blocks` payload there is no meaningful batch size, so
    fall back to the failure-message count."""
    return len(specs) if isinstance(specs, list) else len(failures)


def _http_error_detail(exc) -> str:
    detail = str(exc)
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            body = resp.json()
            detail = body.get("debugMessage") or detail
        except Exception:
            pass
    return detail


def _spec_kwargs(spec: dict, type_map: dict):
    from unpy.block import TextBlock

    btype = spec.get("type", "text")
    text = spec.get("text", "")
    cls = type_map.get(btype, TextBlock) if type_map else TextBlock
    kwargs = {"title": text}
    if btype == "todo" and "checked" in spec:
        kwargs["checked"] = spec["checked"]
    if btype == "callout" and "icon" in spec:
        kwargs["icon"] = spec["icon"]
    if btype == "code" and spec.get("language"):
        kwargs["language"] = spec["language"]
    return cls, kwargs


def _add_single_block_spec(parent, spec: dict, type_map: dict) -> str | None:
    """Create one block from a spec; return None on success, error on failure."""
    cls, kwargs = _spec_kwargs(spec, type_map)
    try:
        parent.children.add_new(cls, **kwargs)
        return None
    except Exception as exc:
        detail = _http_error_detail(exc)
        return f"block ({spec.get('type', 'text')}) failed: {detail}"


def add_blocks_from_specs_core(parent, block_specs: list, type_map: dict):
    """Create child blocks from [{type, text, checked?, icon?, language?}] specs.

    Returns (count_added, failures) — one spec's failure does not abort the
    batch; partial success is reported so clients can retry only the
    remainder (issue #19). Used by append_blocks/create_page (MCP) and
    append-blocks/create-page (CLI).

    v2: all specs are buffered inside ONE batched transaction (flushed in
    chunks of UNPY_BATCH_MAX_OPS ops) so N blocks cost ~N/100 HTTP calls
    instead of N. A failing chunk raises; failures from earlier v1 behavior
    (per-block rollback) still apply inside each chunk since each spec's
    create+props are atomic within the buffered transaction.
    """
    from unpy.config import legacy_mode

    # issue #24: validate every spec up front — one bad spec must not
    # abort the batch with blocks already written
    validation_errors = validate_block_specs(block_specs, type_map)
    if validation_errors:
        return 0, validation_errors

    count = 0
    failures = []

    specs = list(enumerate(block_specs))
    if legacy_mode() or len(specs) <= 1:
        # v1 path: one atomic tx per block (also the only sensible path for
        # a single block — no batching gain, but preserves failure isolation)
        for idx, spec in specs:
            cls, kwargs = _spec_kwargs(spec, type_map)
            try:
                parent.children.add_new(cls, **kwargs)
                count += 1
            except Exception as exc:
                detail = str(exc)
                resp = getattr(exc, "response", None)
                if resp is not None:
                    try:
                        body = resp.json()
                        detail = body.get("debugMessage") or detail
                    except Exception:
                        pass
                failures.append(f"block {idx + 1} ({spec.get('type', 'text')}) failed: {detail}")
        return count, failures

    client = getattr(parent, "_client", None)
    if client is None or not hasattr(client, "batched_transaction"):
        # stub parents in tests (no client) — keep the v1 loop
        for idx, spec in specs:
            cls, kwargs = _spec_kwargs(spec, type_map)
            try:
                parent.children.add_new(cls, **kwargs)
                count += 1
            except Exception as exc:
                detail = str(exc)
                resp = getattr(exc, "response", None)
                if resp is not None:
                    try:
                        body = resp.json()
                        detail = body.get("debugMessage") or detail
                    except Exception:
                        pass
                failures.append(f"block {idx + 1} ({spec.get('type', 'text')}) failed: {detail}")
        return count, failures
    committed = 0
    with client.batched_transaction():
        for idx, spec in specs:
            cls, kwargs = _spec_kwargs(spec, type_map)
            try:
                parent.children.add_new(cls, **kwargs)
                count += 1
            except HTTPError as exc:
                # server rejected a property write inside the buffered tx:
                # in batched mode the enclosing chunk fails as a unit — roll
                # progress back to the last committed chunk boundary and
                # report remaining specs as failures (matches v1 semantics:
                # client can retry the remainder).
                detail = _http_error_detail(exc)
                for j in range(idx, len(specs)):
                    failures.append(
                        f"block {j + 1} ({specs[j][1].get('type', 'text')}) failed: {detail}"
                    )
                return committed, failures
            except Exception as exc:
                detail = str(exc)
                resp = getattr(exc, "response", None)
                if resp is not None:
                    try:
                        body = resp.json()
                        detail = body.get("debugMessage") or detail
                    except Exception:
                        pass
                failures.append(
                    f"block {idx + 1} ({spec.get('type', 'text')}) failed: {detail}"
                )
    return count, failures


def remove_blocks(client, block_ids: list, permanently: bool = False):
    """Soft-delete (archive) many blocks in ONE batched transaction.

    Each block costs two ops (alive:false + listRemove on the parent), so N
    blocks are ~2N ops flushed in chunks of batch_max_ops — ~N/50 HTTP calls
    instead of one transaction each (issue #43: deleting a page's content
    line-by-line was painfully slow). `permanently` additionally calls the
    deleteBlocks hard-delete endpoint once at the end with every id.

    Returns (count_deleted, failures): ids that could not be resolved are
    reported, not raised; a failed mid-flush chunk aborts the remaining ids
    with the remaining ones reported as failures (chunks are already
    committed and NOT rolled back — same semantics as add_blocks_from_specs
    batched mode).
    """
    from unpy.config import legacy_mode
    from unpy.utils import InvalidNotionIdentifier

    # dedupe but keep first-seen order; malformed ids become failures
    seen: dict[str, str] = {}
    bad: list[str] = []
    for bid in block_ids:
        if not isinstance(bid, str) or not bid.strip():
            continue
        try:
            key = extract_id(bid)
        except InvalidNotionIdentifier:
            bad.append(bid)
            continue
        seen.setdefault(key, bid)
    ids = list(seen.keys())
    if not ids:
        return 0, bad + ["no valid block ids given"]

    failures: list[str] = list(bad)
    deleted = 0

    # resolve every block up front (batched fan-out fetch, v2) so unknown
    # ids are reported before any write — an unknown id must not abort a
    # half-committed batch
    blocks = list(client.fetch_many_blocks(ids))
    found: list = []
    for bid, block in zip(ids, blocks):
        if block is None:
            failures.append(f"block {bid} not found")
        else:
            found.append(block)

    if not found:
        return 0, failures

    def _ops():
        for block in found:
            if block.is_alias:
                yield {
                    "id": block._alias_parent,
                    "path": ["content"],
                    "args": {"id": block.id},
                    "command": "listRemove",
                    "table": "block",
                }
                continue
            parent_id = block.get("parent_id")
            parent_table = block.get("parent_table", "block")
            child_list_key = block.child_list_key
            if parent_id and parent_table == "block":
                parent = client.get_block(parent_id)
                if parent is not None and hasattr(parent, "child_list_key"):
                    from unpy.block import Block as _Block

                    if isinstance(parent, _Block):
                        child_list_key = parent.child_list_key
            yield {
                "id": block.id,
                "path": [],
                "args": {"alive": False},
                "command": "update",
                "table": "block",
            }
            yield {
                "id": parent_id,
                "path": [child_list_key],
                "args": {"id": block.id},
                "command": "listRemove",
                "table": parent_table,
            }

    data_ops = list(_ops())  # 2 ops per non-alias block
    if legacy_mode():
        # v1-style: one transaction per block, mirrors Block.remove
        for block in found:
            block.remove()
            deleted += 1
    else:
        from unpy.config import batch_max_ops

        cap = batch_max_ops()
        committed_ops = 0
        blocks_committed = 0
        aborted = False
        # walk the chunks ourselves: cap counts DATA ops; use the same
        # split flush_batched uses, but track which blocks are committed
        for start in range(0, len(data_ops), cap):
            chunk = data_ops[start : start + cap]
            try:
                client.submit_transaction(chunk)
                committed_ops += len(chunk)
                blocks_committed = min(len(found), committed_ops // 2)
            except Exception as exc:
                detail = str(exc)
                resp = getattr(exc, "response", None)
                if resp is not None:
                    try:
                        body = resp.json()
                        detail = body.get("debugMessage") or detail
                    except Exception:
                        pass
                failures.append(f"batch chunk failed: {detail}")
                aborted = True
                break
        deleted = blocks_committed
        if aborted:
            for block in found[deleted:]:
                failures.append(f"block {block.id} not deleted (earlier chunk failed)")
        elif permanently:
            client.post(
                "deleteBlocks",
                {"blockIds": [b.id for b in found], "permanentlyDelete": True},
            )

    return deleted, failures


def validate_update_specs(updates) -> list[str]:
    """Up-front validation for update_blocks: [{block_id, text?, checked?,
    language?}] — rejects before any write (same all-or-nothing policy as
    validate_block_specs, issue #24 lineage)."""
    errors: list[str] = []
    if not isinstance(updates, list):
        errors.append(
            f"updates must be a JSON array of objects, got {type(updates).__name__}"
        )
        return errors
    for i, upd in enumerate(updates):
        where = f"update {i + 1}"
        if not isinstance(upd, dict):
            errors.append(f"{where}: expected an object, got {type(upd).__name__}")
            continue
        block_id = upd.get("block_id")
        if not isinstance(block_id, str) or not block_id.strip():
            errors.append(f"{where}: 'block_id' must be a non-empty string")
        for key in ("text", "language", "color"):
            if key in upd and not isinstance(upd[key], str):
                errors.append(f"{where}: '{key}' must be a string")
        if "checked" in upd and upd["checked"] is not None:
            if not isinstance(upd["checked"], bool):
                errors.append(f"{where}: 'checked' must be a boolean")
    return errors


def update_blocks(client, updates: list):
    """Apply many block edits in ONE batched transaction (issue #43).

    updates: [{block_id, text?, checked?, language?, color?}] — `text`
    replaces the block's title/content (markdown, same conversion append_blocks
    uses), `checked` toggles to-dos. All edits buffer into one batched
    transaction flushed in chunks of batch_max_ops — N edits cost ~1 HTTP
    round trip instead of N.

    Returns (count_updated, failures) with the same partial-success
    reporting as remove_blocks; unknown ids are resolved up front (batched
    fan-out fetch) and reported before any write.
    """
    from unpy.config import legacy_mode

    errors = validate_update_specs(updates)
    if errors:
        return 0, errors

    ids: list[str] = []
    seen: set[str] = set()
    bad: list[str] = []
    for upd in updates:
        try:
            key = extract_id(upd["block_id"])
        except Exception:
            key = None
        if not key or key in seen:
            bad.append(f"update: bad block_id {upd['block_id']!r}")
            continue
        seen.add(key)
        ids.append(key)

    # resolve every block up front (batched fan-out fetch): unknown ids are
    # reported before any write, and the right setter set is known per class
    blocks = list(client.fetch_many_blocks(ids))
    found: list = []
    by_spec: list[tuple[dict, object]] = []
    failures: list[str] = list(bad)
    for upd, block in zip(updates, blocks):
        if block is None:
            failures.append(f"block {upd['block_id']} not found")
        else:
            found.append(block)
            by_spec.append((upd, block))
    if not found:
        return 0, failures

    def _ops():
        from unpy.markdown import markdown_to_notion, plaintext_to_notion

        for upd, block in by_spec:
            if "text" in upd:
                path = ["properties", "title"]
                # code blocks carry verbatim content (no markdown pass)
                if block.get("type") == "code":
                    value = plaintext_to_notion(upd["text"])
                else:
                    value = markdown_to_notion(upd["text"])
                yield {
                    "id": block.id,
                    "path": path,
                    "command": "updateBlockPropertyValue",
                    "table": "block",
                    "args": {"primitiveOp": {"command": "set", "args": value}},
                }
            if "checked" in upd and upd["checked"] is not None:
                yield {
                    "id": block.id,
                    "path": ["properties", "checked"],
                    "command": "updateBlockPropertyValue",
                    "table": "block",
                    "args": {"primitiveOp": {"command": "set", "args": [
                        [["Yes" if upd["checked"] else "No"]]
                    ]}},
                }
            if upd.get("language"):
                yield {
                    "id": block.id,
                    "path": ["properties", "language"],
                    "command": "updateBlockPropertyValue",
                    "table": "block",
                    "args": {"primitiveOp": {"command": "set", "args": [
                        [[upd["language"]]]
                    ]}},
                }
            if upd.get("color"):
                yield {
                    "id": block.id,
                    "path": ["format", "block_color"],
                    "command": "update",
                    "table": "block",
                    "args": upd["color"],
                }

    data_ops = list(_ops())
    failures2: list[str] = []
    if legacy_mode():
        # v1-style: apply via the property setters (one tx via setters' own
        # submits are already batched by transaction context in callers)
        for upd, block in by_spec:
            try:
                if "text" in upd:
                    block.title = upd["text"]
                if "checked" in upd and upd["checked"] is not None:
                    block.checked = upd["checked"]
                if upd.get("language"):
                    block.language = upd["language"]
                if upd.get("color"):
                    block.color = upd["color"]
            except Exception as exc:
                failures2.append(f"block {block.id} failed: {exc}")
        return len(by_spec) - len(failures2), failures + failures2

    failed_ids: set[str] = set()
    from unpy.config import batch_max_ops

    cap = batch_max_ops()
    for start in range(0, len(data_ops), cap):
        chunk = data_ops[start : start + cap]
        try:
            # submit_transaction replays the ops locally (run_local_operations)
            client.submit_transaction(chunk)
        except Exception as exc:
            resp = getattr(exc, "response", None)
            detail = str(exc)
            if resp is not None:
                try:
                    body = resp.json()
                    detail = body.get("debugMessage") or detail
                except Exception:
                    pass
            for op in chunk:
                failed_ids.add(op["id"])
            failures2.append(f"batch chunk failed: {detail}")
            break
    if failed_ids:
        for upd, block in by_spec:
            if block.id in failed_ids:
                failures2.append(f"block {block.id} failed: chunk rejected")
        return len(by_spec) - len(failed_ids), failures + failures2
    return len(by_spec), failures