"""CSV → inline database import shared by unpy-mcp and unpy-cli (issue #32)."""

from __future__ import annotations


def import_csv_impl(client, parent, file_path: str, title: str = "") -> str:
    """Shared CSV→inline-database import (used by MCP tool and CLI)."""
    import csv as csv_mod
    import os

    from unpy.block import CollectionViewBlock
    from unpy.config import legacy_mode
    from unpy.utils import slugify

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
        if title_prop_id is None:
            # title prop must have id "title" or Notion adds a phantom one (issue #6)
            schema["title"] = {"name": h, "type": "title"}
            title_prop_id = "title"
        else:
            schema[f"col{i:04x}"] = {"name": h, "type": "text"}
    if title_prop_id is None:
        schema["title"] = {"name": "Name", "type": "title"}
        title_prop_id = "title"

    cvb = parent.children.add_new(CollectionViewBlock)
    collection_id = client.create_record("collection", parent=cvb, schema=schema)
    cvb.collection = client.get_collection(collection_id)
    cvb.title = title
    cvb.views.add_new(view_type="table")

    title_slug = slugify(schema[title_prop_id]["name"])
    v2_batch = not legacy_mode() and len(rows_data) > 1
    if v2_batch:
        # v2: buffer ALL row creates + property writes + page_sort updates
        # into one batched transaction (flushed in capped chunks) — a 10k-row
        # CSV costs ~ceil(10k ops / cap) HTTP calls instead of ~10k+.
        collection = cvb.collection
        with client.batched_transaction():
            for row in rows_data:
                props = {}
                for i, val in enumerate(row):
                    if i < len(headers):
                        if i == 0:
                            props[title_slug] = val
                        else:
                            props[slugify(headers[i])] = val
                try:
                    collection.add_row(**props)
                except Exception:
                    pass  # Skip rows that fail
    else:
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