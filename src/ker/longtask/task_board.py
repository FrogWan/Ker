from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SubTask:
    id: str
    subject: str
    description: str
    status: str = "pending"  # pending | claimed | running | done | failed
    owner: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    result: str = ""
    worktree_branch: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempts: int = 0


@dataclass
class LongTask:
    id: str
    title: str
    description: str
    status: str = "planning"  # planning | running | done | failed | cancelled
    subtasks: list[SubTask] = field(default_factory=list)
    worker_agent: str = "claude"
    max_workers: int = 3
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_milestone: str = ""
    last_milestone_at: float = 0.0


class TaskBoard:
    def __init__(self, ker_root: Path, workspace: Path) -> None:
        self.ker_root = ker_root
        self.workspace = workspace
        self._base = ker_root / "longtasks"
        self._base.mkdir(parents=True, exist_ok=True)

    # ── Task CRUD ────────────────────────────────────────────────

    def create_task(
        self,
        title: str,
        description: str,
        max_workers: int = 3,
        worker_agent: str = "claude",
    ) -> LongTask:
        task_id = uuid.uuid4().hex[:8]
        task = LongTask(
            id=task_id,
            title=title,
            description=description,
            max_workers=max_workers,
            worker_agent=worker_agent,
        )
        self._task_dir(task_id).mkdir(parents=True, exist_ok=True)
        self._save(task)
        return task

    def get_task(self, task_id: str) -> LongTask | None:
        try:
            return self._load(task_id)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def list_tasks(self) -> list[LongTask]:
        tasks: list[LongTask] = []
        if not self._base.exists():
            return tasks
        for d in sorted(self._base.iterdir()):
            if d.is_dir() and (d / "task.json").exists():
                try:
                    tasks.append(self._load(d.name))
                except Exception:
                    continue
        return tasks

    def update_task_status(self, task_id: str, status: str) -> None:
        task = self._load(task_id)
        task.status = status
        task.updated_at = time.time()
        self._save(task)

    def cancel_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        task.status = "cancelled"
        task.updated_at = time.time()
        for st in task.subtasks:
            if st.status in ("pending", "claimed", "running"):
                st.status = "failed"
                st.result = "Task cancelled"
                st.updated_at = time.time()
        self._save(task)
        return True

    # ── Subtask management ───────────────────────────────────────

    def add_subtask(
        self,
        task_id: str,
        subject: str,
        description: str,
        blocked_by: list[str] | None = None,
    ) -> SubTask:
        task = self._load(task_id)
        idx = len(task.subtasks) + 1
        sub = SubTask(
            id=f"sub_{idx:03d}",
            subject=subject,
            description=description,
            blocked_by=blocked_by or [],
        )
        task.subtasks.append(sub)
        task.updated_at = time.time()
        self._save(task)
        return sub

    def claim_subtask(self, task_id: str, subtask_id: str, owner: str) -> bool:
        task = self._load(task_id)
        for st in task.subtasks:
            if st.id == subtask_id:
                if st.status != "pending":
                    return False
                st.status = "claimed"
                st.owner = owner
                st.updated_at = time.time()
                task.updated_at = time.time()
                self._save(task)
                return True
        return False

    def complete_subtask(self, task_id: str, subtask_id: str, result: str) -> None:
        task = self._load(task_id)
        for st in task.subtasks:
            if st.id == subtask_id:
                st.status = "done"
                st.result = result
                st.updated_at = time.time()
                break
        task.updated_at = time.time()
        self._save(task)

        # Persist result file
        result_path = self._task_dir(task_id) / f"{subtask_id}.md"
        result_path.write_text(result, encoding="utf-8")

    def fail_subtask(self, task_id: str, subtask_id: str, error: str) -> None:
        task = self._load(task_id)
        for st in task.subtasks:
            if st.id == subtask_id:
                st.status = "failed"
                st.result = error
                st.attempts += 1
                st.updated_at = time.time()
                break
        task.updated_at = time.time()
        self._save(task)

    def reset_subtask_for_retry(self, task_id: str, subtask_id: str) -> bool:
        """Reset a failed subtask to pending for retry. Returns False if max attempts reached."""
        task = self._load(task_id)
        for st in task.subtasks:
            if st.id == subtask_id:
                if st.attempts >= 3:
                    return False
                st.status = "pending"
                st.owner = None
                st.worktree_branch = ""
                st.updated_at = time.time()
                break
        task.updated_at = time.time()
        self._save(task)
        return True

    def update_subtask_description(self, task_id: str, subtask_id: str, description: str) -> bool:
        """Update the description of a subtask (used by LLM supervisor to refine after failure)."""
        task = self._load(task_id)
        for st in task.subtasks:
            if st.id == subtask_id:
                st.description = description
                st.updated_at = time.time()
                task.updated_at = time.time()
                self._save(task)
                return True
        return False

    def get_claimable(self, task_id: str) -> list[SubTask]:
        """Return subtasks that are pending and have all blockers done."""
        task = self._load(task_id)
        done_ids = {st.id for st in task.subtasks if st.status == "done"}
        claimable: list[SubTask] = []
        for st in task.subtasks:
            if st.status != "pending":
                continue
            if all(bid in done_ids for bid in st.blocked_by):
                claimable.append(st)
        return claimable

    # ── Inbox ────────────────────────────────────────────────────

    def send_message(self, task_id: str, to: str, content: str) -> None:
        inbox_path = self._task_dir(task_id) / f"inbox_{to}.jsonl"
        entry = {"ts": time.time(), "to": to, "content": content}
        with open(inbox_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_inbox(self, task_id: str, name: str) -> list[dict]:
        inbox_path = self._task_dir(task_id) / f"inbox_{name}.jsonl"
        if not inbox_path.exists():
            return []
        messages: list[dict] = []
        for line in inbox_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        # Clear inbox after reading
        inbox_path.write_text("", encoding="utf-8")
        return messages

    # ── Task prompt ──────────────────────────────────────────────

    def write_task_prompt(self, task_id: str, content: str) -> None:
        path = self._task_dir(task_id) / "TASK_PROMPT.md"
        path.write_text(content, encoding="utf-8")

    def read_task_prompt(self, task_id: str) -> str:
        path = self._task_dir(task_id) / "TASK_PROMPT.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    # ── File I/O ─────────────────────────────────────────────────

    def _task_dir(self, task_id: str) -> Path:
        return self._base / task_id

    def _save(self, task: LongTask) -> None:
        path = self._task_dir(task.id) / "task.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(task)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self, task_id: str) -> LongTask:
        path = self._task_dir(task_id) / "task.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        subtasks = [SubTask(**s) for s in data.pop("subtasks", [])]
        return LongTask(**data, subtasks=subtasks)
