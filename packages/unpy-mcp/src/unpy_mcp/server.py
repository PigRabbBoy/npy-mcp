"""npy-mcp server — Notion MCP server (stdio + HTTP).

Exposes 6 read tools (+ 9 write tools when NOTION_ALLOW_WRITE=1).
Uses MCP Python SDK v2 (MCPServer + decorator pattern).

Per-request token: HTTP clients can send X-Notion-Token header to use
their own Notion session. Falls back to NOTION_TOKEN_V2 env var.
"""

from __future__ import annotations

import collections
import contextvars
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Annotated

# Ensure unpy-core is importable when running from source without install
_CORE_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "unpy-core", "src")
if os.path.isdir(_CORE_SRC) and os.path.abspath(_CORE_SRC) not in sys.path:
    sys.path.insert(0, os.path.abspath(_CORE_SRC))

from mcp.server import MCPServer

from unpy import NotionClient
from unpy.auth import resolve_auth
from . import formula_eval as _fev

mcp = MCPServer("unpy-mcp")

# Context variable for per-request Notion token (set by HTTP middleware)
# When None, falls back to env var NOTION_TOKEN_V2
notion_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "notion_token", default=None
)

# Cache of NotionClient keyed by a hash of the token (avoids re-calling
# loadUserContent on every request). Bounded and keyed by digest so a caller
# firing many distinct tokens cannot grow it without limit or leave raw
# tokens sitting in a process-wide dict.
_CLIENT_CACHE_MAX = 32
_client_cache: "collections.OrderedDict[str, NotionClient]" = collections.OrderedDict()


def _client_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _resolve_local_path(file_path: str) -> str:
    """Resolve a local path and confine it to NOTION_MCP_FILE_ROOT.

    The file-reading write tools (import_csv, create_media) would otherwise
    open any path the server process can read and push its contents into
    Notion — an exfiltration path for a remote Bearer holder over HTTP, or
    for prompt injection over stdio. Every local path must resolve inside the
    allowed root. Root is NOTION_MCP_FILE_ROOT when set, else the current
    working directory; set NOTION_MCP_FILE_ROOT=/ to lift the restriction.
    """
    root = Path(os.environ.get("NOTION_MCP_FILE_ROOT") or os.getcwd()).expanduser().resolve()
    resolved = Path(file_path).expanduser().resolve()
    if not resolved.is_relative_to(root):
        raise PermissionError(
            f"Refusing to read '{file_path}': outside allowed file root '{root}'. "
            "Set NOTION_MCP_FILE_ROOT to another directory (or '/' to allow all)."
        )
    return str(resolved)


def _get_client() -> NotionClient:
    """Get or create a NotionClient for the current request's token.

    Token resolution (first non-empty wins):
    1. Per-request token from contextvar (set by HTTP middleware via X-Notion-Token header)
    2. NOTION_TOKEN_V2 / NOTION_TOKEN env var
    3. ~/.config/unpy-mcp/token config file

    Raises RuntimeError with a helpful message if the token is invalid or expired,
    instead of letting the HTTP 401 crash the MCP connection.
    """
    token = notion_token_var.get()
    if token is None:
        cfg = resolve_auth()
        token = cfg["token"]
    key = _client_cache_key(token)
    # Cache client per token to avoid re-init on every request
    cached = _client_cache.get(key)
    if cached is not None:
        _client_cache.move_to_end(key)
        return cached
    try:
        client = NotionClient(token_v2=token)
    except Exception as exc:
        # Invalidate cache entry if it was cached before but is now failing
        _client_cache.pop(key, None)
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg:
            raise RuntimeError(
                "Notion token is invalid or expired. Extract a fresh token_v2 "
                "from browser DevTools (Application → Cookies → token_v2) and "
                "update NOTION_TOKEN_V2."
            ) from exc
        raise RuntimeError(f"Failed to connect to Notion: {exc}") from exc
    # Try to bind space from config/env
    cfg = resolve_auth()
    space_id = cfg.get("space_id")
    if space_id:
        try:
            client.current_space = client.get_space(space_id)
        except Exception:
            pass
    _client_cache[key] = client
    _client_cache.move_to_end(key)
    while len(_client_cache) > _CLIENT_CACHE_MAX:
        _client_cache.popitem(last=False)
    return client


def _format_icon(icon: str) -> str:
    """Format a page icon for inline display.

    Emoji icons are kept inline; URL/attachment/path icons are dropped
    (they render as noise in text output and waste tokens).
    """
    if not icon:
        return ""
    # Emoji icons are short and don't start with / http or attachment:
    if icon.startswith(("/", "http", "attachment:")):
        return ""
    return icon


def _block_summary(block) -> dict:
    """Compact block dict for tool output."""
    url = ""
    try:
        url = block.get_browseable_url()
    except Exception:
        pass
    icon = block.get("format.page_icon") or ""
    btype = block.get("type", "") or ""
    # Strip icon from title to avoid noise (icon is separate field)
    title = block.title_plaintext if hasattr(block, "title_plaintext") else None
    if title and icon and title.startswith(icon):
        title = title[len(icon):].strip()
    # For collection_view/collection_view_page, use DB name if title is empty
    if not title and btype in ("collection_view", "collection_view_page"):
        title = _get_inline_db_name(block) or ""
    return {
        "id": block.id,
        "type": btype,
        "title": title,
        "url": url,
        "icon": icon,
    }


def _block_tree(client: NotionClient, block, depth: int) -> dict:
    """Recursive block tree."""
    d = _block_summary(block)
    if depth == 0:
        d["children"] = []
        return d
    children = getattr(block, "children", None)
    if children is None:
        d["children"] = []
        return d
    d["children"] = [
        _block_tree(client, c, depth - 1 if depth > 0 else -1)
        for c in children
    ]
    return d


def _render_property(value) -> str:
    """Render a Notion property value to a readable string.

    Shared implementation lives in unpy-core (unpy.render) so the CLI and
    the MCP server never drift apart.
    """
    from unpy.render import render_property

    return render_property(value)


# ---------------------------------------------------------------------------
# Formula / rollup evaluation
#
# Notion does not return computed formula/rollup values over the internal API
# — the web client evaluates them in JS from the definitions stored in the
# collection schema. The schema DOES contain those definitions:
#   - rollup: {relation_property, target_property, collection_pointer}
#   - formula: {formula2: {code: [[literal|'‣' fpp-ref], ...]}}
# We evaluate the common patterns here so MCP reads show real values instead
# of '(computed)'. Unsupported expressions fall back to None.
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, dict] = {}


def _load_schema_cached(client, col_id: str) -> dict:
    if not col_id:
        return {}
    if col_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[col_id]
    try:
        col = client.get_collection(col_id)
        schema = (col.get("schema") or {}) if col else {}
    except Exception:
        schema = {}
    _SCHEMA_CACHE[col_id] = schema
    return schema


_BLOCK_MARKER = "\x00block:"


def _get_block_data(client, block_id: str) -> dict:
    """Fetch raw block data from store, lazily fetching over the wire if missing.

    Related blocks often appear in the local store as STUBS (id/type/parent
    but no properties) after queryCollection — treat those as missing and
    force a real fetch.
    """
    def _fetch():
        try:
            blk = client.get_block(block_id)
            if blk is not None:
                return client._store._get("block", block_id)
        except Exception:
            pass
        return None

    data = client._store._get("block", block_id)
    if not isinstance(data, dict):
        data = _fetch() or {}
    # Stub detection: page-type block with missing/empty properties
    if isinstance(data, dict) and data.get("type") == "page":
        props = data.get("properties")
        if not props:
            data = _fetch() or {}
    return data if isinstance(data, dict) else {}


def _relation_ids(block_data: dict, rel_prop_id: str) -> list[str]:
    val = (block_data.get("properties") or {}).get(rel_prop_id) or []
    ids = []
    for item in val:
        try:
            if item[0] == "‣" and item[1]:
                ids.append(item[1][0][1])
        except Exception:
            continue
    return ids


def _read_prop_display(client, block_data: dict, prop_id: str, schema: dict):
    """Read one property off raw block data as a display-friendly value."""
    val = (block_data.get("properties") or {}).get(prop_id)
    if not val:
        return ""
    ptype = "?"
    if schema and prop_id in schema:
        ptype = schema[prop_id].get("type", "?")
    try:
        head = val[0]
        # date shapes: [['‣', [{'type':'date',...}]]] or [['‣', [['d', {...}]]]]
        if isinstance(head, list) and head:
            if isinstance(head[1], dict):
                d = head[1]
                return d.get("start_date") or d.get("start_time") or ""
            if (
                head[0] == "‣"
                and isinstance(head[1], list)
                and head[1]
                and isinstance(head[1][0], list)
                and head[1][0]
                and head[1][0][0] == "d"
            ):
                d = head[1][0][1]
                return d.get("start_date") or d.get("start_time") or ""
    except Exception:
        pass
    try:
        flat = val[0][0]
    except Exception:
        return str(val)
    # Relation/page pointer: [['‣', [['p', page_id, space_id]]]] → title
    if flat == "‣":
        try:
            target_id = val[0][1][0][1]
            td = _get_block_data(client, target_id)
            tprops = (td.get("properties") or {}).get("title") or []
            if tprops and isinstance(tprops[0], list):
                return str(tprops[0][0])
        except Exception:
            pass
        return ""
    if ptype == "number":
        try:
            f = float(flat)
            return int(f) if f.is_integer() else f
        except Exception:
            return flat
    return str(flat)


