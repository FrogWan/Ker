from __future__ import annotations

import asyncio
import os
import platform
import re
import signal
import time

from ker.logger import get_logger
from ker.tools.tool_base import ToolContext, safe_path

log = get_logger("tool_exec")

IS_WINDOWS = platform.system() == "Windows"
MAX_TIMEOUT = 300  # Hard cap regardless of what the LLM sends


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a process and all its children. On Windows, taskkill /T is
    required because proc.kill() only kills the shell, leaving child
    processes (e.g. node spawned by npx) alive and holding resources."""
    pid = proc.pid
    if pid is None:
        return
    if IS_WINDOWS:
        # taskkill /F /T kills the entire process tree
        try:
            kill_proc = await asyncio.create_subprocess_shell(
                f"taskkill /F /T /PID {pid}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(kill_proc.wait(), timeout=10)
        except Exception:
            # Fallback to basic kill
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    else:
        # On Unix, kill the process group
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass


async def exec_command(ctx: ToolContext, command: str, timeout: int = 60, working_dir: str | None = None, stdin_text: str | None = None) -> str:
    guard = _guard_command(command)
    if guard:
        log.warning("Command blocked by guard: %s", command[:200])
        return guard
    cwd = ctx.workspace if not working_dir else safe_path(ctx.workspace, working_dir)

    # Enforce hard timeout cap
    timeout = min(max(timeout, 1), MAX_TIMEOUT)

    log.info("exec START: cmd=%s timeout=%ds cwd=%s stdin=%s", repr(command[:200]), timeout, cwd, "pipe" if stdin_text else "devnull")
    t0 = time.monotonic()

    # stdin=DEVNULL by default prevents commands (e.g. npx "Ok to proceed?")
    # from hanging forever waiting for user input.  When stdin_text is
    # provided, use PIPE so the caller can feed data to the process.
    use_pipe = stdin_text is not None
    stdin_mode = asyncio.subprocess.PIPE if use_pipe else asyncio.subprocess.DEVNULL

    if IS_WINDOWS:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdin=stdin_mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdin=stdin_mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/sh",
            start_new_session=True,  # Allows os.killpg on Unix
        )

    try:
        stdin_bytes = stdin_text.encode() if stdin_text else None
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin_bytes), timeout=timeout
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        log.error("exec TIMEOUT: cmd=%s elapsed=%.1fs timeout=%ds", repr(command[:200]), elapsed, timeout)
        await _kill_process_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        return f"Error: Command timed out after {timeout}s\nCommand: {command[:200]}"
    except asyncio.CancelledError:
        log.info("exec CANCELLED: cmd=%s", repr(command[:200]))
        await _kill_process_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        raise

    elapsed = time.monotonic() - t0
    out = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
    err = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
    returncode = proc.returncode or 0
    result = (out + ("\nSTDERR:\n" + err if err.strip() else "")).strip()
    if returncode != 0:
        result = (result + f"\n\nExit code: {returncode}").strip()
        log.info("exec DONE: cmd=%s elapsed=%.1fs exit=%d result_len=%d", repr(command[:80]), elapsed, returncode, len(result))
    else:
        log.info("exec DONE: cmd=%s elapsed=%.1fs result_len=%d", repr(command[:80]), elapsed, len(result))
    if len(result) > 30000:
        result = result[:30000] + f"\n... (truncated, {len(result) - 30000} more chars)"
    return result or "(no output)"


async def bash(ctx: ToolContext, command: str, timeout: int = 30, stdin_text: str | None = None) -> str:
    return await exec_command(ctx=ctx, command=command, timeout=timeout, stdin_text=stdin_text)


def _guard_command(command: str) -> str | None:
    lower = command.strip().lower()
    patterns = [
        r"\brm\s+-[rf]{1,2}\b",
        r"\bdel\s+/[fq]\b",
        r"\brmdir\s+/s\b",
        r"(?:^|[;&|]\s*)format\b",
        r"\b(mkfs|diskpart)\b",
        r"\bdd\s+if=",
        r">\s*/dev/sd",
        r"\b(shutdown|reboot|poweroff)\b",
        r":\(\)\s*\{.*\};\s*:",
    ]
    for pattern in patterns:
        if re.search(pattern, lower):
            return "Error: Command blocked by safety guard (dangerous pattern detected)"
    if "..\\" in command or "../" in command:
        return "Error: Command blocked by safety guard (path traversal detected)"
    return None
