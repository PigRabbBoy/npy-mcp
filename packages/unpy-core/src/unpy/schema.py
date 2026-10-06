"""Database schema builders shared by unpy-mcp and unpy-cli.

Moved out of the MCP server (issue #32): the CLI's write commands need the
same column-spec → Notion-schema translation, and a CLI-only install must
not import `unpy_mcp`.

Pure helpers here: no MCP imports, only unpy-core primitives.
"""

from __future__ import annotations

import uuid


def build_select_options(values: list) -> list:
    """Build select/multi_select/status option dicts.

    Notion identifies options by id; without one the UI cannot edit the
    option's colour (the edit appears to create a new option and revert,
    issue #15). Values that already carry an id pass through untouched.
    """
    out = []
    for o in values:
        if isinstance(o, dict):
            out.append(
                {**{"id": str(uuid.uuid4()), "color": "default"}, **o}
                if not o.get("id")
                else o
            )
        else:
            out.append({"id": str(uuid.uuid4()), "value": o, "color": "default"})
    return out


def resolve_collection_id(client, ref: str) -> str:
    """Resolve a database URL/ID to a collection ID (tolerates short ids)."""
    from unpy.utils import extract_id

    raw = (ref or "").strip()
    if not raw:
        return ""
    try:
        raw = extract_id(raw)
    except Exception:
        pass  # keep raw as-is; caller may pass a short/partial id
    block = client.get_block(raw) if client else None
    if block is not None:
        coll = getattr(block, "collection", None)
        if coll is not None:
            return coll.id
    return raw


def build_relation_prop(spec: dict, client, parent_space_id: str) -> dict:
    """Build the schema fragment for a relation property.

    If "reverse_name" is set, returns a fragment carrying the symmetric
    two-way shape observed in Notion's own client: the forward prop holds
    "property": <reverse_prop_id> and "version": "v2". The caller is
    responsible for writing the matching reverse property into the target
    collection's schema.
    """
    target_ref = spec.get("target_database_id", "")
    if not target_ref:
        raise ValueError(
            f"Column '{spec.get('name', '?')}': relation columns need "
            "'target_database_id' (URL or ID of the related database)"
        )
    target_id = resolve_collection_id(client, target_ref)
    space_id = parent_space_id or (
        client.current_space.id if client and client.current_space else ""
    )
    prop = {
        "collection_id": target_id,
        "collection_pointer": {
            "id": target_id,
            "table": "collection",
            "spaceId": space_id,
        },
    }
    if spec.get("limit") == 1:
        prop["limit"] = 1
    reverse_name = spec.get("reverse_name")
    if reverse_name:
        # Notion's UI always writes autoRelate disabled; two-way sync is
        # achieved by a real property on the other collection, not autoRelate.
        prop["version"] = "v2"
        prop["property"] = spec.get("_reverse_prop_id") or uuid.uuid4().hex[:4]
    prop["autoRelate"] = {"enabled": False}
    return prop


def find_prop_id(schema: dict, name: str) -> str:
    from unpy.utils import slugify as _slug
    want = _slug(name).lower()
    for pid, p in schema.items():
        if _slug(p.get("name", "")).lower() == want:
            return pid
    return ""


def fetch_schema(client, col_id: str) -> dict:
    if not col_id or client is None:
        return {}
    try:
        coll = client.get_collection(col_id)
        return coll.get("schema") or {}
    except Exception:
        return {}