def _smart_read(client, block_data: dict, prop_id: str, schema: dict, depth: int = 0):
    """Read a property, evaluating formulas/rollups transparently."""
    if not isinstance(block_data, dict) or not block_data:
        return ""
    ptype = (schema.get(prop_id) or {}).get("type", "?") if schema else "?"
    if ptype in ("formula", "rollup"):
        try:
            return _eval_formula_value(client, block_data, prop_id, schema, depth + 1)
        except Exception:
            return ""
    return _read_prop_display(client, block_data, prop_id, schema)


def _to_num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except Exception:
        return None


def _to_date(v):
    from datetime import date as _date, datetime as _dt
    if isinstance(v, (_date, _dt)):
        return v
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return _dt.strptime(str(v)[:19], fmt).date()
        except Exception:
            continue
    return None



def _resolve_ref_rows(client, row_data, ref, cur_schema, depth=0):
    """Resolve one ref against a row → (rows, target_schema).

    rows is a list of (block_data, target_schema). Handles relation props,
    formulas that return blocks, and scalar props.
    """
    pid = ref.get("property")
    tschema = _load_schema_cached(client, (ref.get("collection") or {}).get("id"))
    tprop = tschema.get(pid) or {}

    if tprop.get("type") == "relation":
        # Related rows live in the relation's TARGET collection
        rel_target_id = (
            (tprop.get("collection_pointer") or {}).get("id")
            or tprop.get("collection_id")
            or ""
        )
        rel_schema = (
            _load_schema_cached(client, rel_target_id)
            if rel_target_id else {}
        )
        ids = _relation_ids(row_data, pid)
        return [(_get_block_data(client, i), rel_schema) for i in ids], rel_schema
    if tprop.get("type") == "formula" or tprop.get("type") == "rollup":
        inner = _eval_formula_value(client, row_data, pid, cur_schema, depth + 1)
        if isinstance(inner, str) and inner.startswith(_BLOCK_MARKER):
            bid = inner[len(_BLOCK_MARKER):]
            return [( _get_block_data(client, bid), tschema)], tschema
        if inner not in (None, "") :
            return [([inner], tschema)], tschema
        return [], tschema
    v = _read_prop_display(client, row_data, pid, cur_schema)
    if v != "" and v is not None:
        return [([v], tschema)], tschema
    return [], tschema


class _FormulaCtx:
    """Adapter between the formula interpreter and the Notion client/store."""

    def __init__(self, client, row_data, schema, prop_schema, depth):
        self.client = client
        self.row = row_data or {}
        self.schema = schema or {}
        _, self.refs = _fev.build_expr(prop_schema)
        self.depth = depth

    # -- ref resolution ----------------------------------------------------
    def _coerce(self, raw_val, ptype, target_schema):
        if raw_val in ("", None):
            return None
        try:
            head = raw_val[0]
        except Exception:
            return str(raw_val)
        if ptype == "number":
            return _fev._as_num(str(head[0])) if isinstance(head, list) and head else None
        if ptype == "checkbox":
            return bool(head and head[0] == "Yes")
        if ptype == "date":
            d = _to_date(_read_prop_display(self.client, {"properties": {self._cur_pid(): raw_val}}, "", {})) if False else None
            # reuse display parser for both date shapes
            disp = self._disp(raw_val)
            return _fev._maybe_date(disp)
        if ptype == "person":
            out = []
            for item in raw_val:
                try:
                    if item[0] == "‣":
                        out.append(_fev.Person(uid=item[1][0][1]))
                except Exception:
                    continue
            return out
        if ptype == "multi_select":
            txt = self._disp(raw_val)
            return [s.strip() for s in txt.split(",")] if txt else []
        if ptype == "file":
            urls = []
            for item in raw_val:
                try:
                    if item[0] != ",":
                        urls.append(item[1][0][1])
                except Exception:
                    continue
            return urls
        # title/text/select/url/email/phone → text
        return self._disp(raw_val) or None

    def _disp(self, raw_val):
        holder = {"properties": {"__p": raw_val}}
        return _read_prop_display(self.client, holder, "__p", {})

    def _prop_target_schema(self, tprop, fallback_ref=None):
        rel_id = (
            (tprop.get("collection_pointer") or {}).get("id")
            or tprop.get("collection_id")
            or ""
        )
        if not rel_id and fallback_ref is not None:
            rel_id = ((fallback_ref.get("collection") or {}).get("id")) or ""
        return _load_schema_cached(self.client, rel_id) if rel_id else {}

    def _ref_schema(self, meta):
        coll = (meta.get("collection") or {}).get("id")
        return (
            _load_schema_cached(self.client, coll)
            if coll
            else self.schema or {}
        )

    def _value_for_prop(self, row_data, pid, ref_meta=None):
        tschema = (
            self.schema
            if ref_meta is None or not ref_meta.get("collection")
            else _load_schema_cached(self.client, (ref_meta["collection"] or {}).get("id"))
        ) or {}
        tprop = tschema.get(pid) or {}
        ptype = tprop.get("type", "?")
        if ptype == "relation":
            rel_schema = self._prop_target_schema(tprop, ref_meta)
            pages = []
            for rid in _relation_ids(row_data or {}, pid)[:50]:
                bd = _get_block_data(self.client, rid)
                if bd:
                    pages.append(_fev.Page(bd, rel_schema))
            return pages
        if ptype in ("formula", "rollup"):
            inner = _eval_formula_value(
                self.client, row_data or {}, pid, tschema or self.schema, self.depth + 1
            )
            if inner is None:
                return None
            if isinstance(inner, str) and inner.startswith(_BLOCK_MARKER):
                bid = inner[len(_BLOCK_MARKER):]
                bd = _get_block_data(self.client, bid)
                return _fev.Page(bd, tschema) if bd else None
            return inner
        raw = (row_data or {}).get("properties", {}).get(pid)
        return self._coerce(raw, ptype, tschema)

    def resolve_ref(self, n):
        meta = self.refs[n] if n < len(self.refs) else {}
        pid = meta.get("property")
        if not pid and meta.get("name"):
            # name-only fpp meta (from encode_expr-built formulas) — resolve
            # the display name to a property id against the target schema
            tschema = self._ref_schema(meta)
            pid = _find_prop_id(tschema, meta["name"])
        return self._value_for_prop(self.row, pid, meta)

    def member(self, value, n):
        meta = self.refs[n] if n < len(self.refs) else {}
        if isinstance(value, list):
            out = [self.member(v, n) for v in value]
            return out
        if isinstance(value, _fev.Page):
            pid = meta.get("property")
            if not pid and meta.get("name"):
                tschema = self._ref_schema(meta)
                pid = _find_prop_id(tschema, meta["name"])
            return self._value_for_prop(value.data, pid, meta)
        if value is None:
            return None
        raise _fev.Unsupported(f"member on {type(value).__name__}")

    # -- misc ---------------------------------------------------------------
    def eq(self, a, b):
        if isinstance(a, _fev.Page):
            a = a.title
        if isinstance(b, _fev.Page):
            b = b.title
        try:
            return _fev._as_num(a) == _fev._as_num(b)
        except _fev.Unsupported:
            pass
        except Exception:
            pass
        return str(a) == str(b)

    def person_field(self, p, which):
        uid = p.get("uid") if isinstance(p, dict) else None
        if not uid:
            return ""
        try:
            u = self.client.get_user(uid)
            val = u.get("name") if which == "name" else u.get("person", {}).get("email") or u.get("email")
            return val or ""
        except Exception:
            return ""

    def now(self, with_time=False):
        from datetime import datetime as _dt2
        return _dt2.now().date()

    def today(self):
        from datetime import date as _d2
        return _d2.today()

    def self_id(self):
        return (self.row or {}).get("id", "")


def _final_formula_render(client, val):
    """Convert interpreter output into the display string contract."""
    if val is None:
        return ""
    if isinstance(val, _fev.Page):
        return _BLOCK_MARKER + str((val.data or {}).get("id", ""))
    if isinstance(val, _fev.Person):
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    if isinstance(val, list):
        parts = []
        for x in val:
            r = _final_formula_render(client, x)
            if r.startswith(_BLOCK_MARKER):
                bd = _get_block_data(client, r[len(_BLOCK_MARKER):])
                tprops = (bd.get("properties") or {}).get("title") or []
                r = str(tprops[0][0]) if tprops and isinstance(tprops[0], list) else "(page)"
            elif isinstance(x, _fev.Person):
                r = ""
            parts.append(r)
        return ", ".join(p for p in parts if p != "")
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)



