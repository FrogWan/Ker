from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ker.logger import get_logger

log = get_logger("working_memory")

WORKING_CONTEXT_MAX_CHARS = 4_000
SESSION_RECORDS_TO_SCAN = 10


@dataclass
class WorkingContext:
    task: str = ""
    decisions: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    last_tools: list[str] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "decisions": self.decisions,
            "pending": self.pending,
            "last_tools": self.last_tools,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkingContext:
        return cls(
            task=d.get("task", ""),
            decisions=d.get("decisions", []),
            pending=d.get("pending", []),
            last_tools=d.get("last_tools", []),
            updated_at=float(d.get("updated_at", 0.0)),
        )


class WorkingMemoryManager:
    def __init__(self, ker_root: Path) -> None:
        self.ker_root = ker_root

    def _context_path(self, agent_name: str) -> Path:
        return self.ker_root / "agents" / agent_name / "working_context.json"

    def load(self, agent_name: str) -> WorkingContext:
        path = self._context_path(agent_name)
        if not path.exists():
            return WorkingContext()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WorkingContext.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load working context for %s: %s", agent_name, exc)
            return WorkingContext()

    def save(self, agent_name: str, ctx: WorkingContext) -> None:
        path = self._context_path(agent_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        ctx.updated_at = time.time()
        path.write_text(json.dumps(ctx.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def update_from_turn(
        self,
        agent_name: str,
        session_id: str,
        session_store: object,
    ) -> None:
        """Update working context by reading recent session records."""
        ctx = self.load(agent_name)

        # Read last N session records
        records = []
        if hasattr(session_store, "load_messages"):
            messages = session_store.load_messages(agent_name, session_id)
            records = messages[-SESSION_RECORDS_TO_SCAN:]

        # Extract task from the most recent user message
        for msg in reversed(records):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    # Use first user message as task hint (truncate)
                    ctx.task = content.strip()[:300]
                    break

        # Extract tool calls from assistant messages
        tools_seen: list[str] = []
        for msg in records:
            if msg.get("role") == "assistant":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            brief = ""
                            if isinstance(inp, dict):
                                # Extract a brief hint from input
                                for key in ("command", "path", "query", "action", "task", "fact"):
                                    if key in inp:
                                        val = str(inp[key])[:60]
                                        brief = f" {key}={val}"
                                        break
                            tools_seen.append(f"{name}{brief}")

        ctx.last_tools = tools_seen[-10:]  # Keep last 10 tool calls

        self.save(agent_name, ctx)

    def clear(self, agent_name: str) -> None:
        path = self._context_path(agent_name)
        if path.exists():
            path.unlink()

    def render_for_prompt(self, agent_name: str) -> str:
        """Render working context as compact markdown, max WORKING_CONTEXT_MAX_CHARS."""
        ctx = self.load(agent_name)

        # Don't render if empty
        if not ctx.task and not ctx.decisions and not ctx.pending and not ctx.last_tools:
            return ""

        parts: list[str] = []

        if ctx.task:
            parts.append(f"**Current task:** {ctx.task}")

        if ctx.decisions:
            items = "\n".join(f"  - {d}" for d in ctx.decisions[-5:])
            parts.append(f"**Decisions:**\n{items}")

        if ctx.pending:
            items = "\n".join(f"  - {p}" for p in ctx.pending[-5:])
            parts.append(f"**Pending:**\n{items}")

        if ctx.last_tools:
            items = ", ".join(ctx.last_tools[-5:])
            parts.append(f"**Recent tools:** {items}")

        text = "\n".join(parts)
        if len(text) > WORKING_CONTEXT_MAX_CHARS:
            text = text[:WORKING_CONTEXT_MAX_CHARS - 20] + "\n...(truncated)"

        return text
