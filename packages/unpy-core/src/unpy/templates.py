"""Database template creation/readback shared by unpy-mcp and unpy-cli (issue #38).

A template is a page block with is_template=true parented directly on the
collection, listed in the collection's template_pages, optionally the
collection default (format.collection_default_template). The body is
ordinary child blocks built from the shared block-spec builder
(unpy.blocks).
"""

from __future__ import annotations

# property types a template default may NOT set (computed server-side)
NON_WRITABLE_TYPES = {
    "formula", "rollup", "created_time", "last_edited_time",
    "created_by", "last_edited_by", "id",
}


def find_template_by_name(collection, title: str):
    """First live template with this title (idempotency), or None."""
    want = (title or "").strip().lower()
    if not want:
        return None
    store = collection._client._store._values.get("block", {})
    for tid in collection.get("template_pages") or []:
        data = store.get(tid) or {}
        if data.get("alive") is False or not data.get("is_template"):
            continue
        props = data.get("properties") or {}
        title_val = props.get("title") or []
        text = "".join(
            seg[0] for seg in title_val
            if isinstance(seg, list) and seg and isinstance(seg[0], str)
            and not seg[0].startswith("‣")
        ) or ""
        if text.strip().lower() == want:
            from unpy.collection import CollectionRowBlock

            return CollectionRowBlock(collection._client, tid)
    return None


def _resolve_prop_by_name(raw_schema: dict, name: str):
    """name (case-insensitive) or id → (pid, prop); raises ValueError."""
    from unpy.utils import slugify as _slug

    ident = (name or "").strip()
    if ident in raw_schema:
        return ident, raw_schema[ident]
    want = _slug(ident).lower()
    for pid, p in raw_schema.items():
        if p is None or p.get("alive") is False:
            continue
        if _slug(p.get("name", "")).lower() == want:
            return pid, p
    available = ", ".join(
        p.get("name") for p in raw_schema.values()
        if p and p.get("alive") is not False
    )
    raise ValueError(
        f"property '{name}' not found in this database (available: {available})"
    )


def resolve_property_defaults(collection, properties: str | dict) -> dict:
    """--properties JSON {"Name": value} → {prop_id: raw_value} (no writes).

    Validates BEFORE any write: unknown property, computed property
    (formula/rollup/created…), and select/status options are checked
    strictly against the schema — a typo is an error, not a silent create.
    """
    if isinstance(properties, dict):
        raw = properties
    else:
        import json as _json

        text = (properties or "").strip()
        if not text:
            return {}
        try:
            raw = _json.loads(text)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"properties is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"properties must be a JSON object, got {type(raw).__name__}")
    schema = collection.get("schema") or {}
    out = {}
    for name, val in raw.items():
        pid, prop = _resolve_prop_by_name(schema, name)
        ptype = prop.get("type", "text")
        if ptype in NON_WRITABLE_TYPES:
            raise ValueError(
                f"property '{name}' ({ptype}) is computed — templates "
                "cannot set a default for it"
            )
        if ptype in ("select", "multi_select", "status") and val:
            values = val if isinstance(val, list) else [val]
            valid = [
                (o.get("value") or "").lower()
                for o in prop.get("options") or []
            ]
            for v in values:
                if str(v).strip().lower() not in valid:
                    raise ValueError(
                        f"option '{v}' is not a valid option of '{name}' "
                        "(available: "
                        + ", ".join(o.get("value", "") for o in prop.get("options") or [])
                        + ")"
                    )
        out[pid] = val
    return out


def validate_block_specs_specs(block_specs) -> list[str]:
    """Body spec validation via the CLI-visible types (subset of block.py)."""
    from unpy.blocks import validate_block_specs
    from unpy.block import (
        BulletedListBlock, CalloutBlock, CodeBlock, DividerBlock,
        EquationBlock, HeaderBlock, NumberedListBlock, QuoteBlock,
        SubheaderBlock, SubsubheaderBlock, TextBlock, TodoBlock, ToggleBlock,
    )

    TYPE_MAP = {
        "text": TextBlock,
        "todo": TodoBlock,
        "header": HeaderBlock,
        "subheader": SubheaderBlock,
        "subsubheader": SubsubheaderBlock,
        "callout": CalloutBlock,
        "bulleted_list": BulletedListBlock,
        "numbered_list": NumberedListBlock,
        "quote": QuoteBlock,
        "code": CodeBlock,
        "divider": DividerBlock,
        "toggle": ToggleBlock,
        "equation": EquationBlock,
    }
    return validate_block_specs(block_specs, TYPE_MAP)


def template_body_type_map() -> dict:
    """The block-spec type map used for template bodies (CLI parity)."""
    from unpy.block import (
        BulletedListBlock, CalloutBlock, CodeBlock, DividerBlock,
        EquationBlock, HeaderBlock, NumberedListBlock, QuoteBlock,
        SubheaderBlock, SubsubheaderBlock, TextBlock, TodoBlock, ToggleBlock,
    )

    return {
        "text": TextBlock,
        "todo": TodoBlock,
        "header": HeaderBlock,
        "subheader": SubheaderBlock,
        "subsubheader": SubsubheaderBlock,
        "callout": CalloutBlock,
        "bulleted_list": BulletedListBlock,
        "numbered_list": NumberedListBlock,
        "quote": QuoteBlock,
        "code": CodeBlock,
        "divider": DividerBlock,
        "toggle": ToggleBlock,
        "equation": EquationBlock,
    }