def build_rollup_prop(spec: dict, client, fetch=None) -> dict:
    """Build the schema fragment for a rollup property.

    Needs the relation property (by name) on THIS database and the target
    property (by name) on the related database. `fetch` optionally supplies
    the schema-fetch callable (tests patch it); defaults to fetch_schema.
    """
    rel_name = spec.get("relation_property", "")
    target_name = spec.get("target_property", "")
    if not (rel_name and target_name):
        raise ValueError(
            f"Column '{spec.get('name', '?')}': rollup columns need "
            "'relation_property' and 'target_property' names"
        )
    own_schema = spec.get("_own_schema") or {}
    rel_pid = find_prop_id(own_schema, rel_name)
    if not rel_pid:
        raise ValueError(
            f"rollup '{spec.get('name', '?')}': relation property "
            f"'{rel_name}' not found in this database"
        )
    rel_prop = own_schema.get(rel_pid, {})
    target_col_id = rel_prop.get("collection_id") or (
        rel_prop.get("collection_pointer") or {}
    ).get("id", "")
    # fetch_schema is resolved through this module's namespace (or the
    # caller-provided `fetch`) so tests can patch it in one place
    if fetch is None:
        import sys as _sys

        mod = _sys.modules[__name__]
        fetch = mod.__dict__.get("fetch_schema", fetch_schema)
    target_schema = fetch(client, target_col_id)
    tgt_pid = find_prop_id(target_schema, target_name)
    if not tgt_pid:
        raise ValueError(
            f"rollup '{spec.get('name', '?')}': target property "
            f"'{target_name}' not found in related database"
        )
    prop = {
        "version": "v2",
        "rollup_type": rel_prop.get("type", "relation"),
        "target_property": tgt_pid,
        "relation_property": rel_pid,
        "target_property_type": target_schema.get(tgt_pid, {}).get("type", "text"),
    }
    agg = spec.get("aggregation")
    # "show_original" is how the UI spells "no aggregation" — the schema
    # stores it by OMITTING the field entirely. Writing the literal string
    # breaks every Notion client that opens the database (issue #14).
    if agg and agg not in ("show_original", "original"):
        prop["aggregation"] = agg
    return prop


def build_formula_prop(spec: dict) -> dict:
    """Build the schema fragment for a formula property.

    spec needs "expression" (Notion formula2 source referencing properties
    as {"Name"}) and optionally "_formula_prop_meta" — a name →
    {"property", "collection"} map (built by the caller from the database's
    schema) so the Notion UI can resolve references.
    """
    from unpy.formula_eval import encode_expr

    expr = spec.get("expression", "")
    if not expr:
        raise ValueError(
            f"Column '{spec.get('name', '?')}': formula columns need an "
            "'expression'"
        )
    prop_meta = spec.get("_formula_prop_meta") or {}
    return {
        "version": "v2",
        "formula2": {
            "code": encode_expr(expr, prop_meta),
            "result_type": {"type": "text"},
        },
    }


def build_formula_prop_meta(own_schema: dict, own_pointer: dict, extra_specs=None) -> dict:
    """Build the name → {property, collection} meta map formula encoding needs.

    `own_schema` is the schema dict of the formula's own collection.
    `extra_specs` (optional) is the list of column specs being built
    alongside (create-database two-pass build) — specs already carrying a
    generated id are included so same-transaction references resolve.
    """
    prop_meta = {}
    if extra_specs:
        for other in extra_specs:
            other_name = other.get("name", "")
            other_id = other.get("id")
            if not (other_name and other_id):
                continue
            meta = {"property": other_id}
            if other.get("type") == "relation":
                tgt = other.get("collection_id") or (
                    other.get("collection_pointer") or {}
                ).get("id")
                meta["collection"] = {
                    "id": tgt or "",
                    "table": "collection",
                    "spaceId": (own_pointer or {}).get("spaceId", ""),
                }
            else:
                meta["collection"] = own_pointer
            prop_meta[other_name] = meta
    for pid, p in own_schema.items():
        if p is None or p.get("alive") is False:
            continue
        meta = {"property": pid}
        if p.get("type") == "relation":
            tgt = p.get("collection_id") or (p.get("collection_pointer") or {}).get("id")
            meta["collection"] = {
                "id": tgt or "",
                "table": "collection",
                "spaceId": (own_pointer or {}).get("spaceId", ""),
            }
        else:
            meta["collection"] = own_pointer
        prop_meta[p.get("name", "")] = meta
    return prop_meta


