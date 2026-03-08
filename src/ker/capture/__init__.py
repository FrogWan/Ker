"""ker.capture — standalone agent session parsers.

This package parses session files written by external coding agents
(Claude Code, Codex) into a uniform structured format.
"""

from __future__ import annotations

from pathlib import Path

from .claude_parser import find_project_dir as _claude_project_dir
from .claude_parser import parse_session as _parse_claude
from .codex_parser import parse_session as _parse_codex
from .codex_parser import session_files as _codex_files


def parse_session(
    agent: str,
    filepath: Path,
    working_dir: str = "",
    anonymizer: object | None = None,
) -> dict | None:
    if agent == "claude":
        return _parse_claude(filepath, anonymizer=anonymizer)
    if agent == "codex":
        return _parse_codex(filepath, target_cwd=working_dir, anonymizer=anonymizer)
    raise ValueError(f"Unknown agent: {agent!r}. Supported: 'claude', 'codex'")


def find_agent_session_files(agent: str, working_dir: str) -> list[Path]:
    if agent == "claude":
        project_dir = _claude_project_dir(working_dir)
        if project_dir is None or not project_dir.exists():
            return []
        return sorted(project_dir.rglob("*.jsonl"))
    if agent == "codex":
        return _codex_files()
    raise ValueError(f"Unknown agent: {agent!r}. Supported: 'claude', 'codex'")


__all__ = [
    "parse_session",
    "find_agent_session_files",
]
