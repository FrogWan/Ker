from __future__ import annotations

import asyncio

from ker.tools.tool_base import ToolContext


def spawn(ctx: ToolContext, task: str, label: str | None = None) -> str:
    if ctx.subagent_manager is None:
        return "Error: subagent manager not configured"
    # spawn is async, but we're called from sync context via asyncio.to_thread
    # Schedule the coroutine on the running event loop
    loop = asyncio.get_event_loop()
    future = asyncio.run_coroutine_threadsafe(
        ctx.subagent_manager.spawn(
            task=task,
            label=label,
            channel=ctx.current_channel,
            user=ctx.current_user,
            session_key=f"{ctx.agent_name}_{ctx.session_name}",
        ),
        loop,
    )
    return future.result(timeout=5)
