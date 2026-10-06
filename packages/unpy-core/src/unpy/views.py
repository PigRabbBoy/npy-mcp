"""Database view creation/readback shared by unpy-mcp and unpy-cli (issue #37).

Pure translation: view spec (property NAMES, human operators) → Notion's
`collection_view` record shapes (query2/filter, format group-by, visible
properties), resolved against the collection's schema. ValueError on
invalid input BEFORE any write — the caller must validate before writing.
"""

from __future__ import annotations

VIEW_TYPES = ("table", "board", "list", "gallery", "calendar", "timeline")

# operator → per-type Notion filter operator. Values are translated per
# property type (see _translate_condition).
OPERATORS = (
    "is", "is_not", "contains", "does_not_contain", "starts_with",
    "ends_with", "is_empty", "is_not_empty", "before", "after",
    "on_or_before", "on_or_after", "is_within", "greater_than",
    "less_than", "greater_than_or_equal_to", "less_than_or_equal_to",
)

_RELATIVE_DATE_VALUES = {
    "today", "yesterday", "tomorrow", "one_week_ago", "one_week_from_now",
    "one_month_ago", "one_month_from_now", "one_year_ago", "one_year_from_now",
    "now", "this_week",
}


def _slug(name: str) -> str:
    from unpy.utils import slugify

    return slugify(name or "").lower()


def schema_maps(collection) -> tuple[dict, dict]:
    """Return (raw_schema {pid: prop}, name→pid map using displayed names)."""
    raw = collection.get("schema") or {}
    name_to_pid = {}
    for pid, p in raw.items():
        if p is None or p.get("alive") is False:
            continue
        name_to_pid[p.get("name", "")] = pid
    return raw, name_to_pid


def resolve_prop(raw_schema: dict, name_to_pid: dict, name: str, what: str = "property") -> tuple[str, dict]:
    """Resolve a property by name (case-insensitive), id or title."""
    ident = (name or "").strip()
    if not ident:
        raise ValueError(f"{what} name is required")
    if ident in raw_schema:
        p = raw_schema[ident]
        if p is None or p.get("alive") is False:
            raise ValueError(f"{what} '{name}' is deleted")
        return ident, p
    pid = name_to_pid.get(ident) or name_to_pid.get(_slug(ident))
    if pid is None:
        # case-insensitive / slug match
        want = _slug(ident)
        for n, cand in name_to_pid.items():
            if _slug(n) == want:
                pid = cand
                break
    if pid is None:
        available = ", ".join(sorted(k for k in name_to_pid if k))
        raise ValueError(
            f"{what} '{name}' not found in this database (available: {available})"
        )
    return pid, raw_schema[pid]


def _option_id(prop: dict, value: str) -> str:
    """Match an option value case-insensitively; ids pass through."""
    for o in prop.get("options") or []:
        if (o.get("value") or "").lower() == (value or "").strip().lower():
            return o.get("id", "")
    raise ValueError(
        f"option '{value}' not found in column "
        f"'{prop.get('name', '?')}' (available: "
        + ", ".join(o.get("value", "") for o in prop.get("options") or [])
        + ")"
    )


def _status_group_options(prop: dict, group_name: str) -> list[str]:
    for g in prop.get("groups") or []:
        if (g.get("name") or "").strip().lower() == (group_name or "").strip().lower():
            return g.get("options") or []
    raise ValueError(
        f"status group '{group_name}' not found in column "
        f"'{prop.get('name', '?')}' (available: "
        + ", ".join(g.get("name", "") for g in prop.get("groups") or [])
        + ")"
    )


def _translate_date_value(operator: str, value):
    if isinstance(value, dict):
        return value  # raw escape hatch
    if value in _RELATIVE_DATE_VALUES:
        return {"type": "relative", "value": value}
    # YYYY-MM-DD exact date
    s = str(value).strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return {"type": "exact", "value": s}
    raise ValueError(
        f"unsupported date value '{value}' (use YYYY-MM-DD, "
        "today/one_week_ago/one_month_ago…, or a raw dict)"
    )


