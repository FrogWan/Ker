from __future__ import annotations

from ker.tools.tool_base import ToolContext


def message(ctx: ToolContext, content: str, channel: str | None = None, chat_id: str | None = None) -> str:
    target_ch = channel or ctx.current_channel
    target_user = chat_id or ctx.current_user
    return f"Message queued to {target_ch}:{target_user} - {content}"
