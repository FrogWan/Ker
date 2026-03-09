from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ker.logger import get_logger
from ker.tools.tool_base import ToolContext

log = get_logger("longtask")

LONG_TASK_DIR = "longTask"


def long_task(
    ctx: ToolContext,
    action: str,
    task_name: str | None = None,
    workspace: str | None = None,
    description: str | None = None,
    max_iterations: int = 3,
) -> str:
    if action == "start":
        return _start(ctx, task_name, workspace, description, max_iterations)
    elif action == "status":
        return _status(ctx, task_name)
    elif action == "cancel":
        return _cancel(ctx, task_name)
    elif action == "list":
        return _list(ctx)
    else:
        return f"Unknown action '{action}'. Use: start, status, cancel, list."


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _start(
    ctx: ToolContext,
    task_name: str | None,
    workspace: str | None,
    description: str | None,
    max_iterations: int,
) -> str:
    if not task_name:
        return "Error: task_name is required for start."
    if not workspace:
        return "Error: workspace is required for start."
    if not description:
        return "Error: description is required for start."

    if not shutil.which("claude"):
        return "Error: 'claude' CLI not found on PATH. Install Claude Code first."

    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        return f"Error: workspace '{workspace}' does not exist or is not a directory."

    task_dir = ctx.ker_root / LONG_TASK_DIR / task_name
    status_path = task_dir / "status.json"
    if status_path.exists():
        existing = _read_status(status_path)
        if existing and existing.get("status") in ("implementing", "reviewing", "initializing"):
            return f"Error: task '{task_name}' is already running. Use status or cancel."

    task_dir.mkdir(parents=True, exist_ok=True)

    # Write task definition
    (task_dir / "task.md").write_text(description, encoding="utf-8")

    # Init status
    now = datetime.now(timezone.utc).isoformat()
    status = {
        "task_name": task_name,
        "workspace": str(workspace_path),
        "status": "initializing",
        "iteration": 0,
        "max_iterations": max_iterations,
        "started_at": now,
        "updated_at": now,
        "cancelled": False,
        "current_agent": None,
        "pid": None,
        "history": [],
        "result": None,
        "error": None,
    }
    _write_status(status_path, status)

    # Launch daemon thread
    t = threading.Thread(
        target=_task_runner,
        args=(ctx, task_name, task_dir, workspace_path, max_iterations),
        daemon=True,
        name=f"longtask-{task_name}",
    )
    t.start()

    return (
        f"Long task '{task_name}' started.\n"
        f"Workspace: {workspace_path}\n"
        f"Max iterations: {max_iterations}\n"
        f"Use long_task(action='status', task_name='{task_name}') to check progress."
    )


def _status(ctx: ToolContext, task_name: str | None) -> str:
    if not task_name:
        return "Error: task_name is required for status."

    status_path = ctx.ker_root / LONG_TASK_DIR / task_name / "status.json"
    status = _read_status(status_path)
    if status is None:
        return f"Error: no task '{task_name}' found."

    lines = [
        f"Task: {status['task_name']}",
        f"Status: {status['status']}",
        f"Iteration: {status['iteration']}/{status['max_iterations']}",
        f"Current agent: {status.get('current_agent') or 'none'}",
        f"Started: {status['started_at']}",
        f"Updated: {status['updated_at']}",
    ]

    if status.get("result"):
        lines.append(f"Result: {status['result']}")
    if status.get("error"):
        lines.append(f"Error: {status['error']}")

    history = status.get("history", [])
    if history:
        lines.append(f"\nHistory ({len(history)} entries):")
        for entry in history[-6:]:
            agent = entry.get("agent", "?")
            iteration = entry.get("iteration", "?")
            exit_code = entry.get("exit_code")
            verdict = entry.get("verdict")
            detail = f"exit={exit_code}" if exit_code is not None else f"verdict={verdict}"
            feedback = entry.get("feedback", "")
            line = f"  iter {iteration} [{agent}] {detail}"
            if feedback:
                line += f" - {feedback[:120]}"
            lines.append(line)

    return "\n".join(lines)


