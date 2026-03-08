from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ker.agent.context.memory import MemoryStore
    from ker.agent.context.skills import SkillsManager
    from ker.agent.subagent import SubagentManager
    from ker.longtask.orchestrator import LongTaskOrchestrator
    from ker.scheduler.cron import CronService


@dataclass
class ToolContext:
    workspace: Path
    ker_root: Path = field(default_factory=lambda: Path.cwd() / ".ker")
    cron_service: CronService | None = None
    memory_store: MemoryStore | None = None
    subagent_manager: SubagentManager | None = None
    skills_manager: SkillsManager | None = None
    longtask_orchestrator: LongTaskOrchestrator | None = None
    agent_name: str = "ker"
    session_name: str = "default"
    current_channel: str = "cli"
    current_user: str = "cli-user"


def safe_path(workspace: Path, relative: str) -> Path:
    candidate = (workspace / relative).resolve()
    root = workspace.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes workspace")
    return candidate
