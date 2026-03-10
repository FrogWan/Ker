from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import signal
import subprocess
import time
from pathlib import Path

from ker.logger import get_logger
from ker.tools.tool_base import ToolContext

log = get_logger("fallback")

DEFAULT_TIMEOUT = 7200  # 2 hours
MAX_OUTPUT = 10_000  # chars for notification
FALLBACK_DIR = "fallback"

# Keep references to background tasks so they aren't garbage-collected.
_background_tasks: dict[str, asyncio.Task] = {}


async def fallback(
    ctx: ToolContext,
    request: str,
    task_name: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    prefer: str | None = None,
) -> str:
    if not task_name:
        h = hashlib.sha256(request.encode()).hexdigest()[:6]
        task_name = f"fb_{int(time.time())}_{h}"

    claude_path = shutil.which("claude")
    codex_path = shutil.which("codex")

    if not claude_path and not codex_path:
        return "Error: Neither 'claude' nor 'codex' CLI found on PATH."

    # Determine CLI order based on preference and availability
    clis = _resolve_cli_order(prefer, claude_path, codex_path)

    task_dir = ctx.ker_root / FALLBACK_DIR / task_name
    task_dir.mkdir(parents=True, exist_ok=True)

    task = asyncio.create_task(
        _run_fallback(ctx, task_name, task_dir, request, clis, timeout),
        name=f"fallback-{task_name}",
    )
    _background_tasks[task_name] = task
    task.add_done_callback(lambda t: _background_tasks.pop(task_name, None))

    return f"Working on your request. I'll notify you when the answer is ready. (task: {task_name})"


def _resolve_cli_order(
    prefer: str | None,
    claude_path: str | None,
    codex_path: str | None,
) -> list[tuple[str, str]]:
    """Return ordered list of (name, path) tuples to try."""
    available: dict[str, str] = {}
    if claude_path:
        available["claude"] = claude_path
    if codex_path:
        available["codex"] = codex_path

    if prefer and prefer in available:
        order = [prefer] + [k for k in available if k != prefer]
    else:
        # Default: claude first
        order = sorted(available.keys(), key=lambda k: 0 if k == "claude" else 1)

    return [(name, available[name]) for name in order]


def _build_command(cli_name: str, cli_path: str, request: str) -> list[str]:
    if cli_name == "claude":
        return [cli_path, "--dangerously-skip-permissions", "-p", request]
    else:
        return [cli_path, "exec", request, "--full-auto"]


async def _run_fallback(
    ctx: ToolContext,
    task_name: str,
    task_dir: Path,
    request: str,
    clis: list[tuple[str, str]],
    timeout: int,
) -> None:
    last_error = ""
    for cli_name, cli_path in clis:
        log_file = task_dir / f"{cli_name}.log"
        cmd = _build_command(cli_name, cli_path, request)

        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        try:
            with open(log_file, "w", encoding="utf-8") as f:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(ctx.workspace),
                    stdout=f,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.DEVNULL,
                    env=env,
                )

                try:
                    await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    log.warning("Fallback %s/%s timed out after %ds", task_name, cli_name, timeout)
                    _kill_process_tree(proc.pid)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        proc.kill()
                    last_error = f"{cli_name} timed out after {timeout}s"
                    continue

            exit_code = proc.returncode if proc.returncode is not None else -1
            if exit_code != 0:
                last_error = f"{cli_name} exited with code {exit_code}"
                log.info("Fallback %s/%s failed: %s", task_name, cli_name, last_error)
                continue

            # Success — read output and notify
            output = _read_output(log_file)
            await _notify(ctx, task_name, output)
            return

        except Exception as exc:
            last_error = f"{cli_name} error: {exc}"
            log.error("Fallback %s/%s crashed: %s", task_name, cli_name, exc)
            continue

    # All CLIs failed
    await _notify_error(ctx, task_name, last_error)


def _read_output(log_file: Path) -> str:
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "(could not read output)"
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n... (truncated, {len(text)} total chars)"
    return text


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


async def _notify(ctx: ToolContext, task_name: str, output: str) -> None:
    text = f"Here's the result for '{task_name}':\n{output}"
    await _send(ctx, text)


async def _notify_error(ctx: ToolContext, task_name: str, error: str) -> None:
    text = f"Could not complete '{task_name}': {error}"
    await _send(ctx, text)


async def _send(ctx: ToolContext, text: str) -> None:
    log.info("Notification: %s", text[:200])
    if ctx.outbound_queue is None:
        return
    try:
        from ker.types import OutboundMessage
        msg = OutboundMessage(
            text=f"[fallback] {text}",
            channel=ctx.current_channel,
            user=ctx.current_user,
        )
        await ctx.outbound_queue.put(msg)
    except Exception as exc:
        log.warning("Failed to send notification: %s", exc)
