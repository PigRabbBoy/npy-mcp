"""Full database schema description, shared by the CLI and the MCP server.

``describe_schema(collection)`` turns a collection's raw schema into one
JSON-ready dict per live property: relation targets and synced properties,
rollup configs, formula expressions and select/status options, with
property ids resolved to names. ``full_schema_markdown(entries)`` renders
the same entries as the ``## Full schema`` section.

``unpy get-database --full-schema`` and the MCP tool
``get_database(full_schema=true)`` both call these, so the two outputs
can't drift apart (issue #31).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, NamedTuple, TypeGuard

SchemaLoader = Callable[[str], dict]

_OPTION_TYPES = ("select", "multi_select", "status")


class FormulaRef(NamedTuple):
    """A '‣' segment of stored formula2 code.

    kind is the annotation type ("fpp" = formula property pointer); meta is
    its payload, for fpp {"property": id, "collection": pointer} or the
    name-only {"name": ...} that encode_expr writes.
    """

    kind: str
    meta: Any


def formula_parts(prop: dict) -> list[str | FormulaRef]:
    """Split a formula's stored formula2.code into literals and references.

    Literal text comes back as str, '‣' segments as FormulaRef. The
    formula interpreter (unpy_mcp.formula_eval.build_expr) and
    describe_schema both read stored formulas through this one function.
    """
    parts: list[str | FormulaRef] = []
    code = (prop.get("formula2") or {}).get("code") or []
    for seg in code:
        if isinstance(seg, list) and seg:
            if seg[0] == "‣" and len(seg) > 1 and seg[1]:
                try:
                    annotation = seg[1][0]
                    parts.append(FormulaRef(annotation[0], annotation[1]))
                    continue
                except (IndexError, KeyError, TypeError):
                    pass
            parts.append(str(seg[0]))
        elif isinstance(seg, str):
            parts.append(seg)
    return parts


def _is_live(prop) -> TypeGuard[dict]:
    """Deleted properties arrive as None or carry alive: false."""
    return isinstance(prop, dict) and prop.get("alive") is not False


def _pointer_id(prop: dict) -> str:
    return prop.get("collection_id") or (prop.get("collection_pointer") or {}).get("id") or ""


class _Schemas:
    """Schemas by collection id: this database's own, plus each foreign one
    loaded at most once per call. A load that fails counts as empty."""

    def __init__(self, own_id: str, own_schema: dict, load: SchemaLoader):
        self.own_id = own_id
        self.own = own_schema
        self._load = load
        self._cache: dict[str, dict] = {}

    def get(self, collection_id: str) -> dict:
        if not collection_id or collection_id == self.own_id:
            return self.own
        if collection_id not in self._cache:
            try:
                schema = self._load(collection_id)
            except Exception:  # noqa: BLE001 — unreadable target: names fall back to None
                schema = None
            self._cache[collection_id] = schema if isinstance(schema, dict) else {}
        return self._cache[collection_id]

    def name(self, collection_id: str, prop_id: str | None) -> str | None:
        if not prop_id:
            return None
        prop = self.get(collection_id).get(prop_id)
        return prop.get("name") if _is_live(prop) else None


def _client_loader(collection) -> SchemaLoader:
    client = getattr(collection, "_client", None)

    def load(collection_id: str) -> dict:
        if client is None:
            return {}
        other = client.get_collection(collection_id)
        return (other.get("schema") or {}) if other is not None else {}

    return load


def _prop_call(name: str) -> str:
    """prop("Name") as Notion's formula editor writes it."""
    return f"prop({json.dumps(name, ensure_ascii=False)})"


def _option_fields(prop: dict) -> dict:
    options = [o for o in prop.get("options") or [] if isinstance(o, dict)]
    fields: dict[str, Any] = {"options": [o.get("value", "") for o in options]}
    groups = prop.get("groups")
    if prop.get("type") == "status" and groups:
        value_by_id = {o.get("id"): o.get("value", "") for o in options}
        fields["groups"] = [
            {
                "name": g.get("name", ""),
                "options": [value_by_id[i] for i in g.get("optionIds") or [] if i in value_by_id],
            }
            for g in groups
            if isinstance(g, dict)
        ]
    return fields


def _relation_fields(prop: dict, schemas: _Schemas) -> dict:
    """A two-way relation names its synced property's id on the target in
    "property"; a one-way relation has none."""
    target = _pointer_id(prop)
    reverse_id = prop.get("property") or None
    reverse = schemas.name(target, reverse_id) if target else None
    return {
        "target": target or None,
        "single": prop.get("limit") == 1,
        "reverse": reverse,
        "reverse_id": reverse_id,
    }