def build_collection_schema(col_specs: list, client=None, parent_space_id: str = "") -> dict:
    """Build a Notion collection schema from column specs.

    Each spec: {"name": str, "type": str, "options": [str, ...]}
    Relation specs additionally accept:
        "target_database_id": URL/ID of the related database (required),
        "limit": 1 caps the relation at one linked row,
        "reverse_name": creates a two-way synced property on the target
            database (written via a forward+reverse schema transaction).
    Formula specs accept "expression" (Notion formula2 source) and,
    optionally, a precomputed "_formula_prop_meta". Without one, refs are
    encoded name-only.
    Rollup specs accept "relation_property" (name), "target_property" (name),
        and optional "aggregation" ("show_original" omitted, issue #14).
    Returns: {prop_id: {"name": str, "type": str, ...}}
    """
    schema = {}
    for spec in col_specs:
        name = spec.get("name", "Untitled")
        ptype = spec.get("type", "text")
        # The first title column MUST get prop id "title" — Notion requires a
        # property with that id in every collection; when it's missing the
        # server silently adds its own "Name" title prop, producing two title
        # columns (issue #6).
        if ptype == "title":
            if "title" in schema:
                raise ValueError(
                    f"Column '{name}': a database can have only one title "
                    f"column ('{schema['title']['name']}' is already the title)"
                )
            prop_id = "title"
        else:
            prop_id = spec.get("id") or uuid.uuid4().hex[:4]
        # stamp so a later pass reuses the same id (two-pass rollup build)
        spec["id"] = prop_id
        prop = {"name": name, "type": ptype}
        if "description" in spec and spec.get("description"):
            # issue #39: honour the in-place manual text on create
            prop["description"] = spec["description"]
        if ptype in ("select", "multi_select", "status") and spec.get("options"):
            prop["options"] = build_select_options(spec["options"])
        if ptype == "relation":
            rel = build_relation_prop(spec, client, parent_space_id)
            if rel.get("property") and not spec.get("_reverse_prop_id"):
                spec["_reverse_prop_id"] = rel["property"]
            prop.update(rel)
        elif ptype == "formula":
            prop.update(build_formula_prop(spec))
        elif ptype == "rollup":
            prop.update(build_rollup_prop(spec, client))
        if "description" in spec:
            prop["description"] = spec.get("description") or ""
        schema[prop_id] = prop
    return schema


def find_column(schema: dict, identifier: str):
    """Find a property in a schema dict by property id or name.

    Returns (prop_id, prop) or (None, None). Tombstoned properties are
    skipped.
    """
    ident = (identifier or "").strip()
    if ident in schema:
        prop = schema[ident]
        if prop is None or prop.get("alive") is False:
            return None, None
        return ident, prop
    ident_lower = ident.lower()
    for pid, prop in schema.items():
        if prop is None or prop.get("alive") is False:
            continue  # tombstoned (deleted) property
        if (prop.get("name") or "").strip().lower() == ident_lower:
            return pid, prop
    return None, None


def resolve_collection_for_write(client, database_id):
    """Resolve a database URL/ID to a collection object for write tools.

    Returns the collection, or an error string when unresolvable.
    """
    block = client.get_block(database_id)
    collection = getattr(block, "collection", None) if block is not None else None
    if collection is None and block is not None and block.get("view_ids"):
        for vid in block.get("view_ids") or []:
            cv_data = client._store._values.get("collection_view", {}).get(vid)
            if cv_data:
                ptr = cv_data.get("format", {}).get("collection_pointer", {})
                if ptr.get("id"):
                    try:
                        collection = client.get_collection(ptr["id"])
                        break
                    except Exception:
                        pass
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    if collection is None:
        return f"Database not found: {database_id}"
    return collection