def translate_condition(spec: dict, raw_schema: dict, name_to_pid: dict) -> dict:
    """One spec condition → Notion query2 condition.

    Accepts the shorthand {"property": "Status", "is": "Done"} too, and the
    escape hatch {"property": "Due", "raw": {...notion filter...}}.
    """
    if not isinstance(spec, dict):
        raise ValueError("each filter condition must be an object")
    if "raw" in spec:
        pid, _prop = resolve_prop(
            raw_schema, name_to_pid, spec.get("property", ""), "filter property"
        )
        raw = spec["raw"]
        if not isinstance(raw, dict):
            raise ValueError("'raw' filter must be an object")
        return {"property": pid, "filter": raw}
    pname = spec.get("property", "")
    pid, prop = resolve_prop(raw_schema, name_to_pid, pname, "filter property")
    ptype = prop.get("type", "text")
    operator = spec.get("operator")
    if not operator and "is" in spec and isinstance(spec.get("is"), (str, bool, list)) and "value" not in spec:
        # shorthand: {"property": "Status", "is": "Done"} → operator "is"
        operator = "is"
    if not operator:
        raise ValueError(
            f"condition on '{pname}' needs an 'operator' "
            f"(available: {', '.join(OPERATORS)}) or a 'raw' object"
        )
    if operator not in OPERATORS:
        raise ValueError(
            f"unknown operator '{operator}' (available: {', '.join(OPERATORS)})"
        )
    if operator in ("is_empty", "is_not_empty"):
        return {"property": pid, "filter": {"operator": _notion_operator(operator, ptype)}}
    value = spec.get("value")
    if value is None:
        value = spec.get("is")
    notion_op = _notion_operator(operator, ptype)
    return {
        "property": pid,
        "filter": {"operator": notion_op, "value": _translate_value(notion_op, ptype, prop, value)},
    }


