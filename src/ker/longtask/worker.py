from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from ker.logger import get_logger
from ker.longtask.task_board import SubTask, TaskBoard

log = get_logger("longtask.worker")


@dataclass
class WorkerConfig:
    agent: str = "claude"
    model: str | None = None
    dangerous_mode: bool = True


@dataclass
class Worker:
    name: str
    process: asyncio.subprocess.Process | None = None
    subtask_id: str = ""
    task_id: str = ""
    status: str = "spawning"  # spawning | working | done | failed
    worktree_path: Path | None = None
    branch: str = ""
    started_at: float = field(default_factory=time.time)
    pid: int | None = None
    command: list[str] = field(default_factory=list)
    _log_file: IO | None = field(default=None, repr=False)
    _stderr_file: IO | None = field(default=None, repr=False)


class WorkerManager:
    def __init__(self, workspace: Path, ker_root: Path, task_board: TaskBoard) -> None:
        self.workspace = workspace
        self.ker_root = ker_root
        self.task_board = task_board
        self._workers: dict[str, list[Worker]] = {}  # task_id → workers

    # ── Worktree management ──────────────────────────────────────

    async def create_worktree(self, task_id: str, subtask_id: str) -> tuple[Path, str]:
        branch = f"longtask/{task_id}/{subtask_id}"
        worktree_path = self.workspace.parent / f"{self.workspace.name}-{task_id}-{subtask_id}"

        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", str(worktree_path), "-b", branch,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {stderr.decode()}")

        log.info("Created worktree %s on branch %s", worktree_path, branch)
        return worktree_path, branch

    async def remove_worktree(self, path: Path) -> None:
        if not path.exists():
            return
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "remove", str(path), "--force",
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        log.info("Removed worktree %s", path)

    async def remove_branch(self, branch: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "-D", branch,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    # ── Supervisor lifecycle ────────────────────────────────────

    async def spawn_supervisor(
        self,
        task_id: str,
        prompt: str,
        config: WorkerConfig | None = None,
    ) -> Worker:
        """Spawn an external supervisor process in the main workspace (not a worktree)."""
        config = config or WorkerConfig()

        if config.agent == "codex":
            cmd = ["codex", "exec", "--full-auto", prompt]
        else:
            cmd = ["claude", "--print", "-p", prompt]
            if config.dangerous_mode:
                cmd.insert(1, "--dangerously-skip-permissions")
            if config.model:
                cmd.extend(["--model", config.model])

        task_dir = self.ker_root / "longtasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        log_path = task_dir / "supervisor.log"
        stderr_path = task_dir / "supervisor.stderr.log"
        log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
        stderr_file = open(stderr_path, "w", encoding="utf-8")  # noqa: SIM115

        self._log_worker_event(task_id, "supervisor", "spawn", {
            "command": cmd,
            "cwd": str(self.workspace),
        })

        import sys
        # start_new_session on Unix so we can kill the entire process group
        # (supervisor + any workers it spawns) on cancellation
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.workspace),
            stdout=log_file,
            stderr=stderr_file,
            start_new_session=(sys.platform != "win32"),
        )

        self._log_worker_event(task_id, "supervisor", "started", {
            "pid": proc.pid,
        })

        worker = Worker(
            name="supervisor",
            process=proc,
            subtask_id="",
            task_id=task_id,
            status="working",
            worktree_path=None,
            branch="",
            pid=proc.pid,
            command=cmd,
            _log_file=log_file,
            _stderr_file=stderr_file,
        )

        if task_id not in self._workers:
            self._workers[task_id] = []
        self._workers[task_id].append(worker)

        log.info("Spawned supervisor (pid=%s) for task %s", proc.pid, task_id)
        return worker

    def get_supervisor(self, task_id: str) -> Worker | None:
        """Return the supervisor worker for a task, if any."""
        for w in self._workers.get(task_id, []):
            if w.name == "supervisor":
                return w
        return None

    # ── Worker lifecycle ─────────────────────────────────────────

    async def spawn_worker(
        self,
        task_id: str,
        worker_name: str,
        subtask: SubTask,
        task_prompt: str,
        config: WorkerConfig,
    ) -> Worker:
        # 1. Create git worktree
        worktree_path, branch = await self.create_worktree(task_id, subtask.id)

        # 2. Build worker prompt
        task_dir = self.ker_root / "longtasks" / task_id
        prompt = (
            f"You are {worker_name}, a focused coding agent.\n\n"
            f"## Shared Context\n{task_prompt}\n\n"
            f"## Your Task: {subtask.subject}\n{subtask.description}\n\n"
            f"## Instructions\n"
            f"- Complete the task in this worktree. All file changes stay on branch '{branch}'.\n"
            f"- When done, write a summary to: {task_dir / (subtask.id + '.md')}\n"
            f"- Commit your changes with a descriptive message.\n"
            f"- If blocked, write to: {task_dir / 'inbox_lead.jsonl'}\n"
        )

        # 3. Build command based on agent type
        if config.agent == "codex":
            cmd = [
                "codex", "exec",
                "--full-auto",
                prompt,
            ]
        else:
            cmd = [
                "claude", "--print",
                "-p", prompt,
            ]
            if config.dangerous_mode:
                cmd.insert(1, "--dangerously-skip-permissions")
            if config.model:
                cmd.extend(["--model", config.model])

        # 4. Launch subprocess in worktree directory
        log_path = task_dir / f"{worker_name}.log"
        stderr_path = task_dir / f"{worker_name}.stderr.log"
        log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
        stderr_file = open(stderr_path, "w", encoding="utf-8")  # noqa: SIM115

        # Log the command being executed for debugging
        self._log_worker_event(task_id, worker_name, "spawn", {
            "command": cmd,
            "cwd": str(worktree_path),
            "subtask_id": subtask.id,
            "pid": None,  # filled after spawn
        })

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(worktree_path),
            stdout=log_file,
            stderr=stderr_file,
        )

        # Update the log with PID
        self._log_worker_event(task_id, worker_name, "started", {
            "pid": proc.pid,
            "command_summary": " ".join(cmd[:5]) + ("..." if len(cmd) > 5 else ""),
        })

        worker = Worker(
            name=worker_name,
            process=proc,
            subtask_id=subtask.id,
            task_id=task_id,
            status="working",
            worktree_path=worktree_path,
            branch=branch,
            pid=proc.pid,
            command=cmd,
            _log_file=log_file,
            _stderr_file=stderr_file,
        )

        if task_id not in self._workers:
            self._workers[task_id] = []
        self._workers[task_id].append(worker)

        log.info("Spawned %s (pid=%s) for %s/%s", worker_name, proc.pid, task_id, subtask.id)
        return worker

    async def check_worker(self, worker: Worker) -> str:
        if worker.process is None:
            return "failed"
        if worker.process.returncode is not None:
            if worker.process.returncode == 0:
                worker.status = "done"
                self._log_worker_event(worker.task_id, worker.name, "done", {
                    "subtask_id": worker.subtask_id,
                    "duration_s": round(time.time() - worker.started_at, 1),
                    "exit_code": 0,
                })
            else:
                worker.status = "failed"
                stderr = self.read_stderr(worker)
                self._log_worker_event(worker.task_id, worker.name, "failed", {
                    "subtask_id": worker.subtask_id,
                    "exit_code": worker.process.returncode,
                    "duration_s": round(time.time() - worker.started_at, 1),
                    "stderr": stderr[:2000],
                    "command": worker.command,
                })
            self._close_log(worker)
            return worker.status
        return "working"

    async def kill_worker(self, worker: Worker) -> None:
        if worker.process and worker.process.returncode is None:
            try:
                self._kill_process_tree(worker.process.pid)
                await asyncio.wait_for(worker.process.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    worker.process.kill()
                except ProcessLookupError:
                    pass
        worker.status = "failed"
        self._close_log(worker)

    @staticmethod
    def _kill_process_tree(pid: int) -> None:
        """Kill a process and all its descendants."""
        import os
        import signal
        import sys

        if sys.platform == "win32":
            # On Windows, taskkill /T kills the entire process tree
            os.system(f"taskkill /F /T /PID {pid} >nul 2>&1")  # noqa: S605
        else:
            # On Unix, kill the entire process group
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

    def collect_result(self, worker: Worker) -> str | None:
        result_path = (
            self.ker_root / "longtasks" / worker.task_id / f"{worker.subtask_id}.md"
        )
        if result_path.exists():
            return result_path.read_text(encoding="utf-8")
        return None

    # ── Manifest support ─────────────────────────────────────────

    def read_manifest(self, task_id: str, subtask_id: str) -> dict | None:
        """Read a worker's manifest file listing files it intentionally changed.

        Expected format:
        {
            "files_modified": ["src/foo.py"],
            "files_created": ["src/new.py"],
            "files_deleted": ["src/old.py"]
        }
        """
        manifest_path = (
            self.ker_root / "longtasks" / task_id / f"{subtask_id}.manifest.json"
        )
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def get_manifest_files(self, task_id: str, subtask_id: str) -> set[str]:
        """Return the set of files a worker declared in its manifest."""
        manifest = self.read_manifest(task_id, subtask_id)
        if manifest is None:
            return set()
        files: set[str] = set()
        for key in ("files_modified", "files_created"):
            files.update(manifest.get(key, []))
        return files

    async def get_branch_changed_files(self, branch: str) -> list[str]:
        """Return files changed on a branch relative to HEAD."""
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", f"HEAD...{branch}",
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        return [f for f in stdout.decode().splitlines() if f.strip()]

    async def checkout_files_from_branch(
        self, branch: str, files: list[str]
    ) -> bool:
        """Checkout specific files from a branch into the working tree.

        Returns True if successful.
        """
        if not files:
            return True
        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", branch, "--", *files,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("checkout_files_from_branch failed: %s", stderr.decode()[:200])
            return False
        return True

    def read_stderr(self, worker: Worker) -> str:
        """Read full stderr from the worker's stderr log file."""
        stderr_path = (
            self.ker_root / "longtasks" / worker.task_id / f"{worker.name}.stderr.log"
        )
        if stderr_path.exists():
            try:
                return stderr_path.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    def read_stdout(self, worker: Worker) -> str:
        """Read stdout from the worker's log file (last 3000 chars)."""
        log_path = (
            self.ker_root / "longtasks" / worker.task_id / f"{worker.name}.log"
        )
        if log_path.exists():
            try:
                text = log_path.read_text(encoding="utf-8")
                return text[-3000:] if len(text) > 3000 else text
            except OSError:
                return ""
        return ""

    def get_active_workers(self, task_id: str) -> list[Worker]:
        return [w for w in self._workers.get(task_id, []) if w.status == "working"]

    def get_all_workers(self, task_id: str) -> list[Worker]:
        return list(self._workers.get(task_id, []))

    async def cleanup_task_worktrees(self, task_id: str) -> None:
        """Scan and remove all git worktrees and branches for a task.

        Used during cancellation to clean up resources created by the
        supervisor that are not tracked in WorkerManager._workers.
        """
        # List all worktrees and find ones matching this task
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "list", "--porcelain",
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return

        # Parse porcelain output: lines like "worktree /path/to/wt"
        task_suffix = f"-{task_id}-"
        for line in stdout.decode().splitlines():
            if line.startswith("worktree "):
                wt_path = Path(line[len("worktree "):].strip())
                if task_suffix in wt_path.name:
                    await self.remove_worktree(wt_path)

        # List branches matching longtask/{task_id}/* and delete them
        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "--list", f"longtask/{task_id}/*",
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            for line in stdout.decode().splitlines():
                branch = line.strip().lstrip("* ")
                if branch:
                    await self.remove_branch(branch)

    async def list_task_branches(self, task_id: str) -> list[str]:
        """Return all git branches for a task (longtask/{task_id}/*)."""
        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "--list", f"longtask/{task_id}/*",
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        branches = []
        for line in stdout.decode().splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                branches.append(branch)
        return branches

    def _close_log(self, worker: Worker) -> None:
        if worker._log_file and not worker._log_file.closed:
            worker._log_file.close()
            worker._log_file = None
        if worker._stderr_file and not worker._stderr_file.closed:
            worker._stderr_file.close()
            worker._stderr_file = None

    def _log_worker_event(self, task_id: str, worker_name: str, event: str, data: dict) -> None:
        """Append a structured event to the task's worker event log."""
        events_path = self.ker_root / "longtasks" / task_id / "events.jsonl"
        entry = {"ts": time.time(), "worker": worker_name, "event": event, **data}
        try:
            with open(events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
