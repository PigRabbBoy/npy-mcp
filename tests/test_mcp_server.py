"""Tests for MCP server — in-memory client, no HTTP transport needed.

Uses MCP SDK v2's in-memory Client to connect directly to the server object.
"""

import os

import pytest
from mcp import Client


@pytest.fixture
def mcp_server(monkeypatch):
    """Build the MCP server with a fake token."""
    monkeypatch.setenv("NOTION_TOKEN_V2", "test-token-not-real")
    monkeypatch.setenv("NOTION_TOKEN", "test-token-not-real")
    monkeypatch.delenv("NOTION_ALLOW_WRITE", raising=False)
    import importlib
    import notion_mcp.server
    importlib.reload(notion_mcp.server)
    return notion_mcp.server.mcp


class TestToolRegistration:
    @pytest.mark.asyncio
    async def test_read_tools_registered(self, mcp_server):
        """Without NOTION_ALLOW_WRITE, only 7 read tools should be registered."""
        async with Client(mcp_server) as client:
            result = await client.list_tools()
            tool_names = [t.name for t in result.tools]
            assert "search" in tool_names
            assert "get_page" in tool_names
            assert "get_block" in tool_names
            assert "get_image" in tool_names
            assert "list_pages" in tool_names
            assert "get_database" in tool_names
            assert "query_database" in tool_names
            assert "create_page" not in tool_names
            assert "delete_block" not in tool_names

    @pytest.mark.asyncio
    async def test_read_tool_count(self, mcp_server):
        async with Client(mcp_server) as client:
            result = await client.list_tools()
            assert len(result.tools) == 7


class TestWriteGate:
    @pytest.mark.asyncio
    async def test_write_tools_when_enabled(self, monkeypatch):
        """With NOTION_ALLOW_WRITE=1, all 21 tools should be registered."""
        monkeypatch.setenv("NOTION_TOKEN_V2", "test-token")
        monkeypatch.setenv("NOTION_ALLOW_WRITE", "1")
        import importlib
        import notion_mcp.server
        importlib.reload(notion_mcp.server)
        mcp = notion_mcp.server.mcp
        async with Client(mcp) as client:
            result = await client.list_tools()
            tool_names = [t.name for t in result.tools]
            assert len(result.tools) == 21
            assert "create_page" in tool_names
            assert "delete_block" in tool_names
            assert "add_database_row" in tool_names
            assert "create_database" in tool_names
            assert "add_column" in tool_names
            assert "create_media" in tool_names
            assert "create_embed" in tool_names
            assert "create_table" in tool_names


class TestToolSchemas:
    @pytest.mark.asyncio
    async def test_search_schema(self, mcp_server):
        async with Client(mcp_server) as client:
            result = await client.list_tools()
            search_tool = next(t for t in result.tools if t.name == "search")
            schema = search_tool.input_schema
            assert "query" in schema.get("properties", {})
            assert "limit" in schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_get_page_schema(self, mcp_server):
        async with Client(mcp_server) as client:
            result = await client.list_tools()
            page_tool = next(t for t in result.tools if t.name == "get_page")
            schema = page_tool.input_schema
            assert "page_id" in schema.get("properties", {})
            assert "depth" in schema.get("properties", {})


class TestBlockTypes:
    def test_block_types_registered(self):
        """Verify all expected block type classes are registered."""
        from notion.block import BLOCK_TYPES
        expected = [
            "text", "to_do", "header", "sub_header", "sub_sub_header",
            "sub_sub_sub_header", "bulleted_list", "numbered_list", "toggle",
            "quote", "code", "callout", "divider", "equation",
            "image", "video", "audio", "file", "pdf",
            "embed", "bookmark", "tweet", "gist", "figma", "loom",
            "typeform", "codepen", "maps", "invision", "framer",
            "html", "miro", "excalidraw", "replit", "deepnote",
            "sketch", "abstract", "mixpanel",
            "column", "column_list", "synced_block",
            "breadcrumb", "factory", "link_to_collection", "link_to_page",
            "table_of_contents", "simple_table",
            "page", "collection_view", "collection_view_page",
        ]
        for t in expected:
            assert t in BLOCK_TYPES, f"Block type '{t}' not registered"
        assert len(BLOCK_TYPES) >= 50