def _notion_operator(operator: str, ptype: str) -> str:
    """Human operator × property type → Notion filter operator (issue #37 table)."""
    if operator == "is_empty":
        return "is_empty"
    if operator == "is_not_empty":
        return "is_not_empty"
    table = {
        "select": {"is": "enum_is", "is_not": "enum_is_not",
                   "contains": "enum_is", "does_not_contain": "enum_is_not"},
        "multi_select": {"is": "enum_contains", "is_not": "enum_does_not_contain",
                         "contains": "enum_contains",
                         "does_not_contain": "enum_does_not_contain"},
        "status": {"is": "status_is", "is_not": "status_is_not",
                   "contains": "status_is", "does_not_contain": "status_is_not"},
        "person": {"is": "person_contains", "is_not": "person_does_not_contain",
                   "contains": "person_contains",
                   "does_not_contain": "person_does_not_contain"},
        "created_by": {"is": "person_contains", "is_not": "person_does_not_contain",
                       "contains": "person_contains",
                       "does_not_contain": "person_does_not_contain"},
        "last_edited_by": {"is": "person_contains", "is_not": "person_does_not_contain",
                           "contains": "person_contains",
                           "does_not_contain": "person_does_not_contain"},
        "checkbox": {"is": "checkbox_is", "is_not": "checkbox_is_not"},
        "title": {"is": "string_is", "is_not": "string_does_not_equal",
                  "contains": "string_contains",
                  "does_not_contain": "string_does_not_contain",
                  "starts_with": "string_starts_with", "ends_with": "string_ends_with"},
        "text": {"is": "string_is", "is_not": "string_does_not_equal",
                 "contains": "string_contains",
                 "does_not_contain": "string_does_not_contain",
                 "starts_with": "string_starts_with", "ends_with": "string_ends_with"},
        "url": {"is": "string_is", "is_not": "string_does_not_equal",
                "contains": "string_contains",
                "does_not_contain": "string_does_not_contain",
                "starts_with": "string_starts_with", "ends_with": "string_ends_with"},
        "email": {"is": "string_is", "is_not": "string_does_not_equal",
                  "contains": "string_contains",
                  "does_not_contain": "string_does_not_contain",
                  "starts_with": "string_starts_with", "ends_with": "string_ends_with"},
        "phone_number": {"is": "string_is", "is_not": "string_does_not_equal",
                         "contains": "string_contains",
                         "does_not_contain": "string_does_not_contain",
                         "starts_with": "string_starts_with", "ends_with": "string_ends_with"},
        "relation": {"is": "relation_contains", "is_not": "relation_does_not_contain",
                     "contains": "relation_contains",
                     "does_not_contain": "relation_does_not_contain"},
        "date": {"is": "date_is", "is_not": "date_is_not", "before": "date_is_before",
                 "after": "date_is_after", "on_or_before": "date_is_on_or_before",
                 "on_or_after": "date_is_on_or_after", "is_within": "date_is_within"},
        "created_time": {"is": "date_is", "is_not": "date_is_not",
                         "before": "date_is_before", "after": "date_is_after",
                         "on_or_before": "date_is_on_or_before",
                         "on_or_after": "date_is_on_or_after",
                         "is_within": "date_is_within"},
        "last_edited_time": {"is": "date_is", "is_not": "date_is_not",
                             "before": "date_is_before", "after": "date_is_after",
                             "on_or_before": "date_is_on_or_before",
                             "on_or_after": "date_is_on_or_after",
                             "is_within": "date_is_within"},
        "number": {"is": "number_is", "is_not": "number_is_not",
                   "greater_than": "number_is_greater_than",
                   "less_than": "number_is_less_than",
                   "greater_than_or_equal_to": "number_is_greater_than_or_equal_to",
                   "less_than_or_equal_to": "number_is_less_than_or_equal_to"},
    }
    by_type = table.get(ptype, table["text"])
    if operator not in by_type:
        raise ValueError(
            f"operator '{operator}' is not valid for a {ptype} column "
            f"(available: {', '.join(sorted(by_type))})"
        )
    return by_type[operator]


def _translate_value(notion_op: str, ptype: str, prop: dict, value):
    if value is None:
        raise ValueError(f"operator '{notion_op}' needs a 'value'")
    if ptype in ("select", "status"):
        if isinstance(value, dict) and "group" in value:
            # status group filter — "is any of this group's options"
            opts = _status_group_options(prop, value["group"])
            vals = [{"type": "is_option", "value": _option_value(prop, o)} for o in opts]
            return vals[0] if len(vals) == 1 else vals
        if isinstance(value, list):
            return [
                {"type": "is_option" if ptype == "status" else "exact",
                 "value": _option_value(prop, v)}
                for v in value
            ]
        return {
            "type": "is_option" if ptype == "status" else "exact",
            "value": _option_value(prop, value),
        }
    if ptype == "multi_select":
        values = value if isinstance(value, list) else [value]
        return [{"type": "exact", "value": _option_value(prop, v)} for v in values]
    if ptype in ("person", "created_by", "last_edited_by"):
        if value == "me":
            return {"type": "relative", "value": "me"}
        from unpy.utils import extract_id

        try:
            uid = extract_id(value)
        except Exception:
            uid = value
        return {"type": "exact", "value": uid}
    if ptype == "checkbox":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
        raise ValueError(f"checkbox filter value must be true/false, got '{value}'")
    if ptype == "relation":
        from unpy.utils import extract_id

        try:
            return {"type": "exact", "value": extract_id(value)}
        except Exception:
            return {"type": "exact", "value": value}
    if ptype in ("date", "created_time", "last_edited_time"):
        if isinstance(value, list):
            return [_translate_date_value(notion_op, v) for v in value]
        return _translate_date_value(notion_op, value)
    # text-ish and number — pass through
    return value