def add_column_prop(client, collection, name: str, coltype: str, options: str = ""):
    """Build and submit the schema ops to add one column (issue #33).

    Uses high-level schema operations (build_collection_schema_update) —
    plain whole-schema `set` writes are rejected with 400
    "Collection schema updates must use high-level schema operations".
    Two-way relations are written as a forward+reverse op pair in ONE
    transaction (Notion validates the back-reference).

    Returns (message, prop_id). `message` is a caller-facing confirmation.
    Raises ValueError with a caller-facing message on invalid input.
    """
    import uuid as _uuid

    from unpy.operations import build_collection_schema_update
    from unpy.formula_eval import encode_expr

    # A second title column is invalid in Notion — every collection already
    # has one — so refuse a title here rather than create a broken schema (#6).
    if coltype == "title":
        raise ValueError(
            "cannot add a title column — every database already has exactly "
            "one (rename the existing title column instead)"
        )
    prop_id = _uuid.uuid4().hex[:4]
    prop: dict = {"name": name, "type": coltype}

    if coltype in ("select", "multi_select", "status"):
        if options:
            opts = json_loads(options)
            if not isinstance(opts, list):
                raise ValueError(
                    f"select options must be a JSON array, got {type(opts).__name__}"
                )
            prop["options"] = build_select_options(opts)
    elif coltype in ("relation", "formula", "rollup"):
        # options doubles as the spec JSON for advanced column types
        spec = json_loads(options) if (options or "").strip() else {}
        if not isinstance(spec, dict):
            raise ValueError(f"{coltype} options must be a JSON object")
        spec = dict(spec)
        spec.setdefault("name", name)
        spec["type"] = coltype
        space_id = client.current_space.id if client.current_space else ""
        if coltype == "relation":
            prop.update(build_relation_prop(spec, client, space_id))
            spec["id"] = prop_id
            spec["_reverse_prop_id"] = prop.get("property")
            if "description" in spec:
                prop["description"] = spec.get("description") or ""
        elif coltype == "formula":
            if not spec.get("expression"):
                raise ValueError("formula columns need a spec with 'expression'")
            own_schema = collection.get("schema") or {}
            own_pointer = {
                "id": getattr(collection, "id", ""),
                "table": "collection",
                "spaceId": space_id,
            }
            prop_meta = build_formula_prop_meta(own_schema, own_pointer)
            prop.update(build_formula_prop({**spec, "_formula_prop_meta": prop_meta}))
            if "description" in spec:
                prop["description"] = spec.get("description") or ""
        elif coltype == "rollup":
            spec["_own_schema"] = collection.get("schema") or {}
            prop.update(build_rollup_prop(spec, client))
            if "description" in spec:
                prop["description"] = spec.get("description") or ""

    if coltype == "relation" and prop.get("property"):
        target_id = prop.get("collection_id", "")
        own_coll_id = collection.id
        reverse_prop = {
            "name": spec.get("reverse_name") or name,
            "type": "relation",
            "collection_id": own_coll_id,
            "collection_pointer": {
                "id": own_coll_id,
                "table": "collection",
                "spaceId": space_id,
            },
            "property": prop_id,
            "version": "v2",
            "autoRelate": {"enabled": False},
        }
        if target_id and target_id != own_coll_id:
            target_coll = client.get_collection(target_id)
            if target_coll is None:
                raise ValueError(
                    f"Relation target database '{target_id}' not found — "
                    "cannot create reverse property"
                )
            client.submit_transaction([
                build_collection_schema_update(own_coll_id, prop_id, prop),
                build_collection_schema_update(
                    target_id, prop["property"], reverse_prop
                ),
            ])
            return (
                f"Added column '{name}' (type: relation, id: {prop_id}) "
                f"with reverse '{reverse_prop['name']}' "
                f"(id: {prop['property']}) on the target database"
            ), prop_id
        # self-referencing: one prop serves both directions — point it at
        # itself, like Notion's own self-referencing relations
        prop["property"] = prop_id
        client.submit_transaction([
            build_collection_schema_update(own_coll_id, prop_id, prop)
        ])
        return f"Added column '{name}' (type: {coltype}, id: {prop_id}) to database", prop_id

    client.submit_transaction([
        build_collection_schema_update(collection.id, prop_id, prop)
    ])
    return f"Added column '{name}' (type: {coltype}, id: {prop_id}) to database", prop_id


