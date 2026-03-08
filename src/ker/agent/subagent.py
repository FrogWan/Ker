from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ker.logger import get_logger

log = get_logger("subagent")


@dataclass
class SubagentResult:
    task_id: str
    label: str
    task: str
    status: str
    result: str
    channel: str
    user: str


class SubagentManager:
    def __init__(self, run_prompt: Callable[[str], Awaitable[str]]) -> None:
        self.run_prompt = run_prompt
        self._tasks: dict[str, asyncio.Task[SubagentResult]] = {}
        self._completed: list[SubagentResult] = []

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        channel: str = "cli",
        user: str = "cli-user",
        session_key: str = "",
    ) -> str:
        task_id = uuid.uuid4().hex[:8]
        display = label or (task[:30] + ("..." if len(task) > 30 else ""))

        async_task = asyncio.create_task(self._run_task(task_id, task, display, channel, user))
        self._tasks[task_id] = async_task
        return f"Subagent [{display}] started (id: {task_id}). I will notify when it completes."

    async def _run_task(self, task_id: str, task: str, label: str, channel: str, user: str) -> SubagentResult:
        prompt = (
            "You are a focused subagent. Complete the task and return concise actionable result. "
            "Do not mention internal implementation details.\n\nTask:\n" + task
        )
        status = "ok"
        try:
            result_text = await self.run_prompt(prompt)
        except Exception as exc:
            status = "error"
            result_text = f"Error: {exc}"
            log.error("Subagent %s failed: %s", task_id, exc)

        result = SubagentResult(
            task_id=task_id, label=label, task=task, status=status, result=result_text, channel=channel, user=user
        )
        self._completed.append(result)
        self._tasks.pop(task_id, None)
        return result

    def poll_results(self) -> list[SubagentResult]:
        out = list(self._completed)
        self._completed.clear()
        return out

    def get_running_count(self) -> int:
        return len(self._tasks)