def _option_value(prop: dict, nameish) -> str:
    if isinstance(nameish, dict):
        return nameish  # already-shaped
    # match option by value; accept ids too
    lowered = str(nameish).strip().lower()
    for o in prop.get("options") or []:
        if (o.get("value") or "").lower() == lowered:
            return o.get("value", str(nameish))
        if o.get("id") == str(nameish):
            return o.get("value", str(nameish))
    raise ValueError(
        f"option '{nameish}' not found in column "
        f"'{prop.get('name', '?')}' (available: "
        + ", ".join(o.get("value", "") for o in prop.get("options") or [])
        + ")"
    )


def translate_filter(spec, raw_schema: dict, name_to_pid: dict) -> dict:
    """Spec filter (hand-writable JSON) → Notion query2.filter tree."""
    if isinstance(spec, list):
        spec = {"and": spec} if spec else {}
    if not isinstance(spec, dict):
        raise ValueError("filter must be an object or a list of conditions")
    if "raw" in spec:
        raw = spec["raw"]
        if not isinstance(raw, dict):
            raise ValueError("filter 'raw' must be an object")
        if "property" in spec:
            # escape hatch on one property: keep the property binding
            pid, _prop = resolve_prop(
                raw_schema, name_to_pid, spec.get("property", ""), "filter property"
            )
            return {"property": pid, "filter": raw}
        return raw
    if "and" in spec or "or" in spec:
        op = "and" if "and" in spec else "or"
        children = spec[op] or []
        if not isinstance(children, list):
            raise ValueError(f"filter '{op}' must be a list")
        filters = [
            translate_condition(c, raw_schema, name_to_pid)
            if isinstance(c, dict) and not ("and" in c or "or" in c)
            else translate_filter(c, raw_schema, name_to_pid)
            for c in children
        ]
        if not filters:
            return {}
        return {"operator": op, "filters": filters}
    # a single condition object
    return {
        "operator": "and",
        "filters": [translate_condition(spec, raw_schema, name_to_pid)],
    }


def translate_sort(spec, raw_schema: dict, name_to_pid: dict) -> list:
    """Spec sort → query2.sort. Accepts [{"property","direction"}] or the
    shorthand "Name" / "-Due" (leading '-' = descending)."""
    if isinstance(spec, str):
        text = spec.strip()
        if not text:
            return []
        try:
            parsed = json_loads(text)
        except Exception:
            parsed = [s.strip() for s in text.split(",") if s.strip()]
        spec = parsed
    if not isinstance(spec, list):
        raise ValueError("sort must be a JSON list")
    out = []
    for s in spec:
        if isinstance(s, str):
            direction = "descending" if s.startswith("-") else "ascending"
            pname = s.lstrip("+-")
        elif isinstance(s, dict):
            pname = s.get("property", "")
            direction = s.get("direction", "ascending")
        else:
            raise ValueError("each sort entry must be a name or an object")
        pid, _prop = resolve_prop(raw_schema, name_to_pid, pname, "sort property")
        if direction not in ("ascending", "descending", "manual"):
            raise ValueError(
                f"sort direction '{direction}' must be ascending/descending/manual"
            )
        out.append({"property": pid, "direction": direction})
    return out