def json_loads(text: str):
    import json

    return json.loads(text)


def set_property_description(client, collection, column: str, text: str):
    """Set (or clear) a property's description (issue #39).

    Writes the FULL current property definition plus `description` through
    build_collection_schema_update — the high-level schema op — so options,
    relation config, rollup/formula settings are preserved unchanged.

    Returns (prop_id, old_description). Raises ValueError for an unknown
    column (message lists the available columns).
    """
    from unpy.operations import build_collection_schema_update

    schema = collection.get("schema") or {}
    prop_id, prop = find_column(schema, column)
    if prop_id is None:
        names = [
            p.get("name") for p in schema.values()
            if p and p.get("alive") is not False and p.get("name")
        ]
        raise ValueError(
            f"column '{column}' not found in this database (available: "
            + ", ".join(names) + ")"
        )
    old = prop.get("description", "") or ""
    new_prop = dict(prop)
    new_prop["description"] = text or ""
    client.submit_transaction([
        build_collection_schema_update(collection.id, prop_id, new_prop)
    ])
    return prop_id, old


# ---------------------------------------------------------------------------
# Full-schema readback (issue #31) — shared by the MCP get_database tool and
# the CLI get-database --full-schema so the two outputs cannot drift.
# ---------------------------------------------------------------------------


def _formula_prop_refs(prop_schema: dict, client=None):
    """Return (display_src, raw_src, refs) for a formula property.

    display_src rewrites every {N} placeholder as prop("Name") — the form
    the Notion formula editor shows (issue #31 gap 1). refs carry the
    {property, collection} metadata per placeholder.
    """
    from unpy.formula_eval import build_expr

    raw, refs = build_expr(prop_schema)
    display = raw
    for i, ref in enumerate(refs):
        name = ref.get("name", "")
        display = display.replace("{" + str(i) + "}", f'prop("{name}")')
    return display, raw, refs


def _rollup_names(prop, schema: dict, client=None):
    """Resolve a rollup's relation/target property NAMES (issue #31 gap 2)."""
    rel_pid = prop.get("relation_property", "")
    tgt_pid = prop.get("target_property", "")
    rel_name = (schema.get(rel_pid) or {}).get("name", rel_pid)
    tgt_name = tgt_pid
    tgt_type = None
    rel_prop = schema.get(rel_pid) or {}
    target_col_id = rel_prop.get("collection_id") or (
        rel_prop.get("collection_pointer") or {}
    ).get("id")
    target_schema = fetch_schema(client, target_col_id) if target_col_id else {}
    if target_schema:
        tgt_name = (target_schema.get(tgt_pid) or {}).get("name", tgt_pid)
        tgt_type = (target_schema.get(tgt_pid) or {}).get("type")
    return {
        "relation_property": rel_name,
        "relation_property_id": rel_pid,
        "target_property": tgt_name,
        "target_property_id": tgt_pid,
        "target_property_type": tgt_type,
        "aggregation": prop.get("aggregation") or "show_original",
    }


def _relation_reverse_name(prop, client=None):
    """Resolve the reverse (synced) property name for a two-way relation
    (issue #31 gap 3): it lives on the TARGET collection and is identified
    by the forward prop's "property" id — autoRelate is always disabled."""
    reverse_prop_id = prop.get("property")
    if not reverse_prop_id:
        return None, None
    target_col_id = prop.get("collection_id") or (
        prop.get("collection_pointer") or {}
    ).get("id")
    target_schema = fetch_schema(client, target_col_id) if target_col_id else {}
    rp = target_schema.get(reverse_prop_id) or {}
    return rp.get("name"), reverse_prop_id


_SCHEMA_FIELD_NAMES = {
    # relation target collection id key varies by shape; handled inline
}