def _cancel(ctx: ToolContext, task_name: str | None) -> str:
    if not task_name:
        return "Error: task_name is required for cancel."

    status_path = ctx.ker_root / LONG_TASK_DIR / task_name / "status.json"
    status = _read_status(status_path)
    if status is None:
        return f"Error: no task '{task_name}' found."

    if status["status"] in ("complete", "failed", "cancelled"):
        return f"Task '{task_name}' already {status['status']}."

    status["cancelled"] = True
    status["status"] = "cancelled"
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_status(status_path, status)

    pid = status.get("pid")
    if pid:
        _kill_process_tree(pid)

    return f"Task '{task_name}' cancelled."


def _list(ctx: ToolContext) -> str:
    base = ctx.ker_root / LONG_TASK_DIR
    if not base.exists():
        return "No long tasks found."

    rows = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        sp = d / "status.json"
        status = _read_status(sp)
        if status is None:
            continue
        name = status.get("task_name", d.name)
        st = status.get("status", "?")
        iteration = status.get("iteration", 0)
        max_iter = status.get("max_iterations", "?")
        rows.append(f"  {name:30s} {st:15s} iter {iteration}/{max_iter}")

    if not rows:
        return "No long tasks found."

    return "Long tasks:\n" + "\n".join(rows)


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------

def _task_runner(
    ctx: ToolContext,
    task_name: str,
    task_dir: Path,
    workspace_path: Path,
    max_iterations: int,
) -> None:
    status_path = task_dir / "status.json"
    task_md = (task_dir / "task.md").read_text(encoding="utf-8")
    feedback = ""

    try:
        for iteration in range(1, max_iterations + 1):
            status = _read_status(status_path)
            if status and status.get("cancelled"):
                log.info("Task %s cancelled before iteration %d", task_name, iteration)
                return

            # --- WORKER PHASE ---
            _update_status(status_path, {
                "status": "implementing",
                "iteration": iteration,
                "current_agent": "worker",
            })

            worker_prompt = _build_worker_prompt(task_md, workspace_path, iteration, feedback)
            worker_log = task_dir / f"worker_iter{iteration}.log"
            exit_code = _run_claude(worker_prompt, workspace_path, worker_log, status_path)

            _append_history(status_path, {
                "iteration": iteration,
                "agent": "worker",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "exit_code": exit_code,
            })

            if exit_code != 0:
                _update_status(status_path, {
                    "status": "failed",
                    "error": f"Worker exited with code {exit_code} on iteration {iteration}",
                    "current_agent": None,
                    "pid": None,
                })
                _notify(ctx, f"Long task '{task_name}' failed: worker exit code {exit_code} (iteration {iteration})")
                return

            # Check cancellation again
            status = _read_status(status_path)
            if status and status.get("cancelled"):
                return

            # --- REVIEW PHASE ---
            _update_status(status_path, {
                "status": "reviewing",
                "current_agent": "reviewer",
            })

            review_prompt = _build_review_prompt(task_md, workspace_path)
            reviewer_log = task_dir / f"reviewer_iter{iteration}.log"
            review_exit = _run_claude(review_prompt, workspace_path, reviewer_log, status_path)

            verdict, review_feedback = _parse_reviewer_log(reviewer_log)

            _append_history(status_path, {
                "iteration": iteration,
                "agent": "reviewer",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "exit_code": review_exit,
                "verdict": verdict,
                "feedback": review_feedback[:500] if review_feedback else "",
            })

            if verdict == "PASS":
                _update_status(status_path, {
                    "status": "complete",
                    "result": f"Completed in {iteration} iteration(s)",
                    "current_agent": None,
                    "pid": None,
                })
                _notify(ctx, f"Long task '{task_name}' completed successfully after {iteration} iteration(s).")
                return

            # Feed review feedback into next iteration
            feedback = review_feedback or "Reviewer found issues but gave no specific feedback."
            log.info("Task %s iteration %d: reviewer verdict=%s, looping", task_name, iteration, verdict)

        # Exhausted max iterations
        _update_status(status_path, {
            "status": "failed",
            "error": f"Exhausted {max_iterations} iterations without passing review",
            "current_agent": None,
            "pid": None,
        })
        _notify(ctx, f"Long task '{task_name}' failed: exhausted {max_iterations} iterations.")

    except Exception as exc:
        log.error("Task %s runner crashed: %s", task_name, exc)
        try:
            _update_status(status_path, {
                "status": "failed",
                "error": str(exc),
                "current_agent": None,
                "pid": None,
            })
        except Exception:
            pass
        _notify(ctx, f"Long task '{task_name}' crashed: {exc}")


