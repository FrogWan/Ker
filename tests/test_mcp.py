import asyncio
import pytest
from pathlib import Path
from ker.tools.tool_registry import ToolRegistry
from ker.tools.tool_base import ToolContext


def test_dynamic_registration(tmp_path: Path):
    """Verify tools can be registered and unregistered at runtime."""
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    registry = ToolRegistry(ctx)

    initial_count = len(registry.schemas)

    # Register a dynamic tool
    registry.register(
        "test_tool",
        {"name": "test_tool", "description": "Test", "input_schema": {"type": "object", "properties": {}}},
        lambda: "test result",
    )

    assert len(registry.schemas) == initial_count + 1
    assert any(s["name"] == "test_tool" for s in registry.schemas)

    # Unregister
    registry.unregister("test_tool")
    assert len(registry.schemas) == initial_count
    assert not any(s["name"] == "test_tool" for s in registry.schemas)


@pytest.mark.asyncio
async def test_execute_dynamic_sync_handler(tmp_path: Path):
    """Verify executing a dynamically registered sync handler."""
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    registry = ToolRegistry(ctx)

    registry.register(
        "sync_test",
        {"name": "sync_test", "description": "Sync test", "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        lambda x="default": f"got {x}",
    )

    result = await registry.execute("sync_test", {"x": "hello"})
    assert result == "got hello"


@pytest.mark.asyncio
async def test_execute_dynamic_async_handler(tmp_path: Path):
    """Verify executing a dynamically registered async handler."""
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    registry = ToolRegistry(ctx)

    async def async_handler(x="default"):
        return f"async got {x}"

    registry.register(
        "async_test",
        {"name": "async_test", "description": "Async test", "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}}},
        async_handler,
    )

    result = await registry.execute("async_test", {"x": "world"})
    assert result == "async got world"


@pytest.mark.asyncio
async def test_execute_unknown_tool(tmp_path: Path):
    """Verify error message for unknown tool."""
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    registry = ToolRegistry(ctx)

    result = await registry.execute("nonexistent", {})
    assert "Unknown tool" in result


def test_mcp_placeholder_removed(tmp_path: Path):
    """Verify the static MCP placeholder is no longer in TOOLS."""
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    registry = ToolRegistry(ctx)

    tool_names = [s["name"] for s in registry.schemas]
    assert "mcp" not in tool_names
