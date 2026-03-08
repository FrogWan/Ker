from __future__ import annotations

import time

from ker.tools.tool_base import ToolContext


def read_memory(ctx: ToolContext, query: str = "", top_k: int = 5) -> str:
    if ctx.memory_store is None:
        return "Error: memory store not configured"
    if not query.strip():
        query = "recent memory"
    hits = ctx.memory_store.search_memory(query, top_k=top_k)
    if not hits:
        return "No memory hits"
    return "\n".join([f"- [{h.path}] score={h.score:.3f} {h.snippet}" for h in hits])


def read_error_log(ctx: ToolContext, limit: int = 50) -> str:
    if ctx.memory_store is None:
        return "Error: memory store not configured"
    rows = ctx.memory_store.read_error_log(limit=limit)
    if not rows:
        return "No error logs"
    lines = []
    for row in rows:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(row.get("ts", 0.0))))
        lines.append(f"- [{ts}] {row.get('source', 'unknown')}: {row.get('message', '')}")
    return "\n".join(lines)