def _run_claude(prompt: str, workspace: Path, log_file: Path, status_path: Path) -> int:
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "-p", prompt,
    ]

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # Allow nested Claude Code sessions

    with open(log_file, "w", encoding="utf-8") as f:
        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace),
            stdout=f,
            stderr=subprocess.STDOUT,
            env=env,
        )

    # Store PID for cancel support
    _update_status(status_path, {"pid": proc.pid})

    proc.wait()
    return proc.returncode


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _build_worker_prompt(task_md: str, workspace: Path, iteration: int, feedback: str) -> str:
    parts = [
        "You are a worker agent executing a coding task.",
        "IMPORTANT: Write code ONLY within the workspace directory.",
        "",
        "## Task",
        task_md,
        "",
        "## Workspace",
        str(workspace),
        "",
        "## Instructions",
        "- Implement the task fully and thoroughly.",
        "- Use sub-agents (Agent tool) for parallel work when the task has independent parts.",
        "- Run tests if applicable.",
        "- Be thorough — an automated reviewer will check your work next.",
    ]

    if iteration > 1 and feedback:
        parts.extend([
            "",
            f"## Previous Review Feedback (Iteration {iteration - 1})",
            "The reviewer found these issues that MUST be fixed:",
            feedback,
        ])

    return "\n".join(parts)


def _build_review_prompt(task_md: str, workspace: Path) -> str:
    return "\n".join([
        "You are a review agent evaluating whether a coding task is FULLY completed.",
        "",
        "## Task Definition",
        task_md,
        "",
        "## Workspace",
        str(workspace),
        "",
        "## Instructions",
        "1. Read the task definition carefully.",
        "2. Examine ALL implementation files in the workspace.",
        "3. Run tests, build commands, or verification steps mentioned in the task.",
        "4. Determine if the task is FULLY complete.",
        "",
        "## Output Format",
        "Write your verdict as the LAST line of output:",
        "- If complete: VERDICT: PASS",
        "- If incomplete: VERDICT: FAIL",
        "Then explain what is missing or wrong in detail.",
    ])


# ---------------------------------------------------------------------------
# Reviewer parsing
# ---------------------------------------------------------------------------

def _parse_reviewer_log(log_file: Path) -> tuple[str, str]:
    """Parse reviewer log for VERDICT line. Returns (verdict, feedback)."""
    if not log_file.exists():
        return "FAIL", "Reviewer log not found."

    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "FAIL", "Could not read reviewer log."

    lines = text.strip().splitlines()

    # Search from bottom for VERDICT line
    for line in reversed(lines):
        stripped = line.strip().upper()
        if "VERDICT: PASS" in stripped:
            # Collect everything after the verdict line as feedback
            idx = next(
                (i for i, l in enumerate(lines) if "VERDICT:" in l.upper()),
                len(lines),
            )
            feedback = "\n".join(lines[idx + 1:]).strip()
            return "PASS", feedback
        if "VERDICT: FAIL" in stripped:
            idx = next(
                (i for i, l in enumerate(lines) if "VERDICT:" in l.upper()),
                len(lines),
            )
            feedback = "\n".join(lines[idx + 1:]).strip()
            if not feedback:
                # Take everything before the verdict as feedback
                feedback = "\n".join(lines[:idx]).strip()[-2000:]
            return "FAIL", feedback

    # No verdict found — treat as fail
    return "FAIL", text[-2000:] if text else "No output from reviewer."


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def _read_status(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_status(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_status(path: Path, updates: dict) -> None:
    status = _read_status(path) or {}
    status.update(updates)
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_status(path, status)


def _append_history(path: Path, entry: dict) -> None:
    status = _read_status(path) or {}
    history = status.get("history", [])
    history.append(entry)
    status["history"] = history
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_status(path, status)


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------

def _kill_process_tree(pid: int) -> None:
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

def _notify(ctx: ToolContext, text: str) -> None:
    log.info("Notification: %s", text)
    if ctx.outbound_queue is None:
        return
    try:
        from ker.types import OutboundMessage
        msg = OutboundMessage(
            text=f"[long_task] {text}",
            channel=ctx.current_channel,
            user=ctx.current_user,
        )
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(ctx.outbound_queue.put_nowait, msg)
    except Exception as exc:
        log.warning("Failed to send notification: %s", exc)
