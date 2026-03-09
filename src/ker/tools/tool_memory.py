from __future__ import annotations

from ker.tools.tool_base import ToolContext


def read_memory(ctx: ToolContext, query: str = "", top_k: int = 5, source: str = "all") -> str:
    """Search short-term memory (daily logs, chat history, session context).

    Long-term memory (MEMORY.md) is already loaded in your system prompt —
    no need to search for it.
    """
    if ctx.memory_store is None:
        return "Error: memory store not configured"
    if not query.strip():
        query = "recent memory"
    agent_name = getattr(ctx, "agent_name", "") or ""
    hits = ctx.memory_store.search_short_term(query, agent_name=agent_name, top_k=top_k, source=source)
    if not hits:
        return "No memory hits"
    return "\n".join([f"- [{h.path}] score={h.score:.3f} {h.snippet}" for h in hits])


def write_memory(ctx: ToolContext, fact: str, category: str = "general", action: str = "add") -> str:
    """Save or remove a fact from long-term memory (MEMORY.md)."""
    if ctx.memory_store is None:
        return "Error: memory store not configured"
    if not fact or not fact.strip():
        return "Error: fact cannot be empty"
    if action not in ("add", "remove"):
        return "Error: action must be 'add' or 'remove'"
    return ctx.memory_store.write_fact(fact=fact, category=category, action=action)
