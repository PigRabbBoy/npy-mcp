"""Shared property-value rendering — used by both the MCP server and the CLI.

Converts Notion Python objects (User, CollectionRowBlock, NotionDate, ...)
into readable strings instead of leaking raw Python reprs.
"""

from __future__ import annotations


def render_property(value) -> str:
    """Render a Notion property value to a readable string.

    Handles common Notion types that would otherwise leak Python repr:
    - User → email or name (not "<User ...>")
    - CollectionRowBlock → row title + id/URL (not "<CollectionRowBlock ...>")
    - NotionDate → ISO date string
    - list → comma-joined rendered items
    - None → empty string
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(render_property(v) for v in value)
    # CollectionRowBlock — check before User since both have .id/.email/.role
    if hasattr(value, "title_plaintext") and hasattr(value, "id"):
        title = value.title_plaintext or ""
        url = (
            value.get_browseable_url()
            if hasattr(value, "get_browseable_url")
            else ""
        )
        if title and url:
            return f"{title} ({url})"
        return title or url or value.id
    # User — has .email/.role but NOT .title_plaintext
    # Use .get() not property attrs — property attrs are lazy/cached and may
    # return stale empty values even when store data is populated.
    if hasattr(value, "email") and hasattr(value, "role"):
        email = value.get("email") or "" if hasattr(value, "get") else ""
        name = value.get("name") or "" if hasattr(value, "get") else ""
        if name:
            return str(name)
        if email:
            return str(email)
        return getattr(value, "id", str(value))
    # NotionDate — has start/end attributes
    if hasattr(value, "start") and hasattr(value, "end") and hasattr(value, "timezone"):
        start = value.start
        end = value.end
        if start and end:
            return f"{start} → {end}"
        return str(start or end or "")
    # Fallback: str() but strip memory addresses
    s = str(value)
    if " object at 0x" in s:
        return s.split(" object at ")[0].split(".")[-1]
    return s


def render_properties(props: dict) -> dict:
    """Render every value of a property dict (returns {slug: str})."""
    return {k: render_property(v) for k, v in props.items()}