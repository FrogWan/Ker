from __future__ import annotations

import asyncio
import json
from typing import Any

from ker.tools.tool_base import ToolContext


def long_task(
    ctx: ToolContext,
    action: str,
    description: str = "",
    task_id: str = "",
    subtasks: list[dict[str, Any]] | None = None,
    max_workers: int = 3,
    task_prompt: str = "",
    worker_agent: str = "claude",
) -> str:
    if ctx.longtask_orchestrator is None:
        return "Error: LongTask orchestrator not configured"

    orchestrator = ctx.longtask_orchestrator
    task_board = orchestrator.task_board

    if action == "plan":
        return _plan(ctx, description)

    elif action == "start":
        return _start(ctx, description, subtasks, max_workers, task_prompt, worker_agent)

    elif action == "status":
        return _status(ctx, task_id)

    elif action == "cancel":
        return _cancel(ctx, task_id)

    elif action == "result":
        return _result(ctx, task_id)

    return f"Error: Unknown action '{action}'. Use: plan, start, status, cancel, result"


def _plan(ctx: ToolContext, description: str) -> str:
    if not description:
        return "Error: description is required for plan action"
    return (
        "To proceed, propose a subtask decomposition and call long_task with action='start'.\n\n"
        "Example subtasks format:\n"
        + json.dumps([
            {"subject": "Task 1 title", "description": "Detailed instructions...", "blocked_by": []},
            {"subject": "Task 2 title", "description": "Detailed instructions...", "blocked_by": ["sub_001"]},
        ], indent=2)
        + "\n\nInclude a task_prompt with shared context all workers should know."
    )


def _start(
    ctx: ToolContext,
    description: str,
    subtasks: list[dict[str, Any]] | None,
    max_workers: int,
    task_prompt: str,
    worker_agent: str,
) -> str:
    if not subtasks:
        return "Error: subtasks array is required for start action"
    if not description:
        return "Error: description is required for start action"

    orchestrator = ctx.longtask_orchestrator
    task_board = orchestrator.task_board

    # Validate blocked_by references
    sub_ids = [f"sub_{i+1:03d}" for i in range(len(subtasks))]
    for i, st in enumerate(subtasks):
        for dep in st.get("blocked_by", []):
            if dep not in sub_ids:
                return f"Error: subtask {i+1} references unknown blocker '{dep}'. Valid IDs: {sub_ids}"

    # Check for circular dependencies
    cycle = _detect_cycle(subtasks, sub_ids)
    if cycle:
        return f"Error: Circular dependency detected: {' -> '.join(cycle)}"

    # Create task
    title = description[:60]
    task = task_board.create_task(
        title=title,
        description=description,
        max_workers=max_workers,
        worker_agent=worker_agent,
    )

    # Add subtasks
    for st_data in subtasks:
        task_board.add_subtask(
            task_id=task.id,
            subject=st_data["subject"],
            description=st_data.get("description", ""),
            blocked_by=st_data.get("blocked_by", []),
        )

    # Write shared task prompt
    if task_prompt:
        task_board.write_task_prompt(task.id, task_prompt)

    # Start orchestrator (async)
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(orchestrator.start_task(task.id), loop)

    return (
        f"LongTask '{task.title}' created (id: {task.id}) with {len(subtasks)} subtasks.\n"
        f"Worker agent: {worker_agent}, max workers: {max_workers}\n"
        f"Orchestrator started. Use long_task(action='status', task_id='{task.id}') to check progress."
    )


def _status(ctx: ToolContext, task_id: str) -> str:
    orchestrator = ctx.longtask_orchestrator
    task_board = orchestrator.task_board

    if not task_id:
        # List all tasks
        tasks = task_board.list_tasks()
        if not tasks:
            return "No long tasks found."
        lines = ["Long Tasks:"]
        for t in tasks:
            done = sum(1 for s in t.subtasks if s.status == "done")
            total = len(t.subtasks)
            active = "active" if orchestrator.is_task_active(t.id) else "idle"
            bar = _progress_bar(done, total)
            lines.append(f"  {t.id}  {t.status:<10} {bar} {done}/{total}  [{active}]  {t.title}")
        return "\n".join(lines)

    # Detailed status
    loop = asyncio.get_event_loop()
    future = asyncio.run_coroutine_threadsafe(orchestrator.get_status(task_id), loop)
    status = future.result(timeout=5)

    if "error" in status:
        return status["error"]

    done = sum(1 for st in status["subtasks"] if st["status"] == "done")
    total = len(status["subtasks"])
    bar = _progress_bar(done, total)

    lines = [
        f"Task: {status['title']} ({status['id']})",
        f"Status: {status['status']}  Supervisor: {status.get('supervisor', 'n/a')}",
        f"Progress: {bar} {done}/{total}  Active workers: {status['active_workers']}/{status['max_workers']}",
        f"Agent: {status['worker_agent']}",
    ]
    if status.get("last_milestone"):
        lines.append(f"Last milestone: {status['last_milestone']}")
    lines.append("")
    lines.append("Subtasks:")
    for st in status["subtasks"]:
        blocked = f" blocked_by={st['blocked_by']}" if st["blocked_by"] else ""
        owner = f" [{st['owner']}]" if st["owner"] else ""
        lines.append(f"  {st['id']}  {st['status']:<8}{owner}{blocked}  {st['subject']}")

    return "\n".join(lines)


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return "[" + "." * width + "]"
    filled = round(done / total * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _cancel(ctx: ToolContext, task_id: str) -> str:
    if not task_id:
        return "Error: task_id is required for cancel action"

    orchestrator = ctx.longtask_orchestrator
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(orchestrator.cancel_task(task_id), loop)
    return f"Task {task_id} cancellation initiated."


def _result(ctx: ToolContext, task_id: str) -> str:
    if not task_id:
        return "Error: task_id is required for result action"

    orchestrator = ctx.longtask_orchestrator
    task_board = orchestrator.task_board

    task = task_board.get_task(task_id)
    if task is None:
        return f"Error: Task {task_id} not found"

    if task.status != "done":
        return f"Task {task_id} is not done yet (status: {task.status})"

    synthesis_path = task_board._task_dir(task_id) / "SYNTHESIS.md"
    if synthesis_path.exists():
        return synthesis_path.read_text(encoding="utf-8")

    # Fall back to individual results
    parts = []
    for st in task.subtasks:
        parts.append(f"## {st.subject} [{st.status}]")
        if st.result:
            parts.append(st.result)
        parts.append("")
    return "\n".join(parts) if parts else "No results available."


def _detect_cycle(subtasks: list[dict], sub_ids: list[str]) -> list[str] | None:
    """Detect circular dependencies in subtask graph."""
    # Build adjacency: id -> blocked_by
    graph: dict[str, list[str]] = {}
    for i, st in enumerate(subtasks):
        graph[sub_ids[i]] = st.get("blocked_by", [])

    visited: set[str] = set()
    in_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visited.add(node)
        in_stack.add(node)
        path.append(node)
        for dep in graph.get(node, []):
            if dep in in_stack:
                cycle_start = path.index(dep)
                return path[cycle_start:] + [dep]
            if dep not in visited:
                result = dfs(dep)
                if result:
                    return result
        path.pop()
        in_stack.discard(node)
        return None

    for node in sub_ids:
        if node not in visited:
            result = dfs(node)
            if result:
                return result
    return None