def visible_properties_entries(spec, raw_schema: dict, name_to_pid: dict,
                               view_type: str = "table") -> list[dict]:
    """Spec property list → format.<type>_properties entries.

    Each entry is a name or {"property", "width"?, "visible"?}. Every
    property NOT listed is appended hidden, so hidden columns keep their
    spot. A table view always keeps the title column visible.
    Raises ValueError when a name is unknown or the title column is hidden
    on a table view (before any write).
    """
    if isinstance(spec, str):
        spec = json_loads(spec) if spec.strip() else []
    if not isinstance(spec, list):
        raise ValueError("properties must be a JSON list")
    title_pid = next(
        (pid for pid, p in raw_schema.items()
         if p and p.get("type") == "title"),
        None,
    )
    entries: list[dict] = []
    seen: set[str] = set()
    title_visible = False
    for item in spec:
        if isinstance(item, str):
            item = {"property": item}
        if not isinstance(item, dict):
            raise ValueError("each property entry must be a name or an object")
        pid, _prop = resolve_prop(
            raw_schema, name_to_pid, item.get("property", ""), "property"
        )
        if pid in seen:
            raise ValueError(f"property '{item.get('property')}' listed twice")
        seen.add(pid)
        visible = item.get("visible")
        if visible is None:
            visible = True
        if pid == title_pid and visible:
            title_visible = True
        entry = {"property": pid, "visible": bool(visible)}
        if item.get("width") is not None:
            entry["width"] = item["width"]
        entries.append(entry)
    # append unlisted properties hidden (keeps their spot in the schema)
    for pid, p in raw_schema.items():
        if p is None or p.get("alive") is False or pid in seen:
            continue
        entries.append({"property": pid, "visible": False})
    if view_type == "table" and title_pid and not title_visible:
        # the title column must stay visible on tables — force it
        for e in entries:
            if e["property"] == title_pid:
                e["visible"] = True
    return entries


def group_by_format(view_type: str, prop: dict, pid: str) -> dict:
    """Group-by spec → the format key + value for the view type (issue #37).

    Boards write "board_columns_by"; every other type writes
    "collection_group_by".
    """
    if view_type == "board":
        return {"board_columns_by": {
            "type": prop.get("type", "select"),
            "property": pid,
            "groupBy": "option",
            "sort": {"type": "ascending"},
            "hideEmptyGroups": False,
            "disableBoardColorColumns": False,
        }}
    return {"collection_group_by": {
        "type": prop.get("type", "select"),
        "property": pid,
        "sort": {"type": "manual"},
        "hideEmptyGroups": True,
    }}


def json_loads(text: str):
    import json

    return json.loads(text)


def build_view_payload(
    client,
    collection,
    view_type: str = "table",
    name: str = "",
    filter_spec=None,
    sort_spec=None,
    group_by: str = "",
    properties=None,
    date_property: str = "",
    existing_view=None,
) -> dict:
    """Translate a view spec into (patch dict) for create or in-place update.

    Returns a dict: {"query2": {...}, "format": {...}, "name": str,
    "type": str, "view_id": str|None, "warnings": [str]}.

    All name → id resolution raises ValueError BEFORE any write. When
    existing_view is given, patches are computed for in-place update
    (idempotent re-run).
    """
    if view_type not in VIEW_TYPES:
        raise ValueError(
            f"unknown view type '{view_type}' (available: {', '.join(VIEW_TYPES)})"
        )
    raw_schema, name_to_pid = schema_maps(collection)
    query2: dict = {}
    fmt: dict = {}
    warnings: list[str] = []

    if filter_spec not in (None, "", {}):
        try:
            parsed = filter_spec if isinstance(filter_spec, (dict, list)) else json_loads(filter_spec)
        except Exception as exc:
            raise ValueError(f"filter is not valid JSON: {exc}") from exc
        f = translate_filter(parsed, raw_schema, name_to_pid)
        if f:
            query2["filter"] = f
    if sort_spec not in (None, "", []):
        try:
            parsed = sort_spec if isinstance(sort_spec, list) else json_loads(sort_spec)
        except Exception as exc:
            raise ValueError(f"sort is not valid JSON: {exc}") from exc
        s = translate_sort(parsed, raw_schema, name_to_pid)
        if s:
            query2["sort"] = s

    if group_by:
        pid, prop = resolve_prop(raw_schema, name_to_pid, group_by, "group-by property")
        if group_by and prop.get("type") not in ("select", "multi_select", "status", "person", "checkbox", "relation"):
            warnings.append(
                f"grouping by '{prop.get('type')}' column — Notion groups by "
                "select/status/person/checkbox/relation columns"
            )
        fmt.update(group_by_format(view_type, prop, pid))
    elif view_type == "board" and existing_view in (None, False):
        # UI behaviour: a new board defaults to the first status, then select
        for want in ("status", "select"):
            pid = next(
                (p for p, q in raw_schema.items()
                 if q and q.get("type") == want),
                None,
            )
            if pid:
                fmt.update(group_by_format("board", raw_schema[pid], pid))
                break

    if view_type in ("calendar", "timeline"):
        ident = date_property or next(
            (p.get("name") for p in raw_schema.values()
             if p and p.get("type") == "date"),
            None,
        )
        if not ident:
            raise ValueError(
                f"a {view_type} view needs a date column (pass --date-property)"
            )
        pid, _prop = resolve_prop(raw_schema, name_to_pid, ident, "date property")
        query2[("calendar_by" if view_type == "calendar" else "timeline_by")] = pid

    if properties not in (None, "", []):
        entries = visible_properties_entries(
            properties, raw_schema, name_to_pid, view_type
        )
        fmt[f"{view_type}_properties"] = entries

    payload: dict = {
        "type": view_type,
        "query2": query2,
        "format": fmt,
        "warnings": warnings,
        "view_id": getattr(existing_view, "id", None) if existing_view is not None else None,
    }
    if name:
        payload["name"] = name
    return payload


