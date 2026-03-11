from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from ker.logger import get_logger
from ker.longtask.task_board import LongTask, SubTask, TaskBoard
from ker.longtask.worker import Worker, WorkerConfig, WorkerManager

log = get_logger("longtask.orchestrator")

POLL_INTERVAL = 5  # seconds — how often the monitor checks task.json
NOTIFICATION_COOLDOWN = 30  # seconds — min interval between milestone notifications
MAX_SUPERVISOR_RESPAWNS = 3  # how many times to re-spawn a crashed supervisor


class LongTaskOrchestrator:
    def __init__(
        self,
        task_board: TaskBoard,
        worker_manager: WorkerManager,
        outbound_queue: asyncio.Queue | None = None,
        ker_root: Path | None = None,
    ) -> None:
        self.task_board = task_board
        self.worker_manager = worker_manager
        self.outbound_queue = outbound_queue
        self.ker_root = ker_root or task_board.ker_root
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._last_notification_at: dict[str, float] = {}  # task_id → timestamp
        self._supervisor_spawns: dict[str, int] = {}  # task_id → spawn count

    async def start_task(self, task_id: str) -> None:
        """Launch supervisor + monitor loop as background asyncio.Task."""
        task = self.task_board.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        self.task_board.update_task_status(task_id, "running")
        self._supervisor_spawns[task_id] = 0
        self._active_tasks[task_id] = asyncio.create_task(self._monitor_loop(task_id))
        log.info("Started orchestration for task %s", task_id)

    async def _monitor_loop(self, task_id: str) -> None:
        """Thin monitor loop — no LLM calls. Spawns supervisor, polls task.json."""
        notified_terminal = False  # track whether we already sent a terminal notification
        try:
            # 1. Spawn the supervisor
            await self._spawn_supervisor(task_id)

            # 2. Poll until task reaches terminal state
            while True:
                task = self.task_board.get_task(task_id)
                if task is None or task.status in ("done", "failed", "cancelled"):
                    break

                # Check supervisor process
                supervisor = self.worker_manager.get_supervisor(task_id)
                supervisor_alive = (
                    supervisor is not None
                    and supervisor.process is not None
                    and supervisor.process.returncode is None
                )

                # Detect milestones from task.json and send notifications
                await self._check_milestones(task)

                # If supervisor exited but task is not terminal, try re-spawn
                if not supervisor_alive and task.status == "running":
                    has_remaining = any(
                        st.status in ("pending", "claimed", "running")
                        for st in task.subtasks
                    )
                    if has_remaining:
                        spawns = self._supervisor_spawns.get(task_id, 0)
                        if spawns < MAX_SUPERVISOR_RESPAWNS:
                            log.warning(
                                "Supervisor exited for task %s with work remaining, re-spawning (%d/%d)",
                                task_id, spawns + 1, MAX_SUPERVISOR_RESPAWNS,
                            )
                            await self._notify(
                                f"Supervisor restarted for task '{task.title}' ({task_id}), "
                                f"continuing... (attempt {spawns + 1}/{MAX_SUPERVISOR_RESPAWNS})"
                            )
                            await self._spawn_supervisor(task_id)
                        else:
                            log.error(
                                "Supervisor exhausted re-spawn attempts for task %s",
                                task_id,
                            )
                            self.task_board.update_task_status(task_id, "failed")
                            await self._notify(
                                f"LongTask '{task.title}' ({task_id}) failed — "
                                f"supervisor could not complete after {MAX_SUPERVISOR_RESPAWNS} attempts."
                            )
                            notified_terminal = True
                            break
                    else:
                        # All subtasks terminal but task status not updated by supervisor
                        all_done = all(
                            st.status == "done" for st in task.subtasks
                        )
                        if all_done and task.subtasks:
                            await self._finish_task(task)
                        else:
                            self.task_board.update_task_status(task_id, "failed")
                            await self._notify(
                                f"LongTask '{task.title}' ({task_id}) failed — "
                                f"some subtasks could not be completed."
                            )
                        notified_terminal = True
                        break

                await asyncio.sleep(POLL_INTERVAL)

            # Final notification for terminal states set by the supervisor
            # (skip if the monitor fallback already sent a terminal notification)
            if not notified_terminal:
                task = self.task_board.get_task(task_id)
                if task and task.status == "done":
                    await self._post_task_cleanup(task_id)
                    synthesis = self._read_synthesis(task_id)
                    await self._notify(
                        f"LongTask '{task.title}' ({task_id}) completed!\n\n{synthesis}"
                    )
                elif task and task.status == "failed":
                    await self._post_task_cleanup(task_id)
                    reason = task.last_milestone or "unknown reason"
                    await self._notify(
                        f"LongTask '{task.title}' ({task_id}) failed: {reason}"
                    )

        except asyncio.CancelledError:
            log.info("Monitor loop cancelled for task %s", task_id)
        except Exception as exc:
            log.error("Monitor loop error for task %s: %s", task_id, exc)
            self.task_board.update_task_status(task_id, "failed")
        finally:
            self._active_tasks.pop(task_id, None)
            self._supervisor_spawns.pop(task_id, None)
            self._last_notification_at.pop(task_id, None)

    # ── Supervisor management ─────────────────────────────────────

    async def _spawn_supervisor(self, task_id: str) -> None:
        """Build supervisor prompt and spawn the external process."""
        prompt = self._build_supervisor_prompt(task_id)

        task = self.task_board.get_task(task_id)
        config = WorkerConfig(agent=task.worker_agent if task else "claude")

        # Kill existing supervisor if any
        existing = self.worker_manager.get_supervisor(task_id)
        if existing and existing.process and existing.process.returncode is None:
            await self.worker_manager.kill_worker(existing)

        # Remove old supervisor from worker list so get_supervisor returns the new one
        workers = self.worker_manager._workers.get(task_id, [])
        self.worker_manager._workers[task_id] = [
            w for w in workers if w.name != "supervisor"
        ]

        await self.worker_manager.spawn_supervisor(task_id, prompt, config)
        self._supervisor_spawns[task_id] = self._supervisor_spawns.get(task_id, 0) + 1
        log.info("Spawned supervisor for task %s (spawn #%d)", task_id, self._supervisor_spawns[task_id])

    def _build_supervisor_prompt(self, task_id: str) -> str:
        """Build the supervisor prompt from the SUPERVISOR.md template + current task state."""
        task = self.task_board.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        template = self._load_supervisor_template()
        task_prompt = self.task_board.read_task_prompt(task_id)
        task_dir = self.task_board._task_dir(task_id)

        # Build subtask list with status info
        subtask_lines = []
        for st in task.subtasks:
            line = f"- {st.id} [{st.status}] {st.subject} (attempts: {st.attempts})"
            if st.blocked_by:
                line += f" blocked_by: {st.blocked_by}"
            if st.status == "done" and st.result:
                line += f"\n  Result: {st.result[:1000]}"
            elif st.status == "failed" and st.result:
                line += f"\n  Error: {st.result[:1000]}"
            subtask_lines.append(line)

        prompt = template.format(
            task_description=f"{task.title}\n\n{task.description}",
            subtask_list="\n".join(subtask_lines) or "(no subtasks)",
            task_prompt=task_prompt or "(no shared context)",
            task_json_path=str(task_dir / "task.json"),
            task_dir=str(task_dir),
            workspace=str(self.worker_manager.workspace),
            max_workers=str(task.max_workers),
        )

        return prompt

    def _load_supervisor_template(self) -> str:
        """Load the SUPERVISOR.md template."""
        # Check built-in templates first
        builtin = Path(__file__).resolve().parents[1] / "memory" / "templates" / "SUPERVISOR.md"
        if builtin.exists():
            return builtin.read_text(encoding="utf-8")

        # Fallback to ker_root templates
        custom = self.ker_root / "templates" / "SUPERVISOR.md"
        if custom.exists():
            return custom.read_text(encoding="utf-8")

        raise FileNotFoundError("SUPERVISOR.md template not found")

    # ── Milestone detection ───────────────────────────────────────

    async def _check_milestones(self, task: LongTask) -> None:
        """Detect milestone changes in task.json and send rate-limited notifications."""
        if not task.last_milestone:
            return

        last_notified = self._last_notification_at.get(task.id, 0.0)
        now = time.time()

        # Rate-limit: at most one notification per NOTIFICATION_COOLDOWN seconds
        if now - last_notified < NOTIFICATION_COOLDOWN:
            return

        # Check if this is a new milestone we haven't notified about
        if task.last_milestone_at > last_notified:
            done = sum(1 for st in task.subtasks if st.status == "done")
            total = len(task.subtasks)
            await self._notify(
                f"Progress on '{task.title}' ({task.id}): "
                f"{done}/{total} subtasks completed. {task.last_milestone}"
            )
            self._last_notification_at[task.id] = now

    # ── Completion ────────────────────────────────────────────────

    async def _finish_task(self, task: LongTask) -> None:
        """Merge branches and write synthesis (fallback if supervisor didn't do it)."""
        await self._merge_results(task.id)

        # Write a simple synthesis from subtask results
        parts = [f"# LongTask Results: {task.title}\n"]
        for st in task.subtasks:
            status_icon = "done" if st.status == "done" else "FAILED"
            parts.append(f"## [{status_icon}] {st.subject}")
            if st.result:
                parts.append(st.result[:2000])
            parts.append("")
        summary = "\n".join(parts)

        self.task_board.update_task_status(task.id, "done")

        synthesis_path = self.task_board._task_dir(task.id) / "SYNTHESIS.md"
        synthesis_path.write_text(summary, encoding="utf-8")

        # Clean up all worktrees and branches now that we're done
        await self._post_task_cleanup(task.id)

        await self._notify(
            f"LongTask '{task.title}' ({task.id}) completed!\n\n{summary}"
        )
        log.info("Task %s completed (monitor fallback)", task.id)

    async def cancel_task(self, task_id: str) -> None:
        """Kill supervisor and all workers, clean up worktrees, cancel loop, mark cancelled."""
        # Kill supervisor (tree-kill takes out its worker children too)
        supervisor = self.worker_manager.get_supervisor(task_id)
        if supervisor:
            await self.worker_manager.kill_worker(supervisor)

        # Kill any tracked workers (normally none in supervisor architecture,
        # but kept for safety / fallback)
        for worker in self.worker_manager.get_active_workers(task_id):
            await self.worker_manager.kill_worker(worker)

        # Clean up ALL worktrees and branches for this task — catches resources
        # created by the supervisor that we don't track in WorkerManager
        await self.worker_manager.cleanup_task_worktrees(task_id)

        loop_task = self._active_tasks.get(task_id)
        if loop_task and not loop_task.done():
            loop_task.cancel()

        self.task_board.cancel_task(task_id)
        self._active_tasks.pop(task_id, None)
        log.info("Task %s cancelled", task_id)

    async def get_status(self, task_id: str) -> dict:
        task = self.task_board.get_task(task_id)
        if task is None:
            return {"error": f"Task {task_id} not found"}

        supervisor = self.worker_manager.get_supervisor(task_id)
        supervisor_state = "not started"
        if supervisor:
            if supervisor.process and supervisor.process.returncode is None:
                supervisor_state = "running"
            else:
                exit_code = supervisor.process.returncode if supervisor.process else -1
                supervisor_state = f"exited (code={exit_code})"

        active_workers = self.worker_manager.get_active_workers(task_id)
        subtask_summary = []
        for st in task.subtasks:
            subtask_summary.append({
                "id": st.id,
                "subject": st.subject,
                "status": st.status,
                "owner": st.owner,
                "attempts": st.attempts,
                "blocked_by": st.blocked_by,
            })

        return {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "worker_agent": task.worker_agent,
            "max_workers": task.max_workers,
            "active_workers": len(active_workers),
            "supervisor": supervisor_state,
            "last_milestone": task.last_milestone,
            "subtasks": subtask_summary,
            "is_running": task_id in self._active_tasks,
        }

    async def _merge_results(self, task_id: str) -> None:
        """Merge worker results back into the current branch.

        Uses manifest-aware merging when manifests are available:
        - Reads {subtask_id}.manifest.json to know which files the worker
          intentionally changed.
        - Only checks out those files from the branch (selective merge).
        - Falls back to full git merge if no manifest exists.

        This prevents build artifacts, node_modules, .claude/ folders,
        and other temp files from leaking into the main branch.
        """
        task = self.task_board.get_task(task_id)
        branches = await self.worker_manager.list_task_branches(task_id)

        for branch in branches:
            # Extract subtask_id from branch name: longtask/{task_id}/{subtask_id}
            parts = branch.split("/")
            subtask_id = parts[-1] if len(parts) >= 3 else ""

            # Check if this subtask is done (only merge successful work)
            if task:
                subtask = next((s for s in task.subtasks if s.id == subtask_id), None)
                if subtask and subtask.status != "done":
                    log.info("Skipping merge for non-done subtask branch %s", branch)
                    continue

            try:
                manifest_files = self.worker_manager.get_manifest_files(task_id, subtask_id)

                if manifest_files:
                    # Manifest-aware merge: only checkout declared files
                    branch_files = await self.worker_manager.get_branch_changed_files(branch)
                    wanted = [f for f in branch_files if f in manifest_files]
                    unwanted = [f for f in branch_files if f not in manifest_files]

                    if unwanted:
                        log.info(
                            "Manifest filter: keeping %d files, skipping %d unwanted from %s",
                            len(wanted), len(unwanted), branch,
                        )

                    if wanted:
                        ok = await self.worker_manager.checkout_files_from_branch(branch, wanted)
                        if ok:
                            # Stage and commit the selectively checked-out files
                            await self._commit_selective_merge(task_id, subtask_id, wanted)
                            log.info("Selective merge from %s: %d files", branch, len(wanted))
                        else:
                            log.warning("Selective checkout failed for %s, falling back to merge", branch)
                            await self._full_merge_branch(branch)
                    else:
                        log.info("No wanted files to merge from %s", branch)
                else:
                    # No manifest — fall back to full merge
                    log.info("No manifest for %s, using full merge", branch)
                    await self._full_merge_branch(branch)

                # Remove branch after merge
                await self.worker_manager.remove_branch(branch)

            except Exception as exc:
                log.error("Merge failed for %s: %s", branch, exc)

    async def _full_merge_branch(self, branch: str) -> None:
        """Standard git merge of a branch."""
        proc = await asyncio.create_subprocess_exec(
            "git", "merge", branch,
            "--no-edit", "-m", f"Merge longtask branch {branch}",
            cwd=str(self.worker_manager.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning("Merge conflict for branch %s: %s", branch, stderr.decode()[:200])
        else:
            log.info("Full merge of branch %s", branch)

    async def _commit_selective_merge(
        self, task_id: str, subtask_id: str, files: list[str],
    ) -> None:
        """Stage and commit selectively checked-out files."""
        workspace = str(self.worker_manager.workspace)
        # git add the specific files
        proc = await asyncio.create_subprocess_exec(
            "git", "add", "--", *files,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # Commit
        msg = f"Merge longtask {task_id}/{subtask_id} (manifest-filtered)"
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", msg, "--allow-empty",
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    # ── Post-task cleanup ─────────────────────────────────────────

    async def _post_task_cleanup(self, task_id: str) -> None:
        """Clean up all resources after a task completes or fails.

        Removes worktrees, branches, and supervisor process remnants.
        """
        # 1. Remove all worktrees for this task
        await self.worker_manager.cleanup_task_worktrees(task_id)

        # 2. Kill supervisor if still running
        supervisor = self.worker_manager.get_supervisor(task_id)
        if supervisor and supervisor.process and supervisor.process.returncode is None:
            await self.worker_manager.kill_worker(supervisor)

        log.info("Post-task cleanup done for %s", task_id)

    def _read_synthesis(self, task_id: str) -> str:
        """Read the SYNTHESIS.md file if it exists."""
        path = self.task_board._task_dir(task_id) / "SYNTHESIS.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return "(no synthesis available)"

    # ── Helpers ───────────────────────────────────────────────────

    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from text (may be in a code block or bare)."""
        code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1).strip())
            except json.JSONDecodeError:
                pass

        brace_start = text.find("{")
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start : i + 1])
                        except json.JSONDecodeError:
                            break
        return None

    async def _notify(self, text: str) -> None:
        if self.outbound_queue:
            from ker.types import OutboundMessage
            await self.outbound_queue.put(
                OutboundMessage(text=text, channel="cli", user="system")
            )

    def is_task_active(self, task_id: str) -> bool:
        return task_id in self._active_tasks