def _eval_formula_value(
    client,
    row_block_data: dict,
    prop_id: str,
    schema: dict,
    depth: int = 0,
) -> str | None:
    """Evaluate a formula/rollup column for one row.

    Returns a display string, a {_BLOCK_MARKER}id sentinel for block results,
    or None when the expression shape is unsupported.
    """
    import re
    from datetime import date as _date, timedelta as _td

    if depth > 5:
        return None
    prop = schema.get(prop_id) or {}
    ptype = prop.get("type")

    # ---- rollup ----
    if ptype == "rollup":
        rel_pid = prop.get("relation_property")
        tgt_pid = prop.get("target_property")
        if not (rel_pid and tgt_pid):
            return None
        cid = (
            (prop.get("collection_pointer") or {}).get("id")
            or prop.get("collection_id")
        )
        if not cid:
            # rollups created without an explicit pointer: resolve the target
            # collection through this row's own relation property schema
            rel_prop = schema.get(rel_pid) or {}
            cid = rel_prop.get("collection_id") or (
                rel_prop.get("collection_pointer") or {}
            ).get("id")
        tschema = _load_schema_cached(client, cid)
        out = []
        for rid in _relation_ids(row_block_data, rel_pid)[:30]:
            rd = _get_block_data(client, rid)
            v = _read_prop_display(client, rd, tgt_pid, tschema)
            if v != "" and v is not None:
                out.append(str(v))
        return ", ".join(out)

    if ptype != "formula":
        return None

    # ---- Interpreter path (full formula language) -------------------------
    _src_check, _ = _fev.build_expr(prop)
    if not _src_check.strip():
        return ""
    ctx = _FormulaCtx(client, row_block_data, schema, prop, depth)
    try:
        val = _fev.evaluate(prop, ctx)
    except _fev.Unsupported:
        return None
    except Exception:
        return None
    return _final_formula_render(client, val)


def _render_row_props(row, schema_names: dict[str, str] | None = None) -> list[str]:
    """Render a database row's properties as readable key: value lines.

    schema_names maps slug → original column name (for readable keys).
    """
    try:
        props = row.get_all_properties()
    except Exception:
        props = {}
    parts = []
    for k, v in props.items():
        label = schema_names.get(k, k) if schema_names else k
        parts.append(f"  {label}: {_render_property(v)}")
    return parts


def _get_inline_db_name(block) -> str:
    """Try to resolve an inline database's name from a collection_view block.

    The collection may not be lazily loaded on the block itself, so we look it
    up via the view_ids → collection_view record → collection_pointer → collection.
    """
    col = getattr(block, "collection", None)
    if col is not None and hasattr(col, "name") and col.name:
        return col.name
    # Fallback: resolve via view_ids → collection_view → collection_pointer
    view_ids = block.get("view_ids") or []
    for vid in view_ids:
        cv_data = block._client._store._values.get("collection_view", {}).get(vid)
        if cv_data:
            ptr = cv_data.get("format", {}).get("collection_pointer", {})
            col_id = ptr.get("id")
            if col_id:
                col_data = block._client._store._values.get("collection", {}).get(col_id)
                if col_data:
                    # Collection name is stored as Notion rich-text array, not plain string
                    name_raw = col_data.get("name") or col_data.get("title")
                    if name_raw:
                        # Parse Notion rich-text: [["text", [["b"]]], ...] → "text"
                        try:
                            parts = []
                            for segment in name_raw:
                                if isinstance(segment, list) and segment:
                                    parts.append(str(segment[0]))
                                elif isinstance(segment, str):
                                    parts.append(segment)
                            return "".join(parts)
                        except Exception:
                            return str(name_raw)
                # Try loading the collection
                try:
                    col_obj = block._client.get_collection(col_id)
                    if col_obj and col_obj.name:
                        return col_obj.name
                except Exception:
                    pass
    return ""


def _build_image_url(block) -> str:
    """Build a downloadable image URL for an image block.

    Notion stores images as 'attachment:<file_id>:<filename>' which the browser
    resolves via a proxy URL: https://app.notion.com/image/<url-encoded-source>?table=block&id=<block_id>&spaceId=...&userId=...
    This proxy URL works with the token_v2 cookie for authentication.
    """
    source = block.get("format.display_source") or block.get("source") or ""
    if not source:
        return ""
    # If it's already a full URL (http/https), return as-is
    if source.startswith("http"):
        return source
    # Build Notion image proxy URL for attachment: sources
    from urllib.parse import quote
    space_id = ""
    user_id = ""
    try:
        space_id = block._client.current_space.id
    except Exception:
        pass
    try:
        user_id = block._client.current_user.id
    except Exception:
        pass
    params = f"table=block&id={block.id}"
    if space_id:
        params += f"&spaceId={space_id}"
    if user_id:
        params += f"&userId={user_id}"
    params += "&cache=v2"
    return f"https://app.notion.com/image/{quote(source, safe='')}?{params}"


_NOTION_HOST_SUFFIXES = (".notion.com", ".notion.so", ".notion-static.com")


