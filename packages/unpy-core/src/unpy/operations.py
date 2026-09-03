from .utils import now


def build_operation(id, path, args, command="set", table="block"):
    """
    Data updates sent to the submitTransaction endpoint consist of a sequence of "operations". This is a helper
    function that constructs one of these operations.
    """

    if isinstance(path, str):
        path = path.split(".")

    return {"id": id, "path": path, "args": args, "command": command, "table": table}


def build_collection_schema_update(collection_id, prop_id, prop_args):
    """
    Build an operation that updates one property in a collection's schema.

    Notion's current API rejects plain "set"/"update" commands against the
    schema path (400) — schema changes must use the dedicated
    "updateCollectionPropertySchema" command with a "primitiveOp" wrapper.
    This mirrors what the Notion web client sends (captured live from
    CollectionSettingsSetupRelation.handleAddRelation).
    """
    return {
        "id": collection_id,
        "path": ["schema"],
        "table": "collection",
        "command": "updateCollectionPropertySchema",
        "args": {"primitiveOp": {"command": "update", "args": {prop_id: prop_args}}},
    }


def operation_update_last_edited(user_id, block_id):
    """
    When transactions are submitted from the web UI, it also includes an operation to update the "last edited"
    fields, so we want to send those too, for consistency -- this convenience function constructs the operation.
    """
    return {
        "args": {
            "last_edited_by_id": user_id,
            "last_edited_by_table": "notion_user",
            "last_edited_time": now(),
        },
        "command": "update",
        "id": block_id,
        "path": [],
        "table": "block",
    }
