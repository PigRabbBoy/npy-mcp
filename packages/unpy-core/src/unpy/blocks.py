"""Block-spec builders shared by unpy-mcp and unpy-cli (issue #32).

`[{type, text, checked?, icon?, language?}]` → child blocks, with up-front
validation (all-or-nothing for input errors, issue #24) and partial-success
reporting (issue #19). Pure unpy-core: no MCP imports.
"""

from __future__ import annotations

from requests import HTTPError


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