def create_template(
    client,
    collection,
    title: str,
    properties: str | dict = "",
    blocks: str | list = "",
    icon: str = "",
    default: bool = False,
):
    """Create (or update in place) one database template (issue #38).

    Idempotent by title: an existing template is updated — listed property
    defaults are set (unlisted left unchanged); a --blocks body REPLACES
    the old body (old top-level children archived first); --icon and
    --default applied when given. Multiple templates with the same title:
    the first is updated, warning returned in the message.

    Returns (template_row, message).
    """
    from unpy.blocks import add_blocks_from_specs_core

    # resolve + validate everything BEFORE any write
    defaults = resolve_property_defaults(collection, properties)
    body_specs = blocks if isinstance(blocks, list) else None
    if not isinstance(blocks, (list, dict)) and blocks:
        import json as _json

        try:
            body_specs = _json.loads(blocks)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"blocks is not valid JSON: {exc}") from exc
    if body_specs is not None:
        type_map = template_body_type_map()
        errors = validate_block_specs_specs(body_specs)
        if errors:
            raise ValueError("; ".join(errors))

    existing = find_template_by_name(collection, title)
    messages = []
    if existing is not None:
        row = existing
        messages.append(f"updated existing template '{title}' in place")
    else:
        row = collection.add_row(update_views=False, **{"title": title})
        # flip into a template: parent on the collection, register in
        # template_pages (NOT content), mark is_template
        row.set("is_template", True)
        row.set("parent_table", "collection")
        pages = collection.get("template_pages") or []
        client.submit_transaction([
            {"table": "collection", "id": collection.id,
             "path": ["template_pages"], "command": "listAfter",
             "args": {"id": row.id}},
        ])
        _ = pages

    if defaults:
        for pid, val in defaults.items():
            row.set_property(pid, val)

    if body_specs is not None:
        # replace the body: archive the old top-level children, then add
        for old_id in row.get("content") or []:
            old = client.get_block(old_id)
            if old is not None:
                try:
                    old.set("alive", False)
                except Exception:
                    pass
        type_map = template_body_type_map()
        _count, failures = add_blocks_from_specs_core(row, body_specs, type_map)
        if failures:
            messages.append(
                "body written with " + str(len(failures)) + " failed spec(s): "
                + "; ".join(failures)
            )

    if icon:
        row.set(["format", "page_icon"], icon)

    if default:
        collection.set(["format", "collection_default_template"],
                       {"template_page_id": row.id})
        # rewrite per-view overrides so "all views" really means all views
        block = getattr(collection, "parent", None)
        for vid in block.get("view_ids") or [] if block is not None else []:
            data = client._store._values.get("collection_view", {}).get(vid)
            if not data or data.get("alive") is False:
                continue
            from unpy.collection import COLLECTION_VIEW_TYPES, CollectionView

            cls = COLLECTION_VIEW_TYPES.get(data.get("type", ""), CollectionView)
            view = cls(client, vid, collection=collection)
            view.set("collection_view_default_template",
                     {"template_page_id": row.id})

    message = "Created template " if existing is None else "Updated template "
    message += f"'{title}': {row.id}"
    if messages:
        message += " (" + "; ".join(messages) + ")"
    return row, message


def list_templates(collection, client) -> list[dict]:
    """Readback: every live template with property NAMES (issue #38)."""
    schema = collection.get("schema") or {}
    def _name_of(pid: str) -> str:
        if pid in schema:
            return schema[pid].get("name", pid)
        return pid

    store = client._store._values.get("block", {})
    # the collection-level default (also read per-view keys)
    default_id = (((collection.get("format") or {}).get("collection_default_template")) or {}).get("template_page_id")
    out = []
    for tid in collection.get("template_pages") or []:
        data = store.get(tid) or {}
        if data.get("alive") is False or not data.get("is_template"):
            continue
        props = data.get("properties") or {}
        values = {}
        for pid, raw in props.items():
            if pid == "title":
                values["title"] = "".join(
                    seg[0] for seg in (raw or [])
                    if isinstance(seg, list) and seg and isinstance(seg[0], str)
                    and not seg[0].startswith("‣")
                ) or ""
                continue
            ptype = (schema.get(pid) or {}).get("type", "text")
            if ptype in NON_WRITABLE_TYPES:
                continue
            values[_name_of(pid)] = _readback_value(raw, ptype)
        body = [
            (client._store._values.get("block", {}).get(cid) or {}).get("type", cid)
            for cid in data.get("content") or []
        ]
        fmt = data.get("format") or {}
        out.append({
            "id": tid,
            "title": values.get("title", ""),
            "default": tid == default_id,
            "properties": {k: v for k, v in values.items() if k != "title"},
            "icon": fmt.get("page_icon", ""),
            "body_blocks": body,
        })
    return out


def _readback_value(raw, ptype: str):
    from unpy.markdown import notion_to_markdown

    if raw is None:
        return None
    if ptype in ("title", "text", "url", "email", "phone_number"):
        return "".join(
            seg[0] for seg in (raw or [])
            if isinstance(seg, list) and seg and isinstance(seg[0], str)
            and not seg[0].startswith("‣")
        ) or notion_to_markdown(raw)
    if ptype in ("select", "status"):
        return raw[0][0] if raw else None
    if ptype == "multi_select":
        return [v.strip() for v in raw[0][0].split(",")] if raw else []
    if ptype == "checkbox":
        return bool(raw) and raw[0][0] == "Yes"
    if ptype == "number":
        try:
            return float(raw[0][0]) if raw else None
        except (TypeError, ValueError, IndexError):
            return None
    return notion_to_markdown(raw)