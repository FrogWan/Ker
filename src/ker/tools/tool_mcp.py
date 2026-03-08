from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

from ker.logger import get_logger

log = get_logger("mcp")


class MCPToolWrapper:
    """Wraps a single MCP server tool as a Ker tool."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict,
        session: Any,
        timeout: float = 30.0,
    ) -> None:
        self.ker_name = f"mcp_{server_name}_{tool_name}"
        self.tool_name = tool_name
        self.description = description
        self.input_schema = input_schema
        self.session = session
        self.timeout = timeout

    def schema(self) -> dict:
        return {
            "name": self.ker_name,
            "description": f"[MCP:{self.tool_name}] {self.description}",
            "input_schema": self.input_schema,
        }

    async def execute(self, **kwargs: Any) -> str:
        try:
            result = await asyncio.wait_for(
                self.session.call_tool(self.tool_name, kwargs),
                timeout=self.timeout,
            )
            parts: list[str] = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else "(empty MCP result)"
        except asyncio.TimeoutError:
            return f"Error: MCP tool {self.tool_name} timed out after {self.timeout}s"
        except Exception as exc:
            return f"Error: MCP tool {self.tool_name} failed: {exc}"


async def connect_mcp_servers(
    config: dict[str, dict],
    registry: Any,
    stack: AsyncExitStack,
) -> list[MCPToolWrapper]:
    """Connect to configured MCP servers and register their tools.

    Args:
        config: Dict of server_name -> server config. Each config can have:
            - command/args/env: for stdio transport
            - url/headers: for HTTP transport
            - tool_timeout: per-tool timeout in seconds (default 30)
        registry: ToolRegistry instance to register tools into.
        stack: AsyncExitStack to manage server lifetimes.

    Returns:
        List of MCPToolWrapper instances that were registered.
    """
    if not config:
        return []

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        log.warning("mcp package not installed; skipping MCP server connections")
        return []

    wrappers: list[MCPToolWrapper] = []

    for server_name, srv_cfg in config.items():
        try:
            tool_timeout = float(srv_cfg.get("tool_timeout", 30))

            if "command" in srv_cfg:
                params = StdioServerParameters(
                    command=srv_cfg["command"],
                    args=srv_cfg.get("args", []),
                    env=srv_cfg.get("env"),
                )
                transport = await stack.enter_async_context(stdio_client(params))
                read_stream, write_stream = transport
                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
            elif "url" in srv_cfg:
                try:
                    from mcp.client.streamable_http import streamablehttp_client
                except ImportError:
                    log.warning("streamable HTTP client not available for MCP server %s", server_name)
                    continue
                transport = await stack.enter_async_context(
                    streamablehttp_client(
                        url=srv_cfg["url"],
                        headers=srv_cfg.get("headers"),
                    )
                )
                read_stream, write_stream, _ = transport
                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
            else:
                log.warning("MCP server %s has no command or url; skipping", server_name)
                continue

            await session.initialize()
            tools_result = await session.list_tools()

            for tool in tools_result.tools:
                wrapper = MCPToolWrapper(
                    server_name=server_name,
                    tool_name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {"type": "object", "properties": {}},
                    session=session,
                    timeout=tool_timeout,
                )
                registry.register(wrapper.ker_name, wrapper.schema(), wrapper.execute)
                wrappers.append(wrapper)

            log.info(
                "Connected MCP server '%s': %d tools registered",
                server_name,
                len(tools_result.tools),
            )
        except Exception as exc:
            log.error("Failed to connect MCP server '%s': %s", server_name, exc)

    return wrappers
