from __future__ import annotations

import asyncio
import platform
import re
import time

from ker.logger import get_logger
from ker.tools.tool_base import ToolContext, safe_path

log = get_logger("tool_exec")


async def exec_command(ctx: ToolContext, command: str, timeout: int = 60, working_dir: str | None = None) -> str:
    guard = _guard_command(command)
    if guard:
        log.warning("Command blocked by guard: %s", command[:200])
        return guard
    cwd = ctx.workspace if not working_dir else safe_path(ctx.workspace, working_dir)

    log.info("exec START: cmd=%s timeout=%ds cwd=%s", repr(command[:200]), timeout, cwd)
    t0 = time.monotonic()

    # Cross-platform shell selection
    if platform.system() == "Windows":
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/sh",
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        log.error("exec TIMEOUT: cmd=%s elapsed=%.1fs timeout=%ds", repr(command[:200]), elapsed, timeout)
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        return f"Error: Command timed out after {timeout}s\nCommand: {command[:200]}"

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
    if len(result) > 10000:
        result = result[:10000] + f"\n... (truncated, {len(result) - 10000} more chars)"
    return result or "(no output)"


async def bash(ctx: ToolContext, command: str, timeout: int = 30) -> str:
    return await exec_command(ctx=ctx, command=command, timeout=timeout)


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