def full_schema_entries(collection, client=None) -> list[dict]:
    """Rich schema readback for provisioning diffing (issue #31).

    One entry per live (non-tombstoned) schema property:
      {"id", "name", "type", "description"} plus per-type fields:
       - select/multi_select/status: options (names, in order); status
         also carries groups as [{name, options}].
       - relation: target (data-source id), single (bool), reverse (name
         of the synced property on the target, or None for one-way),
         reverse_id, limit.
       - rollup: resolved names + ids + aggregation ("show_original"
         when the field is absent).
       - formula: expression with prop("Name") refs, raw_expression
         (stored {N} form) and refs.
    """
    raw_schema = collection.get("schema") or {}
    entries = []
    for pid, p in raw_schema.items():
        if p is None or p.get("alive") is False:
            continue  # tombstoned (deleted) property
        ptype = p.get("type", "?")
        entry = {
            "id": pid,
            "name": p.get("name", "?"),
            "type": ptype,
            "description": p.get("description", "") or "",
        }
        if ptype in ("select", "multi_select", "status"):
            entry["options"] = [
                o.get("value", "") for o in (p.get("options") or [])
            ]
            if ptype == "status":
                groups = p.get("groups") or []
                entry["groups"] = [
                    {
                        "name": g.get("name", ""),
                        "options": [
                            (raw_schema.get(pid, {})).get("options", [])[0] and "" or ""
                        ],
                    }
                    for g in groups
                ]
                # groups reference option ids — resolve names properly
                opt_by_id = {
                    o.get("id", ""): o.get("value", "")
                    for o in (p.get("options") or [])
                }
                entry["groups"] = [
                    {
                        "name": g.get("name", ""),
                        "options": [opt_by_id.get(oid, oid) for oid in (g.get("options") or [])],
                    }
                    for g in groups
                ]
        elif ptype == "relation":
            tgt = p.get("collection_pointer") or {}
            entry["target"] = p.get("collection_id") or tgt.get("id", "")
            entry["single"] = p.get("limit") == 1
            rname, rid = _relation_reverse_name(p, client)
            entry["reverse"] = rname
            entry["reverse_id"] = rid
        elif ptype == "rollup":
            entry.update(_rollup_names(p, raw_schema, client))
        elif ptype == "formula":
            display, raw, refs = _formula_prop_refs(p, client)
            entry["expression"] = display
            entry["raw_expression"] = raw
            entry["refs"] = refs
        entries.append(entry)
    return entries


def render_full_schema_markdown(collection, client=None) -> list[str]:
    """The markdown '## Full schema' section lines (same data as
    full_schema_entries, human-readable) — shared by the MCP get_database.
    """
    lines = []
    for e in full_schema_entries(collection, client):
        lines.append(f"  - **{e['name']}** ({e['type']}) [id: {e['id']}]")
        if e.get("description"):
            lines.append(f"      description: {e['description']}")
        if e["type"] == "relation":
            lines.append(f"      target: {e.get('target', '?')}")
            lines.append(f"      single: {'yes' if e.get('single') else 'no'}")
            if e.get("reverse"):
                lines.append(f"      reverse_name: {e['reverse']} (id: {e.get('reverse_id')})")
            elif e.get("reverse_id"):
                lines.append(f"      reverse_name: (unnamed; id: {e['reverse_id']})")
        elif e["type"] == "rollup":
            lines.append(f"      relation_property: {e.get('relation_property', '?')}")
            lines.append(f"      target_property: {e.get('target_property', '?')}")
            lines.append(f"      aggregation: {e.get('aggregation', 'show_original')}")
        elif e["type"] == "formula":
            lines.append(f"      expression: {e.get('expression', '(unparseable)')}")
        elif e["type"] in ("select", "multi_select", "status"):
            lines.append(f"      options: {e.get('options', [])}")
            for g in e.get("groups") or []:
                lines.append(f"      group '{g['name']}': {g['options']}")
    return lines