def _is_notion_host(url: str) -> bool:
    """True if the URL points at a Notion-operated host (may receive the session cookie)."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return False
    return host in ("notion.com", "notion.so") or host.endswith(_NOTION_HOST_SUFFIXES)


def _fetch_image(client, url: str):
    """Download an image URL without ever handing the Notion session to a third party.

    Notion-hosted URLs (image proxy, signed files) need the token_v2 cookie and
    go through the client session. Any other http(s) source — an image block
    whose source is an external URL — is fetched with a plain, cookie-less
    request, so someone who can place an image block in a page you read cannot
    collect your session token. Non-http(s) schemes are rejected.
    """
    from urllib.parse import urlparse

    import requests

    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"Unsupported image URL scheme: {url}")
    if _is_notion_host(url):
        return client.session.get(url, allow_redirects=True, timeout=30)
    return requests.get(url, allow_redirects=True, timeout=30)


def _block_to_markdown(block) -> str:
    """Convert a single block to markdown text."""
    btype = block.get("type", "") or ""
    # Plaintext title of the block, used by most text branches below (and by
    # the factory / link_to_page markers). Computed up front so those early
    # branches don't reference it before assignment.
    try:
        md = block.title_plaintext
    except Exception:
        md = ""
    # Image — emit marker with filename and get_image hint
    if btype == "image":
        # Extract filename from properties for readability
        filename = ""
        try:
            title_raw = block.get("properties.title") or []
            if title_raw and isinstance(title_raw[0], list):
                filename = str(title_raw[0][0])
            elif title_raw and isinstance(title_raw[0], str):
                filename = title_raw[0]
        except Exception:
            pass
        caption = ""
        try:
            caption = block.caption or ""
        except Exception:
            pass
        label = caption or filename or "(untitled)"
        return f"[image] {label} — use get_image(\"{block.id}\") to download"
    # Embed/video/file/audio/pdf — emit marker with source URL
    if btype in ("embed", "video", "file", "audio", "pdf"):
        source = block.get("format.display_source") or block.get("source") or ""
        return f"[{btype}] {source}" if source else f"[{btype}] (no source)"
    # Bookmark/figma/tweet/gist/etc — emit marker with source URL
    if btype in ("bookmark", "figma", "tweet", "gist", "drive", "loom", "typeform",
                 "codepen", "maps", "invision", "framer", "html", "miro", "excalidraw",
                 "replit", "deepnote", "sketch", "abstract", "mixpanel"):
        source = block.get("format.display_source") or block.get("source") or ""
        return f"[{btype}] {source}" if source else f"[{btype}]"
    # Simple table (type=table or simple_table) — render as markdown table from children
    if btype in ("table", "simple_table"):
        return _table_to_markdown(block)
    # Column list — render children sequentially with column headers
    if btype == "column_list":
        return ""  # handled in _render_page_tree via recursion
    if btype == "column":
        return ""  # handled in _render_page_tree via recursion
    # Synced block — render its children (same as a container)
    if btype == "synced_block":
        return ""  # handled in _render_page_tree via recursion
    # Breadcrumb — auto-generated by Notion
    if btype == "breadcrumb":
        return "[breadcrumb]"
    # Factory — template factory block
    if btype == "factory":
        return f"[template factory] {md}" if md else "[template factory]"
    # Link to collection — linked database
    if btype == "link_to_collection":
        return f"[linked database] — use get_database(\"{block.id}\")"
    # Table of contents
    if btype == "table_of_contents":
        return "[table of contents]"
    # Link to page
    if btype == "link_to_page":
        return f"[link to page] {md}" if md else "[link to page]"
    # Inline database — only emit stub if there's actually a collection
    if btype in ("collection_view", "collection_view_page"):
        db_name = _get_inline_db_name(block)
        if db_name:
            return f"[inline database] {db_name} — use get_database(\"{block.id}\")"
        # No collection found — might be a simple table misidentified, or empty DB
        return f"[collection_view] (no collection) — block id: {block.id}"
    if btype == "header":
        return f"# {md}"
    if btype == "sub_header":
        return f"## {md}"
    if btype == "sub_sub_header":
        return f"### {md}"
    if btype == "sub_sub_sub_header":
        return f"#### {md}"
    if btype == "to_do":
        checked = block.get("format.checked", False)
        return f"- [{'x' if checked else ' '}] {md}"
    if btype == "bulleted_list":
        return f"- {md}"
    if btype == "numbered_list":
        return f"1. {md}"
    if btype == "quote":
        return f"> {md}"
    if btype == "code":
        return f"```\n{md}\n```"
    if btype == "callout":
        icon = block.get("format.page_icon", "") or "💡"
        return f"{icon} {md}"
    if btype == "divider":
        return "---"
    if btype == "toggle":
        return f"<details><summary>{md}</summary></details>"
    if btype == "equation":
        return f"$$ {md} $$"
    return md


def _table_to_markdown(block) -> str:
    """Render a Notion simple table (type=table) as a markdown table.

    Simple tables store rows as children blocks, with cells in properties.
    """
    children = getattr(block, "children", None)
    if not children:
        return f"[table] (empty — block id: {block.id})"
    # Check if table has collection (some tables are collection-backed)
    col = getattr(block, "collection", None)
    if col is not None:
        db_name = _get_inline_db_name(block) or "(unnamed)"
        return f"[inline database] {db_name} — use get_database(\"{block.id}\")"
    rows = []
    for child in children:
        cells = []
        # Table row cells are in properties, keyed by column id
        props = child.get("properties") or {}
        # Get column order from format
        fmt = block.get("format", {}) or {}
        col_order = fmt.get("table_block_column_order", [])
        col_widths = fmt.get("table_block_column_format", {})
        if col_order:
            for col_id in col_order:
                cell_data = props.get(col_id, [])
                cell_text = _parse_rich_text(cell_data)
                cells.append(cell_text.replace("|", "\\|").replace("\n", " "))
        else:
            # Fallback: just dump all property values in order
            for _, cell_data in props.items():
                cell_text = _parse_rich_text(cell_data)
                cells.append(cell_text.replace("|", "\\|").replace("\n", " "))
        rows.append(cells)
    if not rows:
        return f"[table] (no rows — block id: {block.id})"
    # First row is header
    ncols = len(rows[0])
    lines = []
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(ncols)) + " |")
    for row in rows[1:]:
        # Pad row to ncols
        while len(row) < ncols:
            row.append("")
        lines.append("| " + " | ".join(row[:ncols]) + " |")
    return "\n".join(lines)


def _parse_rich_text(data) -> str:
    """Parse Notion rich-text property value to plain text.

    Notion stores cell text as: [["text", [["b"]]], [", "], ["more text"]]
    Each element is [text, formatting_markers] or a plain string.
    """
    if not data:
        return ""
    if isinstance(data, str):
        return data
    parts = []
    for segment in data:
        if isinstance(segment, str):
            parts.append(segment)
        elif isinstance(segment, list) and segment:
            parts.append(str(segment[0]))
    return "".join(parts)


def _tree_to_markdown(client: NotionClient, block, depth: int, level: int = 0) -> list[str]:
    """Recursively render a block tree to markdown lines."""
    if block is None:
        return []
    lines = []
    btype = block.get("type", "") or ""

    # Container blocks — render children, not the container itself.
    # Container blocks don't consume depth (they're transparent wrappers).
    if btype == "column_list":
        if depth == 0:
            return lines
        children = getattr(block, "children", None)
        if children is None:
            return lines
        col_num = 0
        for child in children:
            col_num += 1
            if child.get("type", "") == "column":
                lines.append(("  " * level) + f"--- Column {col_num} ---")
                child_lines = _tree_to_markdown(
                    client, child, depth, level + 1
                )
                lines.extend(child_lines)
            else:
                child_lines = _tree_to_markdown(
                    client, child, depth, level
                )
                lines.extend(child_lines)
        return lines

    if btype == "column":
        # Column itself is transparent — just render children, don't consume depth
        if depth == 0:
            return lines
        children = getattr(block, "children", None)
        if children is None:
            return lines
        for child in children:
            child_lines = _tree_to_markdown(
                client, child, depth, level
            )
            lines.extend(child_lines)
        return lines

    if btype == "synced_block":
        # Synced block — render children, don't consume depth
        if depth == 0:
            return lines
        children = getattr(block, "children", None)
        if children is None:
            return lines
        for child in children:
            child_lines = _tree_to_markdown(
                client, child, depth, level
            )
            lines.extend(child_lines)
        return lines

    md = _block_to_markdown(block)
    if md:
        lines.append(("  " * level) + md)
    if depth == 0:
        return lines
    children = getattr(block, "children", None)
    if children is None:
        return lines
    for child in children:
        if child is None:
            continue
        child_lines = _tree_to_markdown(
            client, child, depth - 1 if depth > 0 else -1, level + 1
        )
        lines.extend(child_lines)
    return lines


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search(
    query: str,
    limit: int = 20,
) -> str:
    """Search Notion blocks/pages in the current space.

    Args:
        query: Search query string
        limit: Maximum results (default 20)

    Returns:
        Markdown list of matching blocks with type, title, and URL.
    """
    client = _get_client()
    results = client.search_blocks(query, limit=limit)
    if not results:
        return "(no results)"
    lines = []
    for b in results:
        s = _block_summary(b)
        icon = _format_icon(s["icon"] or "")
        title = s["title"] or ""
        lines.append(f"[{s['type']}] {icon}{title}\n  {s['url']}")
    return "\n".join(lines)


@mcp.tool()
def get_page(
    page_id: str,
    depth: int = 1,
) -> str:
    """Fetch a Notion page and its children tree as markdown.

    Args:
        page_id: Page URL or ID
        depth: 0=metadata only, 1=direct children (default), 2=grandchildren, -1=full tree

    Returns:
        Markdown rendering of the page and its children.
    """
    client = _get_client()
    page = client.get_block(page_id)
    if page is None:
        return f"Page not found: {page_id}"
    lines = _tree_to_markdown(client, page, depth)
    return "\n".join(lines)


@mcp.tool()
def get_block(block_id: str) -> str:
    """Fetch a single Notion block as markdown.

    Args:
        block_id: Block URL or ID

    Returns:
        Markdown rendering of the block, or type info for non-text blocks.
    """
    client = _get_client()
    block = client.get_block(block_id)
    if block is None:
        return f"Block not found: {block_id}"
    md = _block_to_markdown(block)
    btype = block.get("type", "") or ""
    if not md.strip():
        # Non-text block (collection_view_page, column, link_to_page, etc.)
        title = block.title_plaintext if hasattr(block, "title_plaintext") else ""
        if title:
            return f"[{btype}] {title}"
        return f"[{btype}] (no text content — use get_page or get_database for details)"
    return md


@mcp.tool(structured_output=False)
def get_image(block_id: str):
    """Download an image block and return it as MCP ImageContent.

    The Notion image proxy URL requires token_v2 cookie authentication, so
    external clients cannot download images directly. This tool fetches the
    image through the server's authenticated session and returns it as an
    MCP image content block — the client renders it natively as an image
    (~157 tokens for a typical diagram), not as base64 text (~37k tokens).

    Args:
        block_id: Image block URL or ID

    Returns:
        MCP ImageContent (image block) — client renders as image.
        On error, returns a text message.
    """
    from mcp.server.mcpserver import Image
    client = _get_client()
    block = client.get_block(block_id)
    if block is None:
        return f"Block not found: {block_id}"
    btype = block.get("type", "") or ""
    if btype != "image":
        return f"Block {block_id} is not an image (type: {btype})"
    url = _build_image_url(block)
    if not url:
        return f"Image block {block_id} has no source URL"
    try:
        r = _fetch_image(client, url)
        r.raise_for_status()
    except Exception as exc:
        return f"Failed to download image: {exc}"
    mime = r.headers.get("content-type", "image/png")
    # Fallback mime detection from filename
    if not mime or mime == "application/octet-stream":
        source = block.get("format.display_source") or block.get("source") or ""
        if source.endswith(".png"):
            mime = "image/png"
        elif source.endswith(".jpg") or source.endswith(".jpeg"):
            mime = "image/jpeg"
        elif source.endswith(".gif"):
            mime = "image/gif"
        elif source.endswith(".svg"):
            mime = "image/svg+xml"
        elif source.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/png"
    # Extract format from mime (e.g. "image/png" -> "png")
    fmt = mime.split("/")[-1] if "/" in mime else "png"
    return Image(data=r.content, format=fmt)


@mcp.tool()
def list_pages() -> str:
    """List top-level pages in the current space.

    Returns:
        Markdown list of pages with title and URL.
    """
    client = _get_client()
    pages = client.get_top_level_pages()
    if not pages:
        return "(no pages)"
    lines = []
    for p in pages:
        s = _block_summary(p)
        title = s["title"] or ""
        if not title:
            continue  # skip untitled/empty blocks
        icon = _format_icon(s["icon"] or "")
        lines.append(f"[page] {icon}{title}\n  {s['url']}")
    return "\n".join(lines)


@mcp.tool()
def get_database(
    database_id: str,
    sample_rows: int = 5,
    full_schema: bool = False,
) -> str:
    """Fetch a Notion database (collection) schema and sample rows.

    Args:
        database_id: Database block URL or ID, or collection ID
        sample_rows: Number of sample rows to show (default 5)
        full_schema: If true, include full column definitions (relation
            targets, rollup configs, formula expressions, select options) —
            rich enough to diff for idempotent provisioning.

    Returns:
        Database name, column schema, and sample row data as markdown.

    Note: Formula and rollup columns show '(computed)' as placeholder.
        Notion evaluates these browser-side (JavaScript) and does not return
        values via the API. This is a known limitation of the cookie-based
        internal API — not a bug.
    """
    client = _get_client()
    block = client.get_block(database_id)
    collection = None
    if block is not None:
        collection = getattr(block, "collection", None)
        # If block is collection_view but collection is None (lazy-loaded),
        # try resolving via view_ids → collection_view record → collection_pointer
        if collection is None and block.get("view_ids"):
            view_ids = block.get("view_ids") or []
            for vid in view_ids:
                cv_data = client._store._values.get("collection_view", {}).get(vid)
                if cv_data:
                    ptr = cv_data.get("format", {}).get("collection_pointer", {})
                    col_id = ptr.get("id")
                    if col_id:
                        try:
                            collection = client.get_collection(col_id)
                            break
                        except Exception:
                            pass
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    if collection is None:
        btype = block.get("type", "") if block else "(unknown)"
        return f"Database not found: {database_id} (block type: {btype}). This may be a simple table, not a database — use get_page to read it."
    try:
        name = collection.name if hasattr(collection, "name") else "(unnamed)"
        schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    except Exception as exc:
        return f"Failed to read database schema: {exc}"
    # Build slug → name map for readable column keys
    slug_to_name: dict[str, str] = {}
    formula_slugs: set[str] = set()
    lines = [f"# {name}", ""]
    lines.append("## Columns")
    for prop in schema:
        pname = prop.get("name", "?")
        ptype = prop.get("type", "?")
        pslug = prop.get("slug", pname)
        slug_to_name[pslug] = pname
        if ptype in ("formula", "rollup"):
            formula_slugs.add(pslug)
        lines.append(f"  - **{pname}** ({ptype})")
    if full_schema:
        lines.append("")
        lines.append("## Full schema")
        raw_schema = collection.get("schema") or {}
        for pid, p in raw_schema.items():
            ptype = p.get("type", "?")
            lines.append(f"  - **{p.get('name', '?')}** ({ptype}) [id: {pid}]")
            if ptype == "relation":
                tgt = p.get("collection_pointer") or {}
                lines.append(
                    f"      target: {p.get('collection_id') or tgt.get('id', '?')}"
                )
                lines.append(f"      single: {'yes' if p.get('limit') == 1 else 'no'}")
                ar = p.get("autoRelate") or {}
                if ar.get("enabled"):
                    lines.append(f"      reverse_name: {ar.get('name', '')}")
            elif ptype == "rollup":
                lines.append(
                    f"      relation_property: {p.get('relation_property', '?')}"
                )
                lines.append(f"      target_property: {p.get('target_property', '?')}")
                if p.get("aggregation"):
                    lines.append(f"      aggregation: {p['aggregation']}")
            elif ptype == "formula":
                try:
                    src, _ = _fev.build_expr(p)
                    lines.append(f"      expression: {src}")
                except Exception:
                    lines.append("      expression: (unparseable)")
            elif ptype in ("select", "multi_select", "status"):
                opts = [o.get("value", "") for o in p.get("options") or []]
                lines.append(f"      options: {opts}")
    lines.append("")
    rows = collection.get_rows()[:sample_rows] if hasattr(collection, "get_rows") else []
    if rows:
        lines.append(f"## Sample rows ({len(rows)})")
        # prop id → schema entry map for formula evaluation
        raw_schema = collection.get("schema") or {}
        for row in rows:
            try:
                props = row.get_all_properties()
            except Exception:
                props = {}
            try:
                row_data = client._store._get("block", row.id) or {}
            except Exception:
                row_data = {}
            parts = [f"  id: {row.id}"]
            for prop in schema:
                pname = prop.get("name", "?")
                pslug = prop.get("slug", pname)
                ptype = prop.get("type", "?")
                if ptype in ("formula", "rollup"):
                    pid = prop.get("id")
                    evaluated = None
                    if pid and row_data:
                        try:
                            evaluated = _eval_formula_value(client, row_data, pid, raw_schema)
                        except Exception:
                            evaluated = None
                    if evaluated is not None and not str(evaluated).startswith("\x00"):
                        rendered = str(evaluated)
                    elif evaluated is not None:
                        bid = str(evaluated)[len(_BLOCK_MARKER):]
                        bd = _get_block_data(client, bid)
                        tprops = (bd.get("properties") or {}).get("title") or []
                        rendered = (
                            str(tprops[0][0])
                            if tprops and isinstance(tprops[0], list)
                            else "(related row)"
                        )
                    else:
                        rendered = "(computed)"
                else:
                    v = props.get(pslug, "")
                    rendered = _render_property(v)
                parts.append(f"  {pname}: {rendered}")
            lines.append("\n".join(parts))
            lines.append("---")
    return "\n".join(lines)


@mcp.tool()
def query_database(
    database_id: str,
    limit: int = 20,
    fetch_all: bool = False,
) -> str:
    """Query a Notion database and return rows as a markdown table.

    Args:
        database_id: Database block URL or ID, or collection ID
        limit: Maximum rows to return (default 20)
        fetch_all: If true, fetch every row in the database regardless of
            limit (the internal queryCollection API has no cursor pagination,
            but a single request can return the full result set).

    Returns:
        Markdown table of database rows with all properties.

    Note: Formula and rollup columns show '(computed)' as placeholder.
        Notion evaluates these browser-side (JavaScript) and does not return
        values via the API. This is a known limitation of the cookie-based
        internal API — not a bug.
    """
    client = _get_client()
    block = client.get_block(database_id)
    collection = None
    if block is not None:
        collection = getattr(block, "collection", None)
        # If block is collection_view but collection is None (lazy-loaded),
        # try resolving via view_ids → collection_view record → collection_pointer
        if collection is None and block.get("view_ids"):
            view_ids = block.get("view_ids") or []
            for vid in view_ids:
                cv_data = client._store._values.get("collection_view", {}).get(vid)
                if cv_data:
                    ptr = cv_data.get("format", {}).get("collection_pointer", {})
                    col_id = ptr.get("id")
                    if col_id:
                        try:
                            collection = client.get_collection(col_id)
                            break
                        except Exception:
                            pass
    if collection is None:
        try:
            collection = client.get_collection(database_id)
        except Exception:
            pass
    if collection is None:
        btype = block.get("type", "") if block else "(unknown)"
        return f"Database not found: {database_id} (block type: {btype}). This may be a simple table, not a database — use get_page to read it."
    try:
        schema = collection.get_schema_properties() if hasattr(collection, "get_schema_properties") else []
    except Exception as exc:
        return f"Failed to read database schema: {exc}"
    slug_to_name: dict[str, str] = {}
    col_names: list[str] = ["id"]
    formula_slugs: set[str] = set()
    for prop in schema:
        pname = prop.get("name", "?")
        pslug = prop.get("slug", pname)
        ptype = prop.get("type", "?")
        slug_to_name[pslug] = pname
        col_names.append(pname)
        if ptype in ("formula", "rollup"):
            formula_slugs.add(pslug)
    rows = collection.get_rows(
        **({"limit": -1} if fetch_all else {"limit": limit})
    ) if hasattr(collection, "get_rows") else []
    if fetch_all and rows:
        # -1 queries the remote total first, then fetches exactly that many
        total_note = f"(fetched all {len(rows)} rows)"
    else:
        total_note = ""
    if not rows:
        return "(no rows)"
    # Build markdown table
    lines = []
    # Header
    lines.append("| " + " | ".join(col_names) + " |")
    lines.append("| " + " | ".join("---" for _ in col_names) + " |")
    # Rows
    raw_schema = collection.get("schema") or {}
    for row in rows:
        try:
            props = row.get_all_properties()
        except Exception:
            props = {}
        try:
            row_data = client._store._get("block", row.id) or {}
        except Exception:
            row_data = {}
        cells = [row.id]
        for prop in schema:
            pslug = prop.get("slug", prop.get("name", "?"))
            ptype = prop.get("type", "?")
            if ptype in ("formula", "rollup"):
                pid = prop.get("id")
                evaluated = None
                if pid and row_data:
                    try:
                        evaluated = _eval_formula_value(client, row_data, pid, raw_schema)
                    except Exception:
                        evaluated = None
                if evaluated is not None and not str(evaluated).startswith("\x00"):
                    rendered = str(evaluated)
                elif evaluated is not None:
                    bid = str(evaluated)[len(_BLOCK_MARKER):]
                    bd = _get_block_data(client, bid)
                    tprops = (bd.get("properties") or {}).get("title") or []
                    rendered = (
                        str(tprops[0][0])
                        if tprops and isinstance(tprops[0], list)
                        else "(related row)"
                    )
                else:
                    rendered = "(computed)"
            else:
                v = props.get(pslug, "")
                rendered = _render_property(v)
            cells.append(rendered.replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(cells) + " |")
    if total_note:
        lines.append("")
        lines.append(total_note)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write tools (gated by NOTION_ALLOW_WRITE=1)
# ---------------------------------------------------------------------------

_WRITE_ENABLED = os.environ.get("NOTION_ALLOW_WRITE") == "1"

def _embed_type_map() -> dict:
    """Embed-type → block-class map (lazy — needs the write-enabled imports)."""
    return {
        "embed": EmbedBlock,
        "bookmark": BookmarkBlock,
        "tweet": TweetBlock,
        "gist": GistBlock,
        "figma": FigmaBlock,
        "loom": LoomBlock,
        "typeform": TypeformBlock,
        "codepen": CodepenBlock,
        "maps": MapsBlock,
        "invision": InvisionBlock,
        "framer": FramerBlock,
        "drive": DriveBlock,
        "html": HtmlBlock,
        "miro": MiroBlock,
        "excalidraw": ExcalidrawBlock,
        "replit": ReplitBlock,
        "deepnote": DeepnoteBlock,
        "sketch": SketchBlock,
        "abstract": AbstractBlock,
        "mixpanel": MixpanelBlock,
    }


def _import_csv_impl(client, parent, file_path: str, title: str = "") -> str:
    """Shared CSV→inline-database import (used by MCP tool and CLI)."""
    import csv as csv_mod
    import os

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        headers = next(reader)
        rows_data = list(reader)
    if not headers:
        raise ValueError("CSV file has no headers")
    if not title:
        title = os.path.basename(file_path).rsplit(".", 1)[0]

    schema = {}
    title_prop_id = None
    for i, h in enumerate(headers):
        prop_id = f"col{i:04x}"
        if title_prop_id is None:
            schema[prop_id] = {"name": h, "type": "title"}
            title_prop_id = prop_id
        else:
            schema[prop_id] = {"name": h, "type": "text"}
    if title_prop_id is None:
        schema["title"] = {"name": "Name", "type": "title"}
        title_prop_id = "title"

    cvb = parent.children.add_new(CollectionViewBlock)
    collection_id = client.create_record("collection", parent=cvb, schema=schema)
    cvb.collection = client.get_collection(collection_id)
    cvb.title = title
    cvb.views.add_new(view_type="table")

    from unpy.utils import slugify

    title_slug = slugify(schema[title_prop_id]["name"])
    for row in rows_data:
        props = {}
        for i, val in enumerate(row):
            if i < len(headers):
                if i == 0:
                    props[title_slug] = val
                else:
                    props[slugify(headers[i])] = val
        try:
            cvb.collection.add_row(**props)
        except Exception:
            pass  # Skip rows that fail
    return cvb.id


def _build_collection_schema(col_specs: list, client=None, parent_space_id: str = "") -> dict:
    """Build a Notion collection schema from column specs.

    Each spec: {"name": str, "type": str, "options": [str, ...]}
    Relation specs additionally accept:
        "target_database_id": URL/ID of the related database (required),
        "limit": 1 caps the relation at one linked row,
        "reverse_name": creates a two-way synced property on the target
            database (written via a forward+reverse schema transaction; see
            create_database).
    Formula specs accept "expression" (Notion formula2 source).
    Rollup specs accept "relation_property" (name), "target_property" (name),
        and optional "aggregation" (count, sum, percent_checked, latest_date...).
    Returns: {prop_id: {"name": str, "type": str, ...}}
    """
    import uuid
    schema = {}
    for spec in col_specs:
        name = spec.get("name", "Untitled")
        ptype = spec.get("type", "text")
        prop_id = spec.get("id") or uuid.uuid4().hex[:4]
        # stamp so a later pass reuses the same id (two-pass rollup build)
        spec["id"] = prop_id
        prop = {"name": name, "type": ptype}
        if ptype in ("select", "multi_select", "status") and spec.get("options"):
            prop["options"] = [
                {"value": o, "color": "default"} for o in spec["options"]
            ]
        if ptype == "relation":
            rel = _build_relation_prop(spec, client, parent_space_id)
            if rel.get("property") and not spec.get("_reverse_prop_id"):
                spec["_reverse_prop_id"] = rel["property"]
            prop.update(rel)
        elif ptype == "formula":
            expr = spec.get("expression", "")
            if not expr:
                raise ValueError(
                    f"Column '{name}': formula columns need an 'expression'"
                )
            # Build name → {property, collection} metas so the Notion UI can
            # resolve refs (it needs ids; the client-side evaluator accepts
            # name-only).
            own_pointer = spec.get("_own_pointer") or {}
            own_schema = spec.get("_own_schema") or schema
            prop_meta = {}
            for other in col_specs:
                if other is spec:
                    continue
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
                        "id": _resolve_collection_id(client, tgt) if tgt else "",
                        "table": "collection",
                        "spaceId": spec.get("_space_id", ""),
                    }
                else:
                    meta["collection"] = own_pointer
                prop_meta[other_name] = meta
            prop["version"] = "v2"
            prop["formula2"] = {
                "code": _fev.encode_expr(expr, prop_meta),
                "result_type": {"type": "text"},
            }
        elif ptype == "rollup":
            prop.update(_build_rollup_prop(spec, client))
        schema[prop_id] = prop
    return schema


def _resolve_collection_id(client, ref: str) -> str:
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


def _build_relation_prop(spec: dict, client, parent_space_id: str) -> dict:
    """Build the schema fragment for a relation property.

    If "reverse_name" is set, returns a fragment carrying the symmetric
    two-way shape observed in Notion's own client: the forward prop holds
    "property": <reverse_prop_id> and "version": "v2". The caller is
    responsible for writing the matching reverse property into the target
    collection's schema (see _apply_reverse_relation).
    """
    target_ref = spec.get("target_database_id", "")
    if not target_ref:
        raise ValueError(
            f"Column '{spec.get('name', '?')}': relation columns need "
            "'target_database_id' (URL or ID of the related database)"
        )
    target_id = _resolve_collection_id(client, target_ref)
    space_id = parent_space_id or (
        client.current_space.id if client and client.current_space else ""
    )
    import uuid
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


def _build_rollup_prop(spec: dict, client) -> dict:
    """Build the schema fragment for a rollup property.

    Needs the relation property (by name) on THIS database and the target
    property (by name) on the related database.
    """
    rel_name = spec.get("relation_property", "")
    target_name = spec.get("target_property", "")
    if not (rel_name and target_name):
        raise ValueError(
            f"Column '{spec.get('name', '?')}': rollup columns need "
            "'relation_property' and 'target_property' names"
        )
    own_schema = spec.get("_own_schema") or {}
    rel_pid = _find_prop_id(own_schema, rel_name)
    if not rel_pid:
        raise ValueError(
            f"rollup '{spec.get('name', '?')}': relation property "
            f"'{rel_name}' not found in this database"
        )
    rel_prop = own_schema.get(rel_pid, {})
    target_col_id = rel_prop.get("collection_id") or (
        rel_prop.get("collection_pointer") or {}
    ).get("id", "")
    target_schema = _fetch_schema(client, target_col_id)
    tgt_pid = _find_prop_id(target_schema, target_name)
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
    if agg:
        prop["aggregation"] = agg
    return prop


def _find_prop_id(schema: dict, name: str) -> str:
    from unpy.utils import slugify as _slug
    want = _slug(name).lower()
    for pid, p in schema.items():
        if _slug(p.get("name", "")).lower() == want:
            return pid
    return ""


def _fetch_schema(client, col_id: str) -> dict:
    if not col_id or client is None:
        return {}
    try:
        coll = client.get_collection(col_id)
        return coll.get("schema") or {}
    except Exception:
        return {}


@mcp.tool()
def get_comments(
    block_id: str,
    include_resolved: bool = True,
) -> str:
    """Read all comment threads attached to a page or block.

    Args:
        block_id: Page/block URL or ID
        include_resolved: If false, skip resolved (closed) threads

    Returns:
        Markdown list of discussions, each with its comments
        (author, text, timestamps).
    """
    client = _get_client()
    try:
        discussions = client.get_comments(
            block_id, include_resolved=include_resolved
        )
    except Exception as exc:
        return f"Failed to read comments: {exc}"
    if not discussions:
        return "(no comments)"
    lines = []
    for d in discussions:
        status = " [resolved]" if d["resolved"] else ""
        lines.append(f"- thread {d['id']}{status} — on: {d['context'] or '(page)'}")
        for c in d["comments"]:
            if not c["alive"]:
                continue
            lines.append(f"    - {c['text']}  ({c['created_time']}, by {c['author']})")
    return "\n".join(lines)


if _WRITE_ENABLED:
    from unpy.block import (
        PageBlock, TextBlock, TodoBlock, HeaderBlock, SubheaderBlock,
        SubsubheaderBlock, CalloutBlock, BulletedListBlock, NumberedListBlock,
        QuoteBlock, CodeBlock, DividerBlock, ToggleBlock, EquationBlock,
        CollectionViewBlock, CollectionViewPageBlock,
        EmbedBlock, BookmarkBlock, ImageBlock, VideoBlock, AudioBlock,
        FileBlock, PDFBlock, TweetBlock, GistBlock, FigmaBlock, LoomBlock,
        TypeformBlock, CodepenBlock, MapsBlock, InvisionBlock, FramerBlock,
        DriveBlock, HtmlBlock, MiroBlock, ExcalidrawBlock, ReplitBlock,
        DeepnoteBlock, SketchBlock, AbstractBlock, MixpanelBlock,
    )
    from unpy.collection import Collection

    @mcp.tool()
    def add_comment(
        block_id: str,
        text: str,
        discussion_id: str = "",
    ) -> str:
        """Add a comment to a page (new thread, or reply inside an existing one).

        Args:
            block_id: Page/block URL or ID
            text: Comment text (plain text; user mentions render as "@…")
            discussion_id: Optional existing thread id — omit to start a new thread

        Returns:
            Confirmation with comment and discussion ids.
        """
        client = _get_client()
        try:
            result = client.add_comment(
                block_id, text, discussion_id=discussion_id or None
            )
        except Exception as exc:
            return f"Failed to add comment: {exc}"
        return (
            f"Comment added: {result['comment_id']} "
            f"(discussion: {result['discussion_id']})"
        )

    @mcp.tool()
    def create_page(
        parent_id: str,
        title: str,
        icon: str = "",
    ) -> str:
        """Create a new page under a parent block.

        Args:
            parent_id: Parent page URL or ID
            title: Title for the new page
            icon: Optional emoji icon (e.g. "📄")

        Returns:
            URL of the created page.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"
        page = parent.children.add_new(PageBlock, title=title)
        if icon:
            page.icon = icon
        return page.get_browseable_url()

    @mcp.tool()
    def append_blocks(
        page_id: str,
        blocks: str,
    ) -> str:
        """Append blocks to a page. blocks is a JSON array of {type, text, checked?}.

        Supported types: text, todo, header, subheader, subsubheader, callout,
        bulleted_list, numbered_list, quote, code, divider, toggle, equation.

        Args:
            page_id: Parent page URL or ID
            blocks: JSON array string, e.g. [{"type":"text","text":"Hello"},{"type":"todo","text":"Task","checked":true}]

        Returns:
            Confirmation with count of blocks added.
        """
        client = _get_client()
        parent = client.get_block(page_id)
        if parent is None:
            return f"Page not found: {page_id}"
        block_specs = json.loads(blocks)
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
        count = 0
        for spec in block_specs:
            btype = spec.get("type", "text")
            text = spec.get("text", "")
            cls = TYPE_MAP.get(btype, TextBlock)
            kwargs = {"title": text}
            if btype == "todo" and "checked" in spec:
                kwargs["checked"] = spec["checked"]
            if btype == "callout" and "icon" in spec:
                kwargs["icon"] = spec["icon"]
            parent.children.add_new(cls, **kwargs)
            count += 1
        return f"Added {count} block(s) to {page_id}"

    @mcp.tool()
    def update_block(
        block_id: str,
        field: str,
        value: str,
    ) -> str:
        """Update a block field. Supports title/text fields and 'checked' for todos.

        Args:
            block_id: Block URL or ID
            field: Field name ('title' or 'checked')
            value: New value ('true'/'false' for checked, text for title)

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        if field == "title":
            block.title = value
        elif field == "checked":
            block.checked = value.lower() in ("true", "1", "yes")
        else:
            return f"Unsupported field: {field} (try 'title' or 'checked')"
        return f"Updated {field} on block {block_id}"

    @mcp.tool()
    def delete_block(
        block_id: str,
        permanently: bool = False,
    ) -> str:
        """Delete a block (soft delete by default, permanent optional).

        Args:
            block_id: Block URL or ID
            permanently: If true, permanently delete (cannot undo)

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        block.remove(permanently=permanently)
        action = "Permanently deleted" if permanently else "Deleted (soft)"
        return f"{action} block {block_id}"

    @mcp.tool()
    def move_block(
        block_id: str,
        target_id: str,
        position: str = "after",
    ) -> str:
        """Move a block relative to a target block.

        Args:
            block_id: Block to move
            target_id: Target block
            position: 'before', 'after', or 'first-child'

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        target = client.get_block(target_id)
        if target is None:
            return f"Target not found: {target_id}"
        block.move_to(target, position)
        return f"Moved {block_id} {position} {target_id}"

    @mcp.tool()
    def add_alias(
        block_id: str,
        target_page_id: str,
    ) -> str:
        """Add an alias (linked copy) of a block to a target page.

        Args:
            block_id: Block to alias
            target_page_id: Page to add the alias to

        Returns:
            Confirmation message.
        """
        client = _get_client()
        block = client.get_block(block_id)
        if block is None:
            return f"Block not found: {block_id}"
        target = client.get_block(target_page_id)
        if target is None:
            return f"Target page not found: {target_page_id}"
        alias = target.children.add_alias(block)
        return f"Added alias of {block_id} to {target_page_id}"

    @mcp.tool()
    def add_database_row(
        database_id: str,
        properties: str,
    ) -> str:
        """Add a row to a database. properties is a JSON object of column_name -> value.

        Args:
            database_id: Database block URL or ID, or collection ID
            properties: JSON object string, e.g. {"Name":"New row","Tags":["A"]}

        Returns:
            ID of the created row.
        """
        client = _get_client()
        block = client.get_block(database_id)
        collection = None
        if block is not None:
            collection = getattr(block, "collection", None)
        if collection is None:
            try:
                collection = client.get_collection(database_id)
            except Exception:
                pass
        if collection is None:
            return f"Database not found: {database_id}"
        props = json.loads(properties)
        row = collection.add_row(**props)
        return f"Created row: {row.id}"

    @mcp.tool()
    def update_database_row(
        row_id: str,
        properties: str,
    ) -> str:
        """Update a database row's properties.

        Args:
            row_id: Row block ID
            properties: JSON object string of column_name -> value

        Returns:
            Confirmation message.
        """
        client = _get_client()
        row = client.get_block(row_id)
        if row is None:
            return f"Row not found: {row_id}"
        props = json.loads(properties)
        for k, v in props.items():
            setattr(row, k, v)
        return f"Updated row {row_id}"

    @mcp.tool()
    def delete_database_row(
        row_id: str,
        permanently: bool = False,
    ) -> str:
        """Delete a database row.

        Args:
            row_id: Row block ID
            permanently: If true, permanently delete

        Returns:
            Confirmation message.
        """
        client = _get_client()
        row = client.get_block(row_id)
        if row is None:
            return f"Row not found: {row_id}"
        try:
            row.remove(permanently=permanently)
        except TypeError:
            row.remove()
        return f"Deleted row {row_id}"

    @mcp.tool()
    def create_database(
        parent_id: str,
        title: str,
        columns: str = "",
        icon: str = "",
        full_page: bool = False,
    ) -> str:
        """Create a new database (collection) under a parent page.

        Args:
            parent_id: Parent page URL or ID
            title: Database title
            columns: Optional JSON array of column definitions, e.g.
                [{"name":"Status","type":"select","options":["Todo","Done"]},
                 {"name":"Priority","type":"select","options":["High","Low"]}]
                Supported types: title, text, number, select, multi_select,
                date, person, checkbox, url, email, phone_number, file,
                relation, formula, rollup, created_time, last_edited_time,
                created_by, last_edited_by, status.
                Relation columns: {"name","type":"relation",
                "target_database_id":"<db url/id>","limit":1 (optional,
                caps the relation at one linked row),"reverse_name":
                "Backrefs" (optional, creates a two-way synced property
                on the target database)}.
                Formula columns: {"name","type":"formula",
                "expression":"if({\"Done\"}, \"✅\", \"⬜\")"} — reference
                properties with {"Name"}.
                Rollup columns: {"name","type":"rollup",
                "relation_property":"Rel","target_property":"Price",
                "aggregation":"sum"} (aggregation optional; relation/target
                resolved by property NAME).
            icon: Optional emoji icon
            full_page: If true, creates a full-page database (collection_view_page).
                If false (default), creates an inline database embedded in the page.

        Returns:
            Database block ID (use with get_database, query_database, add_database_row).
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        # Build schema from columns spec
        if columns:
            col_specs = json.loads(columns)
            space_id = client.current_space.id if client.current_space else ""
            # two-pass: pass 1 builds everything except rollups/formulas
            # (both need relation property ids from this same schema), pass 2
            # adds them. Pass 1 stamps each spec with its generated prop id
            # so pass 2 reuses the SAME ids.
            schema = _build_collection_schema(
                [s for s in col_specs if s.get("type") not in ("rollup", "formula")],
                client,
                space_id,
            )
            # formulas need fpp metas with property ids + collection pointer
            own_pointer = {
                "id": "<own>",
                "table": "collection",
                "spaceId": space_id,
            }
            for spec in col_specs:
                if spec.get("type") in ("rollup", "formula"):
                    spec["_own_schema"] = schema
                    spec["_own_pointer"] = own_pointer
                    spec["_space_id"] = space_id
            schema = _build_collection_schema(col_specs, client, space_id)
            # patch own-collection pointer into formula fpp metas now that we
            # know the real collection id (created by create_record below —
            # schema dict is built BEFORE the collection exists, so fpp metas
            # carry the placeholder; Notion resolves {name,property} fine when
            # the collection pointer matches the enclosing collection)
            # Two-way relations: a forward prop with a "property" back-ref is
            # rejected unless the reverse prop lands in the same transaction,
            # and create_record can't batch cross-collection schema writes —
            # so strip reverse-bearing relations out of the create payload and
            # write each forward+reverse pair afterwards.
            deferred = []
            for spec in col_specs:
                if spec.get("type") == "relation" and spec.get("reverse_name"):
                    fwd_pid = spec.get("id")
                    fwd = schema.pop(fwd_pid, None)
                    if fwd:
                        deferred.append((spec, fwd_pid, fwd))
        else:
            schema = {"title": {"name": "Name", "type": "title"}}
            deferred = []

        # Create database block as child of parent
        if full_page:
            cvb = parent.children.add_new(CollectionViewPageBlock)
        else:
            cvb = parent.children.add_new(CollectionViewBlock)
        collection_id = client.create_record(
            "collection", parent=cvb, schema=schema
        )
        cvb.collection = client.get_collection(collection_id)
        cvb.title = title
        if icon:
            cvb.icon = icon

        # Add a default table view
        cvb.views.add_new(view_type="table")

        # Two-way relations: forward + reverse pair in ONE transaction each
        # (autoRelate alone does not create a reverse property, and Notion
        # rejects a dangling back-reference).
        if deferred:
            from unpy.operations import build_collection_schema_update
            space_id = client.current_space.id if client.current_space else ""
            ops = [build_collection_schema_update(collection_id, fwd_pid, fwd)
                   for _, fwd_pid, fwd in deferred]
            for spec, fwd_pid, fwd in deferred:
                reverse_prop = {
                    "name": spec.get("reverse_name") or spec.get("name"),
                    "type": "relation",
                    "collection_id": collection_id,
                    "collection_pointer": {
                        "id": collection_id,
                        "table": "collection",
                        "spaceId": space_id,
                    },
                    "property": fwd_pid,
                    "version": "v2",
                    "autoRelate": {"enabled": False},
                }
                target_id = fwd.get("collection_id", "")
                if target_id and target_id != collection_id:
                    ops.append(build_collection_schema_update(
                        target_id, fwd["property"], reverse_prop
                    ))
                else:
                    # self-referencing: single prop points at itself
                    fwd["property"] = fwd_pid
                    ops = [build_collection_schema_update(
                        collection_id, fwd_pid, fwd
                    )]
            client.submit_transaction(ops)
        return cvb.id

    @mcp.tool()
    def add_column(
        database_id: str,
        name: str,
        type: str,
        options: str = "",
    ) -> str:
        """Add a column to an existing database.

        Args:
            database_id: Database URL or ID
            name: Column name
            type: Column type (title, text, number, select, multi_select,
                date, person, checkbox, url, email, phone_number, file,
                relation, created_time, last_edited_time, created_by,
                last_edited_by, status)
            options: For select/multi_select/status: JSON array of option
                values, e.g. ["High","Medium","Low"].
                For relation: JSON spec {"target_database_id":"<db url/id>",
                "limit":1 (optional, caps the relation at one linked row),
                "reverse_name":"Backrefs" (optional, creates a two-way
                synced property on the target database)}.
                For formula: JSON spec {"expression":"..."} — reference
                properties with {"Name"}.
                For rollup: JSON spec {"relation_property":"Rel",
                "target_property":"Price","aggregation":"sum"} (names, not ids).

        Returns:
            Confirmation message with the new column's property ID.
        """
        import uuid
        client = _get_client()

        # Get the collection
        block = client.get_block(database_id)
        collection = None
        if block is not None:
            collection = getattr(block, "collection", None)
        if collection is None:
            try:
                collection = client.get_collection(database_id)
            except Exception:
                pass
        if collection is None:
            return f"Database not found: {database_id}"

        # Build the new property
        prop_id = uuid.uuid4().hex[:4]
        prop = {"name": name, "type": type}
        if type in ("select", "multi_select", "status") and options:
            opts = json.loads(options)
            prop["options"] = [{"value": o, "color": "default"} for o in opts]
        if type in ("relation", "formula", "rollup"):
            # options doubles as the spec JSON for advanced column types
            spec = json.loads(options) if options else {}
            spec.setdefault("name", name)
            spec["type"] = type
            space_id = client.current_space.id if client.current_space else ""
            if type == "relation":
                prop.update(_build_relation_prop(spec, client, space_id))
                # remember where the forward prop will land so the reverse
                # property can reference it back
                spec["id"] = prop_id
                spec["_reverse_prop_id"] = prop.get("property")
            elif type == "formula":
                expr = spec.get("expression", "")
                if not expr:
                    return "formula columns need an options JSON with 'expression'"
                own_schema = collection.get("schema") or {}
                coll_ptr_id = (
                    collection.get("parent_id")
                    or getattr(collection, "id", "")
                )
                space_id = client.current_space.id if client.current_space else ""
                own_pointer = {
                    "id": getattr(collection, "id", ""),
                    "table": "collection",
                    "spaceId": space_id,
                }
                prop_meta = {}
                for pid2, p2 in own_schema.items():
                    meta = {"property": pid2}
                    if p2.get("type") == "relation":
                        tgt = p2.get("collection_id") or (
                            p2.get("collection_pointer") or {}
                        ).get("id")
                        meta["collection"] = {
                            "id": tgt,
                            "table": "collection",
                            "spaceId": space_id,
                        }
                    else:
                        meta["collection"] = own_pointer
                    prop_meta[p2.get("name", "")] = meta
                prop["version"] = "v2"
                prop["formula2"] = {
                    "code": _fev.encode_expr(expr, prop_meta),
                    "result_type": {"type": "text"},
                }
            elif type == "rollup":
                spec["_own_schema"] = collection.get("schema") or {}
                try:
                    prop.update(_build_rollup_prop(spec, client))
                except ValueError as exc:
                    return f"Cannot add rollup column: {exc}"

        # Build the write. IMPORTANT: a forward relation prop carrying
        # "property": <reverse_pid> is REJECTED (400) unless the reverse
        # property is written in the SAME transaction — Notion validates the
        # back-reference. So two-way relations must submit both ops together.
        from unpy.operations import build_collection_schema_update
        current_schema = collection.get("schema") or {}
        current_schema[prop_id] = prop

        if type == "relation" and prop.get("property"):
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
                )
            else:
                # self-referencing: one prop serves both directions — point
                # it at itself, like Notion's own self-referencing relations
                prop["property"] = prop_id
                current_schema[prop_id] = prop
                client.submit_transaction([
                    build_collection_schema_update(own_coll_id, prop_id, prop)
                ])
        else:
            client.submit_transaction([
                build_collection_schema_update(collection.id, prop_id, prop)
            ])

        return f"Added column '{name}' (type: {type}, id: {prop_id}) to database"

    @mcp.tool()
    def create_media(
        parent_id: str,
        type: str,
        url: str = "",
        file_path: str = "",
        caption: str = "",
    ) -> str:
        """Create a media block (image, video, audio, file, pdf) from a URL or file.

        Args:
            parent_id: Parent page URL or ID
            type: Media type (image, video, audio, file, pdf)
            url: Source URL (e.g. https://example.com/image.png)
            file_path: Local file path for upload (alternative to url)
            caption: Optional caption text

        Returns:
            Confirmation with the created block ID.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        TYPE_MAP = {
            "image": ImageBlock,
            "video": VideoBlock,
            "audio": AudioBlock,
            "file": FileBlock,
            "pdf": PDFBlock,
        }
        cls = TYPE_MAP.get(type)
        if cls is None:
            return f"Unsupported media type: {type} (try image, video, audio, file, pdf)"

        block = parent.children.add_new(cls)
        if file_path:
            try:
                file_path = _resolve_local_path(file_path)
            except PermissionError as e:
                return str(e)
            block.upload_file(file_path)
        elif url:
            block.source = url
            block.display_source = url
        else:
            return "Either url or file_path must be provided"
        if caption:
            block.caption = caption
        return f"Created {type} block: {block.id}"

    @mcp.tool()
    def create_embed(
        parent_id: str,
        type: str,
        url: str,
        caption: str = "",
    ) -> str:
        """Create an embed block (tweet, figma, gist, miro, html, etc.).

        Args:
            parent_id: Parent page URL or ID
            type: Embed type (embed, bookmark, tweet, gist, figma, loom,
                typeform, codepen, maps, invision, framer, drive, html,
                miro, excalidraw, replit, deepnote, sketch, abstract, mixpanel)
            url: Source URL to embed
            caption: Optional caption text

        Returns:
            Confirmation with the created block ID.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        TYPE_MAP = _embed_type_map()
        cls = TYPE_MAP.get(type)
        if cls is None:
            supported = ", ".join(sorted(TYPE_MAP.keys()))
            return f"Unsupported embed type: {type} (supported: {supported})"

        block = parent.children.add_new(cls)
        block.source = url
        block.display_source = url
        if caption:
            block.caption = caption
        return f"Created {type} embed: {block.id}"

    @mcp.tool()
    def create_table(
        parent_id: str,
        rows: int = 3,
        cols: int = 2,
    ) -> str:
        """Create a simple table (not a database) with the specified dimensions.

        Args:
            parent_id: Parent page URL or ID
            rows: Number of rows (default 3)
            cols: Number of columns (default 2)

        Returns:
            Confirmation with the created table block ID.
        """
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"

        # Notion simple tables use the "table" block type
        # The block is created with format.table_columns specifying dimensions
        import uuid
        table_id = str(uuid.uuid4())
        client.create_record(
            "block",
            parent=parent,
            type="table",
            format={"table_columns": cols, "table_blocks": []},
            id=table_id,
        )
        table = client.get_block(table_id)
        return f"Created table ({rows}x{cols}): {table_id}"

    @mcp.tool()
    def create_columns(
        parent_id: str,
        num_columns: int = 2,
    ) -> str:
        """Create a column layout with the specified number of columns.

        Creates a column_list block with N empty column blocks.
        Add content to each column by using append_blocks with the column block ID.

        Args:
            parent_id: Parent page URL or ID
            num_columns: Number of columns (1-10)

        Returns:
            Confirmation with column block IDs.
        """
        from unpy.block import ColumnListBlock, ColumnBlock
        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"
        if num_columns < 1 or num_columns > 10:
            return f"num_columns must be 1-10, got {num_columns}"

        col_list = parent.children.add_new(ColumnListBlock)
        col_ids = []
        for i in range(num_columns):
            col = col_list.children.add_new(ColumnBlock)
            col_ids.append(col.id)
        return f"Created column_list ({num_columns} columns): {col_list.id}\nColumn IDs: {', '.join(col_ids)}"

    @mcp.tool()
    def import_csv(
        parent_id: str,
        file_path: str,
        title: str = "",
    ) -> str:
        """Import a CSV file as a new database.

        Parses the CSV file locally, creates a collection with the CSV
        headers as columns (first text column becomes the title), and
        inserts all rows as database entries.

        Args:
            parent_id: Parent page URL or ID
            file_path: Path to the CSV file
            title: Database title (defaults to the filename)

        Returns:
            Confirmation with the created database block ID.
        """
        import csv as csv_mod
        import os

        client = _get_client()
        parent = client.get_block(parent_id)
        if parent is None:
            return f"Parent not found: {parent_id}"
        try:
            file_path = _resolve_local_path(file_path)
        except PermissionError as e:
            return str(e)
        try:
            db_id = _import_csv_impl(client, parent, file_path, title)
        except FileNotFoundError as e:
            return str(e)
        except ValueError as e:
            return str(e)
        return f"Imported CSV as database: {db_id}"