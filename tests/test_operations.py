"""Unit tests for operations.py — build_operation + operation_update_last_edited."""

import time

from notion.operations import build_operation, operation_update_last_edited


class TestBuildOperation:
    def test_basic_set(self):
        op = build_operation(
            id="block-123",
            path=["title"],
            args={"value": "hello"},
            command="set",
            table="block",
        )
        assert op["id"] == "block-123"
        assert op["path"] == ["title"]
        assert op["args"] == {"value": "hello"}
        assert op["command"] == "set"
        assert op["table"] == "block"

    def test_defaults(self):
        op = build_operation(id="b1", path=[], args={"alive": True})
        assert op["command"] == "set"
        assert op["table"] == "block"

    def test_path_as_string(self):
        op = build_operation(id="b1", path="content.0", args={"id": "child"})
        assert op["path"] == ["content", "0"]

    def test_list_after(self):
        op = build_operation(
            id="parent-1",
            path=["content"],
            args={"id": "child-1"},
            command="listAfter",
            table="block",
        )
        assert op["command"] == "listAfter"
        assert op["path"] == ["content"]


class TestOperationUpdateLastEdited:
    def test_structure(self):
        op = operation_update_last_edited("user-123", "block-456")
        assert op["id"] == "block-456"
        assert op["table"] == "block"
        assert op["command"] == "update"
        assert op["path"] == []
        assert op["args"]["last_edited_by_id"] == "user-123"
        assert op["args"]["last_edited_by_table"] == "notion_user"
        assert isinstance(op["args"]["last_edited_time"], int)

    def test_timestamp_is_recent(self):
        before = int(time.time() * 1000)
        op = operation_update_last_edited("u1", "b1")
        after = int(time.time() * 1000)
        ts = op["args"]["last_edited_time"]
        assert before <= ts <= after