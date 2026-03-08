from __future__ import annotations

from datetime import datetime
from pathlib import Path


BOOTSTRAP_FILES = [
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
    "TOOLS.md",
    "AGENTS.md",
    "BOOT.md",
]

# Which files to include per session type
SESSION_INCLUDES: dict[str, set[str]] = {
    "main": {"IDENTITY.md", "SOUL.md", "USER.md", "TOOLS.md", "AGENTS.md", "BOOT.md"},
    "subagent": {"IDENTITY.md", "TOOLS.md"},
    "cron": {"IDENTITY.md", "TOOLS.md"},
    "internal": {"IDENTITY.md"},
}

BUILTIN_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "memory" / "templates"


class PromptBuilder:
    def __init__(self, ker_root: Path, per_file_cap: int = 20_000, total_cap: int = 150_000) -> None:
        self.ker_root = ker_root
        self.per_file_cap = per_file_cap
        self.total_cap = total_cap

    def _agent_dir(self, agent_name: str) -> Path:
        return self.ker_root / "agents" / agent_name

    def _smart_truncate(self, text: str, cap: int) -> tuple[str, bool]:
        """Truncate keeping head 70% + tail 20%, with a marker in between."""
        if len(text) <= cap:
            return text, False
        head_size = int(cap * 0.70)
        tail_size = int(cap * 0.20)
        removed = len(text) - head_size - tail_size
        marker = f"\n...[truncated: {removed} chars removed]...\n"
        # Adjust for marker length
        available = cap - len(marker)
        if available < 20:
            return text[:cap], True
        head_size = int(available * 0.78)  # 70/(70+20) ≈ 0.78
        tail_size = available - head_size
        return text[:head_size] + marker + text[-tail_size:], True

    def _read_capped(self, path: Path) -> tuple[str, bool]:
        """Read file with smart truncation. Returns (text, was_truncated)."""
        text = path.read_text(encoding="utf-8")
        return self._smart_truncate(text, self.per_file_cap)

    def _load_user_md(self, agent_name: str) -> tuple[str, bool] | None:
        """Load USER.md with multi-source fallback: agent → workspace → builtin."""
        candidates = [
            self._agent_dir(agent_name) / "USER.md",
            self.ker_root / "USER.md",
            BUILTIN_TEMPLATES_DIR / "USER.md",
        ]
        for path in candidates:
            if path.exists():
                return self._read_capped(path)
        return None

    def _load_bootstrap(self, agent_name: str, session_type: str = "main") -> dict[str, str]:
        agent_dir = self._agent_dir(agent_name)
        includes = SESSION_INCLUDES.get(session_type, SESSION_INCLUDES["main"])
        loaded: dict[str, str] = {}
        warnings: list[str] = []
        total = 0

        for name in BOOTSTRAP_FILES:
            if name not in includes:
                continue

            # USER.md has special multi-source loading
            if name == "USER.md":
                result = self._load_user_md(agent_name)
                if result is None:
                    continue
                text, truncated = result
            else:
                agent_file = agent_dir / name
                builtin_file = BUILTIN_TEMPLATES_DIR / name

                if agent_file.exists():
                    text, truncated = self._read_capped(agent_file)
                elif builtin_file.exists():
                    text, truncated = self._read_capped(builtin_file)
                else:
                    continue

            if truncated:
                warnings.append(f"[Warning: {name} truncated to {self.per_file_cap} chars]")

            if total + len(text) > self.total_cap:
                text, _ = self._smart_truncate(text, max(0, self.total_cap - total))
            total += len(text)
            loaded[name] = text
            if total >= self.total_cap:
                break

        # Also load AGENT.md if present
        agent_md = agent_dir / "AGENT.md"
        if agent_md.exists() and total < self.total_cap:
            text, truncated = self._read_capped(agent_md)
            if truncated:
                warnings.append(f"[Warning: AGENT.md truncated to {self.per_file_cap} chars]")
            if total + len(text) > self.total_cap:
                text, _ = self._smart_truncate(text, max(0, self.total_cap - total))
            loaded["AGENT.md"] = text

        if warnings:
            loaded["_warnings"] = "\n".join(warnings)

        return loaded

    # ── Section builders ────────────────────────────────────────────

    def _build_identity(self, bootstrap: dict[str, str]) -> str | None:
        identity = bootstrap.get("IDENTITY.md", "").strip()
        return identity if identity else "You are a helpful AI assistant."

    def _build_agent(self, bootstrap: dict[str, str]) -> str | None:
        agent_md = bootstrap.get("AGENT.md", "").strip()
        return agent_md or None

    def _build_soul(self, bootstrap: dict[str, str]) -> str | None:
        soul = bootstrap.get("SOUL.md", "").strip()
        return "## Personality\n\n" + soul if soul else None

    def _build_user(self, bootstrap: dict[str, str]) -> str | None:
        user = bootstrap.get("USER.md", "").strip()
        return "## User Profile\n\n" + user if user else None

    def _build_tools(self, bootstrap: dict[str, str]) -> str | None:
        tools_md = bootstrap.get("TOOLS.md", "").strip()
        return "## Tool Usage Guidelines\n\n" + tools_md if tools_md else None

    def _build_skills(self, skills_block: str) -> str | None:
        return skills_block or None

    def _build_memory(self, memory_context: str) -> str | None:
        memory_md_path = self.ker_root / "MEMORY.md"
        memory_parts: list[str] = []
        if memory_md_path.exists():
            memory_md = memory_md_path.read_text(encoding="utf-8").strip()
            if memory_md:
                memory_parts.append("### Evergreen Memory\n" + memory_md)
        if memory_context:
            memory_parts.append(
                "### Recalled Memory\n"
                "Before answering, review these recalled memory fragments.\n"
                "If confidence is low, mention that you checked memory but aren't certain.\n\n"
                + memory_context
            )
        return "## Memory\n\n" + "\n\n".join(memory_parts) if memory_parts else None

    def _build_agents(self, bootstrap: dict[str, str]) -> str | None:
        v = bootstrap.get("AGENTS.md", "").strip()
        return "## Bootstrap Context\n\n### AGENTS.md\n" + v if v else None

    def _build_guardrails(self) -> str:
        return (
            "## Execution Guardrails\n"
            "- State intent before tool calls.\n"
            "- Never claim tool results before receiving them.\n"
            "- If a tool fails, analyze the error and retry with a different approach.\n"
            "- Re-read modified files when correctness matters.\n"
            "- Prefer reversible operations; ask before destructive ones.\n"
            "- When uncertain, say so and suggest options.\n"
            "- Don't loop on the same failing approach — try something different."
        )

    def _build_boot(self, bootstrap: dict[str, str]) -> str | None:
        boot = bootstrap.get("BOOT.md", "").strip()
        return "## Startup Instructions\n\n" + boot if boot else None

    def _build_runtime(
        self, agent_name: str, model_id: str, channel: str, session_name: str, session_type: str
    ) -> str:
        lines = [
            "## Runtime Context",
            f"- agent: {agent_name}",
            f"- model: {model_id}",
            f"- channel: {channel}",
            f"- session: {session_name}",
            f"- session_type: {session_type}",
            f"- timestamp: {datetime.now().isoformat()}",
        ]
        return "\n".join(lines)

    def _build_channel(self, channel: str) -> str:
        return f"## Channel Hints\nYou are responding via {channel}."

    # ── Main build ──────────────────────────────────────────────────

    def build(
        self,
        agent_name: str,
        skills_block: str = "",
        memory_context: str = "",
        model_id: str = "",
        channel: str = "cli",
        session_name: str = "default",
        session_type: str = "main",
    ) -> str:
        bootstrap = self._load_bootstrap(agent_name, session_type=session_type)
        includes = SESSION_INCLUDES.get(session_type, SESSION_INCLUDES["main"])

        sections: list[str] = []

        # Context injection markers
        sections.append("===== PROJECT CONTEXT STARTS =====")

        # Identity — always included
        identity = self._build_identity(bootstrap)
        if identity:
            sections.append(identity)

        # AGENT.md — always included if present
        agent_section = self._build_agent(bootstrap)
        if agent_section:
            sections.append(agent_section)

        # Soul — main only
        if "SOUL.md" in includes:
            soul = self._build_soul(bootstrap)
            if soul:
                sections.append(soul)

        # User profile — main only
        if "USER.md" in includes:
            user = self._build_user(bootstrap)
            if user:
                sections.append(user)

        # Tools — main, subagent, cron
        if "TOOLS.md" in includes:
            tools = self._build_tools(bootstrap)
            if tools:
                sections.append(tools)

        # Skills — main, subagent, cron
        if session_type != "internal":
            skills = self._build_skills(skills_block)
            if skills:
                sections.append(skills)

        # Memory — main only
        if session_type == "main":
            memory = self._build_memory(memory_context)
            if memory:
                sections.append(memory)

        # Agents operational manual — main only
        if "AGENTS.md" in includes:
            agents = self._build_agents(bootstrap)
            if agents:
                sections.append(agents)

        # Guardrails — always
        sections.append(self._build_guardrails())

        # Boot instructions — main only
        if "BOOT.md" in includes:
            boot = self._build_boot(bootstrap)
            if boot:
                sections.append(boot)

        # Truncation warnings
        warnings = bootstrap.get("_warnings", "").strip()
        if warnings:
            sections.append(warnings)

        sections.append("===== PROJECT CONTEXT ENDS =====")

        # Runtime and channel — always included (outside context markers)
        sections.append(self._build_runtime(agent_name, model_id, channel, session_name, session_type))
        sections.append(self._build_channel(channel))

        return "\n\n".join(sections)
