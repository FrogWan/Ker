from __future__ import annotations

from ker.tools.tool_base import ToolContext


def read_memory(ctx: ToolContext, query: str = "", top_k: int = 5, source: str = "all") -> str:
    """Search short-term memory (daily logs, episodes, chat history, session context).

    Long-term memory (MEMORY.md) is already loaded in your system prompt —
    no need to search for it.
    """
    if ctx.memory_store is None:
        return "Error: memory store not configured"

    agent_name = getattr(ctx, "agent_name", "") or ""

    # Handle new source options
    if source == "working":
        if ctx.working_memory is None:
            return "Working memory not configured"
        return ctx.working_memory.render_for_prompt(agent_name) or "No working context"

    if source == "episodes":
        if not ctx.memory_store.episodes_path.exists():
            return "No episodes found"
        episodes = ctx.memory_store._load_episodes()
        if not episodes:
            return "No episodes found"
        if query.strip():
            from ker.agent.context.scorer import MemoryScorer
            chunks = [{
                "path": "episodes.jsonl",
                "text": ep.get("summary", ""),
                "ts": float(ep.get("ts", 0.0)),
                "importance": float(ep.get("importance", 0.5)),
                "source": "episodes",
            } for ep in episodes]
            hits = MemoryScorer.score(chunks, query, top_k)
            return "\n".join([f"- [ep] score={h.score:.3f} {h.snippet}" for h in hits]) or "No matching episodes"
        # No query: return recent episodes
        recent = episodes[-top_k:]
        return "\n".join([
            f"- [{ep.get('date', '?')}] {ep.get('summary', '')[:200]} (tags: {', '.join(ep.get('tags', []))})"
            for ep in reversed(recent)
        ])

    if not query.strip():
        query = "recent memory"

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


def memory_status(ctx: ToolContext, aspect: str = "overview", topic: str = "") -> str:
    """Introspect memory: see what you know, what you're working on, memory stats."""
    if ctx.memory_store is None:
        return "Error: memory store not configured"

    agent_name = getattr(ctx, "agent_name", "") or ""

    if aspect == "working":
        if ctx.working_memory is None:
            return "Working memory not configured"
        rendered = ctx.working_memory.render_for_prompt(agent_name)
        return rendered or "No active working context"

    if aspect == "stats":
        stats = ctx.memory_store.get_stats()
        lines = [
            "## Memory Stats",
            f"- Long-term facts: {stats.get('long_term_facts', 0)} ({stats.get('long_term_size', 0)} bytes)",
            f"- Daily files: {stats.get('daily_files', 0)} ({stats.get('daily_entries', 0)} entries)",
            f"- Episodes: {stats.get('episode_count', 0)}",
            f"- Error log entries: {stats.get('error_entries', 0)}",
        ]
        return "\n".join(lines)

    if aspect == "recent":
        parts: list[str] = []

        # Last 5 daily entries
        daily_dir = ctx.memory_store.ker_root / "memory" / "daily"
        if daily_dir.exists():
            import json
            entries: list[dict] = []
            for p in sorted(daily_dir.glob("*.jsonl"), reverse=True)[:2]:
                for line in reversed(p.read_text(encoding="utf-8").splitlines()):
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if len(entries) >= 5:
                        break
                if len(entries) >= 5:
                    break
            if entries:
                parts.append("### Recent Daily Entries")
                for e in entries:
                    parts.append(f"- [{e.get('time', '?')}] {e.get('text', '')[:150]}")

        # Last 3 episodes
        episodes = ctx.memory_store._load_episodes()
        if episodes:
            parts.append("### Recent Episodes")
            for ep in episodes[-3:]:
                parts.append(f"- [{ep.get('date', '?')}] {ep.get('summary', '')[:200]}")

        return "\n".join(parts) if parts else "No recent memory entries"

    if aspect == "about":
        if not topic.strip():
            return "Error: 'topic' is required for aspect='about'"
        # Cross-tier search
        results: list[str] = []

        # Search long-term (MEMORY.md)
        long_term = ctx.memory_store.read_long_term()
        if topic.lower() in long_term.lower():
            # Extract matching lines
            for line in long_term.splitlines():
                if topic.lower() in line.lower():
                    results.append(f"[long-term] {line.strip()}")

        # Search episodes
        from ker.agent.context.scorer import MemoryScorer
        episodes = ctx.memory_store._load_episodes()
        if episodes:
            ep_chunks = [{
                "path": "episodes.jsonl",
                "text": ep.get("summary", ""),
                "ts": float(ep.get("ts", 0.0)),
                "importance": float(ep.get("importance", 0.5)),
                "source": "episodes",
            } for ep in episodes]
            ep_hits = MemoryScorer.score(ep_chunks, topic, top_k=2)
            for h in ep_hits:
                results.append(f"[episode] score={h.score:.3f} {h.snippet[:200]}")

        # Search short-term
        st_hits = ctx.memory_store.search_short_term(topic, agent_name=agent_name, top_k=3)
        for h in st_hits:
            results.append(f"[short-term] score={h.score:.3f} {h.snippet[:200]}")

        return "\n".join(results[:5]) if results else f"No memory found about '{topic}'"

    # aspect == "overview" (default)
    parts = []

    # Working context
    if ctx.working_memory:
        wc = ctx.working_memory.render_for_prompt(agent_name)
        if wc:
            parts.append("### Working Context\n" + wc)

    # Today summary
    import json
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = ctx.memory_store.ker_root / "memory" / "daily" / f"{today}.jsonl"
    if daily_file.exists():
        count = sum(1 for line in daily_file.read_text(encoding="utf-8").splitlines() if line.strip())
        parts.append(f"### Today\n- {count} daily entries logged")

    # Stats
    stats = ctx.memory_store.get_stats()
    parts.append(
        f"### Memory Tiers\n"
        f"- Facts: {stats.get('long_term_facts', 0)}\n"
        f"- Daily: {stats.get('daily_entries', 0)} entries\n"
        f"- Episodes: {stats.get('episode_count', 0)}\n"
        f"- Errors: {stats.get('error_entries', 0)}"
    )

    return "\n".join(parts) if parts else "Memory system active, no entries yet"
