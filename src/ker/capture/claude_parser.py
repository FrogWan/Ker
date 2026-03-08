"""Parse Claude Code session JSONL files into structured conversations.

This module is intentionally self-contained: stdlib only, no Ker imports.

Claude Code writes one JSONL file per session under:
    ~/.claude/projects/<encoded-path>/<session-uuid>.jsonl

Each line is a JSON object with type "user" or "assistant".
User entries carry the human prompt (and tool results from the previous turn).
Assistant entries carry the model response (text, thinking blocks, tool calls).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class _NoOpAnonymizer:
    """No-op replacement for the removed Anonymizer class."""
    def path(self, p: str) -> str:
        return p
    def text(self, t: str) -> str:
        return t

Anonymizer = _NoOpAnonymizer


def _redact_text(text: str) -> tuple[str, int]:
    return text, 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_session(filepath: Path, anonymizer: object | None = None) -> dict | None:
    """Parse a single Claude Code session JSONL file.

    Args:
        filepath:   Path to the ``.jsonl`` session file.
        anonymizer: Optional :class:`Anonymizer` instance. If omitted, a
                    default one is created (hashes the current OS username).

    Returns a structured dict::

        {
            "session_id": str,
            "model": str | None,
            "git_branch": str | None,
            "start_time": str | None,
            "end_time": str | None,
            "messages": [
                {
                    "role": "user" | "assistant",
                    "content": str,          # present when there is text
                    "thinking": str,         # present when assistant has thinking blocks
                    "tool_uses": [...],      # present when assistant called tools
                    "timestamp": str | None,
                }
            ],
            "stats": {
                "user_messages": int,
                "assistant_messages": int,
                "tool_uses": int,
                "input_tokens": int,
                "output_tokens": int,
            },
        }

    Returns ``None`` if the file cannot be read or contains no messages.
    """
    if anonymizer is None:
        anonymizer = _NoOpAnonymizer()

    try:
        entries = list(_iter_jsonl(filepath))
    except OSError:
        return None

    metadata: dict[str, Any] = {
        "session_id": filepath.stem,
        "cwd": None,
        "git_branch": None,
        "model": None,
        "start_time": None,
        "end_time": None,
    }
    stats = _make_stats()
    messages: list[dict[str, Any]] = []

    # Pre-pass: map tool_use_id -> {output, status} from tool_result blocks
    tool_result_map = _build_tool_result_map(entries, anonymizer)

    for entry in entries:
        _process_entry(entry, messages, metadata, stats, anonymizer, tool_result_map)

    if not messages:
        return None

    return _make_result(metadata, messages, stats)


def find_project_dir(working_dir: str) -> Path | None:
    """Return the Claude Code project directory for a given working directory.

    Claude Code encodes the working directory path as the project folder name
    by replacing path separators with hyphens and stripping the leading one.

    Examples:
        /home/user/Code/Ker   -> home-user-Code-Ker
        C:\\Code\\Ker          -> C--Code-Ker
    """
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        return None

    encoded = working_dir.replace(":", "").replace("\\", "-").replace("/", "-").lstrip("-")
    candidate = projects_root / encoded
    if candidate.exists():
        return candidate

    # Fallback: match on the project basename
    name = Path(working_dir).name.lower()
    for d in projects_root.iterdir():
        if d.is_dir() and name in d.name.lower():
            return d

    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _iter_jsonl(filepath: Path):
    with filepath.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _make_stats() -> dict[str, int]:
    return {
        "user_messages": 0,
        "assistant_messages": 0,
        "tool_uses": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def _make_result(metadata: dict, messages: list, stats: dict) -> dict:
    return {
        "session_id": metadata["session_id"],
        "model": metadata["model"],
        "git_branch": metadata["git_branch"],
        "start_time": metadata["start_time"],
        "end_time": metadata["end_time"],
        "messages": messages,
        "stats": stats,
    }


def _normalize_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    return None


def _update_time_bounds(metadata: dict, ts: str | None) -> None:
    if ts is None:
        return
    if metadata["start_time"] is None:
        metadata["start_time"] = ts
    metadata["end_time"] = ts


def _build_tool_result_map(entries: list[dict], anonymizer: Anonymizer) -> dict[str, dict]:
    """Pre-pass: map tool_use_id -> {output, status} from tool_result content blocks."""
    result: dict[str, dict] = {}
    for entry in entries:
        if entry.get("type") != "user":
            continue
        for block in entry.get("message", {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id")
            if not tid:
                continue
            is_error = bool(block.get("is_error"))
            content = block.get("content", "")
            if isinstance(content, list):
                text = "\n\n".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ).strip()
            else:
                text = str(content).strip() if content else ""
            result[tid] = {
                "output": {"text": anonymizer.text(text)} if text else {},
                "status": "error" if is_error else "success",
                "timestamp": _normalize_ts(entry.get("timestamp")),
            }
    return result


def _process_entry(
    entry: dict,
    messages: list,
    metadata: dict,
    stats: dict,
    anonymizer: Anonymizer,
    tool_result_map: dict,
) -> None:
    entry_type = entry.get("type")

    # Capture metadata from the first entry that carries it
    if metadata["cwd"] is None and entry.get("cwd"):
        metadata["cwd"] = anonymizer.path(entry["cwd"])
        metadata["git_branch"] = entry.get("gitBranch")
        metadata["session_id"] = entry.get("sessionId", metadata["session_id"])

    ts = _normalize_ts(entry.get("timestamp"))

    if entry_type == "user":
        content = _extract_user_content(entry, anonymizer)
        if content is not None:
            messages.append({"role": "user", "content": content, "timestamp": ts})
            stats["user_messages"] += 1
            _update_time_bounds(metadata, ts)

    elif entry_type == "assistant":
        msg = _extract_assistant_content(entry, anonymizer, tool_result_map)
        if msg:
            if metadata["model"] is None:
                metadata["model"] = entry.get("message", {}).get("model")
            usage = entry.get("message", {}).get("usage", {})
            stats["input_tokens"] += usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
            stats["output_tokens"] += usage.get("output_tokens", 0)
            stats["tool_uses"] += len(msg.get("tool_uses", []))
            msg["timestamp"] = ts
            messages.append(msg)
            stats["assistant_messages"] += 1
            _update_time_bounds(metadata, ts)


def _extract_user_content(entry: dict, anonymizer: Anonymizer) -> str | None:
    msg_data = entry.get("message", {})
    content = msg_data.get("content", "")
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = "\n".join(parts)
    if not content or not content.strip():
        return None
    return anonymizer.text(content.strip())


def _extract_assistant_content(
    entry: dict, anonymizer: Anonymizer, tool_result_map: dict
) -> dict | None:
    msg_data = entry.get("message", {})
    content_blocks = msg_data.get("content", [])
    if not isinstance(content_blocks, list):
        return None

    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_uses: list[dict] = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "").strip()
            if text:
                text_parts.append(anonymizer.text(text))
        elif btype == "thinking":
            thinking = block.get("thinking", "").strip()
            if thinking:
                thinking_parts.append(anonymizer.text(thinking))
        elif btype == "tool_use":
            tu: dict[str, Any] = {
                "tool": block.get("name"),
                "input": _parse_tool_input(block.get("name"), block.get("input", {}), anonymizer),
            }
            if block.get("id"):
                tu["tool_use_id"] = block.get("id")
            result = tool_result_map.get(block.get("id", ""))
            if result:
                tu["output"] = result["output"]
                tu["status"] = result["status"]
                if result.get("timestamp"):
                    tu["output_timestamp"] = result["timestamp"]
            tool_uses.append(tu)

    if not text_parts and not tool_uses and not thinking_parts:
        return None

    msg: dict[str, Any] = {"role": "assistant"}
    if text_parts:
        msg["content"] = "\n\n".join(text_parts)
    if thinking_parts:
        msg["thinking"] = "\n\n".join(thinking_parts)
    if tool_uses:
        msg["tool_uses"] = tool_uses
    return msg


def _parse_tool_input(tool_name: str | None, input_data: Any, anonymizer: Anonymizer) -> dict:
    """Return a structured dict for a tool's input args with paths/secrets cleaned."""
    if not isinstance(input_data, dict):
        return {"raw": anonymizer.text(str(input_data))}

    name = (tool_name or "").lower()

    # Claude Code built-in tools
    if name in ("read", "edit"):
        return {"file_path": anonymizer.path(input_data.get("file_path", ""))}
    if name == "write":
        return {
            "file_path": anonymizer.path(input_data.get("file_path", "")),
            "content": anonymizer.text(input_data.get("content", "")),
        }
    if name == "bash":
        cmd, _ = _redact_text(input_data.get("command", ""))
        return {"command": anonymizer.text(cmd)}
    if name == "grep":
        pattern, _ = _redact_text(input_data.get("pattern", ""))
        return {
            "pattern": anonymizer.text(pattern),
            "path": anonymizer.path(input_data.get("path", "")),
        }
    if name == "glob":
        return {
            "pattern": input_data.get("pattern", ""),
            "path": anonymizer.path(input_data.get("path", "")),
        }
    if name == "task":
        return {"prompt": anonymizer.text(input_data.get("prompt", ""))}
    if name == "websearch":
        return {"query": anonymizer.text(input_data.get("query", ""))}
    if name == "webfetch":
        return {"url": anonymizer.text(input_data.get("url", ""))}
    if name == "apply_patch":
        return {"patch": anonymizer.text(input_data.get("patchText", ""))}
    if name == "codesearch":
        return {"query": anonymizer.text(input_data.get("query", ""))}

    # Fallback: anonymize all string values
    return {k: anonymizer.text(str(v)) if isinstance(v, str) else v for k, v in input_data.items()}