def find_view_by_name(collection, name: str):
    """First live view with this name (idempotency), or None."""
    want = (name or "").strip().lower()
    block = getattr(collection, "parent", None)
    view_ids = block.get("view_ids") or [] if block is not None else []
    for vid in view_ids:
        data = collection._client._store._values.get("collection_view", {}).get(vid) or {}
        if data.get("alive") is False:
            continue
        if (data.get("name") or "").strip().lower() == want and want:
            from unpy.collection import CollectionView, COLLECTION_VIEW_TYPES

            cls = COLLECTION_VIEW_TYPES.get(data.get("type", ""), CollectionView)
            return cls(collection._client, vid, collection=collection)
    return None


def list_views(collection, client) -> list[dict]:
    """Readback: every live view with property NAMES (issue #31-style)."""
    raw_schema, name_to_pid = schema_maps(collection)
    def _name_of(pid: str) -> str:
        if pid in raw_schema:
            return raw_schema[pid].get("name", pid)
        return pid

    block = getattr(collection, "parent", None)
    view_ids = block.get("view_ids") or [] if block is not None else []
    out = []
    store = client._store._values
    for vid in view_ids:
        data = store.get("collection_view", {}).get(vid) or {}
        if data.get("alive") is False:
            continue
        fmt = data.get("format") or {}
        q2 = data.get("query2") or {}
        props = fmt.get(f"{data.get('type', 'table')}_properties") or []
        visible = [
            _name_of(p.get("property", ""))
            for p in props if p.get("visible")
        ]
        entry = {
            "id": vid,
            "name": data.get("name", ""),
            "type": data.get("type", ""),
            "filter": _names_in_filter(q2.get("filter"), _name_of),
            "sort": [
                {"property": _name_of(s.get("property", "")),
                 "direction": s.get("direction", "ascending")}
                for s in q2.get("sort") or []
            ],
            "visible_properties": visible,
        }
        g = fmt.get("board_columns_by") or fmt.get("collection_group_by")
        if g:
            entry["group_by"] = _name_of(g.get("property", ""))
        if q2.get("calendar_by"):
            entry["date_property"] = _name_of(q2["calendar_by"])
        if q2.get("timeline_by"):
            entry["timeline_by"] = _name_of(q2["timeline_by"])
        out.append(entry)
    return out


def _names_in_filter(node, name_of):
    if not node:
        return node
    if isinstance(node, dict):
        if "property" in node and "filter" in node:
            return {**node, "property": name_of(node.get("property", ""))}
        return {
            k: (_names_in_filter(v, name_of) if isinstance(v, (dict, list)) else v)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_names_in_filter(n, name_of) for n in node]
    return node