def _rollup_fields(prop: dict, schemas: _Schemas) -> dict:
    relation_id = prop.get("relation_property") or None
    target_prop_id = prop.get("target_property") or None
    relation = schemas.own.get(relation_id) if relation_id else None
    # rollups usually carry no pointer of their own: the target collection
    # is the one their relation points at
    target = _pointer_id(prop) or (_pointer_id(relation) if _is_live(relation) else "")
    return {
        "relation_property": schemas.name(schemas.own_id, relation_id),
        "relation_property_id": relation_id,
        "target_property": schemas.name(target, target_prop_id) if target else None,
        "target_property_id": target_prop_id,
        # an absent aggregation is how Notion stores "show original" (#14)
        "aggregation": prop.get("aggregation") or "show_original",
    }


def _formula_fields(prop: dict, schemas: _Schemas) -> dict:
    shown: list[str] = []
    raw: list[str] = []
    refs: list[dict] = []
    for part in formula_parts(prop):
        if not isinstance(part, FormulaRef):
            shown.append(part)
            raw.append(part)
            continue
        placeholder = "{" + str(len(refs)) + "}"
        meta = part.meta if isinstance(part.meta, dict) else {}
        collection_id = (meta.get("collection") or {}).get("id") or None
        name = None
        if part.kind == "fpp":
            # name-only metas (written by encode_expr) already carry the name
            name = schemas.name(collection_id or "", meta.get("property")) or meta.get("name")
        shown.append(_prop_call(name) if name else placeholder)
        raw.append(placeholder)
        refs.append(
            {"property": meta.get("property"), "collection_id": collection_id, "name": name}
        )
    return {"expression": "".join(shown), "raw_expression": "".join(raw), "refs": refs}


def _describe_prop(prop_id: str, prop: dict, schemas: _Schemas) -> dict:
    ptype = prop.get("type", "?")
    entry: dict[str, Any] = {"id": prop_id, "name": prop.get("name", "?"), "type": ptype}
    if ptype in _OPTION_TYPES:
        entry.update(_option_fields(prop))
    elif ptype == "relation":
        entry.update(_relation_fields(prop, schemas))
    elif ptype == "rollup":
        entry.update(_rollup_fields(prop, schemas))
    elif ptype == "formula":
        entry.update(_formula_fields(prop, schemas))
    return entry


def describe_schema(collection, load_schema: SchemaLoader | None = None) -> list[dict]:
    """Describe every live property of a collection, in schema order.

    Each entry has id, name and type, plus per type:
      select / multi_select / status: options (names, in order); status
          also groups [{name, options}]
      relation: target (collection id), single, reverse (synced property
          name on the target, None if one-way), reverse_id
      rollup: relation_property, target_property (names),
          relation_property_id, target_property_id, aggregation
      formula: expression (refs as prop("Name")), raw_expression (refs as
          {N}), refs [{property, collection_id, name}]

    load_schema(collection_id) returns another collection's raw schema; it
    defaults to the collection's own client. Names that can't be resolved
    come back as None while their ids are kept.
    """
    own_schema = collection.get("schema") or {}
    schemas = _Schemas(
        getattr(collection, "id", "") or "",
        own_schema,
        load_schema or _client_loader(collection),
    )
    return [
        _describe_prop(prop_id, prop, schemas)
        for prop_id, prop in own_schema.items()
        if _is_live(prop)
    ]


def _named(name: str | None, prop_id: str | None) -> str:
    return f"{name or '?'} [id: {prop_id or '?'}]"


def full_schema_markdown(entries: list[dict]) -> list[str]:
    """Render describe_schema() entries as the '## Full schema' section."""
    lines = ["## Full schema"]
    for e in entries:
        ptype = e["type"]
        lines.append(f"  - **{e['name']}** ({ptype}) [id: {e['id']}]")
        if ptype == "relation":
            lines.append(f"      target: {e['target'] or '?'}")
            lines.append(f"      single: {'yes' if e['single'] else 'no'}")
            if e["reverse_id"]:
                lines.append(f"      reverse_name: {_named(e['reverse'], e['reverse_id'])}")
        elif ptype == "rollup":
            lines.append(
                f"      relation_property: "
                f"{_named(e['relation_property'], e['relation_property_id'])}"
            )
            lines.append(
                f"      target_property: {_named(e['target_property'], e['target_property_id'])}"
            )
            lines.append(f"      aggregation: {e['aggregation']}")
        elif ptype == "formula":
            lines.append(f"      expression: {e['expression']}")
        elif ptype in _OPTION_TYPES:
            lines.append(f"      options: {e['options']}")
    return lines
