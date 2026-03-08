from __future__ import annotations

import platform
import re
import subprocess

from ker.tools.tool_base import ToolContext, safe_path


def exec_command(ctx: ToolContext, command: str, timeout: int = 60, working_dir: str | None = None) -> str:
    guard = _guard_command(command)
    if guard:
        return guard
    cwd = ctx.workspace if not working_dir else safe_path(ctx.workspace, working_dir)

    # Cross-platform shell selection
    if platform.system() == "Windows":
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=True
        )
    else:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=True,
            executable="/bin/sh",
        )

    out = completed.stdout or ""
    err = completed.stderr or ""
    result = (out + ("\nSTDERR:\n" + err if err.strip() else "")).strip()
    if completed.returncode != 0:
        result = (result + f"\n\nExit code: {completed.returncode}").strip()
    if len(result) > 10000:
        result = result[:10000] + f"\n... (truncated, {len(result) - 10000} more chars)"
    return result or "(no output)"


def bash(ctx: ToolContext, command: str, timeout: int = 30) -> str:
    return exec_command(ctx=ctx, command=command, timeout=timeout)


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
