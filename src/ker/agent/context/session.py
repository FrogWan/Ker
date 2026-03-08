from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
import json
import time
from typing import Any

from ker.logger import get_logger

log = get_logger("session")

SESSION_NAME_MAX_LENGTH = 64
SESSION_NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"
SESSION_NAME_ALLOWED_CHARS_DESC = "letters, digits, hyphens, underscores"


def sanitize_session_name(name: str) -> str:
    """Sanitize a session name so it is safe for use in filenames.

    - Strips whitespace
    - Replaces characters not in [a-zA-Z0-9_-] with hyphens
    - Collapses consecutive hyphens and strips leading/trailing hyphens
    - Truncates to SESSION_NAME_MAX_LENGTH
    - Falls back to "default" for empty/dot-only inputs
    """
    s = (name or "").strip()
    if not s or s in (".", ".."):
        return "default"
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    if len(s) > SESSION_NAME_MAX_LENGTH:
        s = s[:SESSION_NAME_MAX_LENGTH].rstrip("-")
    return s or "default"


def _ts() -> dict[str, Any]:
    """Return both epoch and human-readable timestamp."""
    now = time.time()
    return {"ts": now, "time": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}


class SessionStore:
    def __init__(self, ker_root: Path) -> None:
        self.ker_root = ker_root

    def _session_path(self, agent_name: str, session_id: str) -> Path:
        return self.ker_root / "agents" / agent_name / "session" / f"{session_id}.jsonl"

    def _ensure_parent(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def _append_record(self, path: Path, record: dict[str, Any]) -> None:
        self._ensure_parent(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append_user(self, agent_name: str, session_id: str, content: str, media: list | None = None) -> None:
        record = {"type": "user", "content": content, **_ts()}
        if media:
            record["media"] = media
        self._append_record(
            self._session_path(agent_name, session_id),
            record,
        )

    def append_assistant(self, agent_name: str, session_id: str, content: list[dict[str, Any]]) -> None:
        self._append_record(
            self._session_path(agent_name, session_id),
            {"type": "assistant", "content": content, **_ts()},
        )

    def append_tool_use(self, agent_name: str, session_id: str, tool_use_id: str, name: str, tool_input: dict[str, Any]) -> None:
        self._append_record(
            self._session_path(agent_name, session_id),
            {"type": "tool_use", "tool_use_id": tool_use_id, "name": name, "input": tool_input, **_ts()},
        )

    def append_tool_result(self, agent_name: str, session_id: str, tool_use_id: str, content: str) -> None:
        self._append_record(
            self._session_path(agent_name, session_id),
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, **_ts()},
        )

    def load_messages(self, agent_name: str, session_id: str) -> list[dict[str, Any]]:
        path = self._session_path(agent_name, session_id)
        if not path.exists():
            return []
        return self._rebuild_history(path)

    def replace_messages(self, agent_name: str, session_id: str, messages: list[dict[str, Any]]) -> None:
        path = self._session_path(agent_name, session_id)
        self._ensure_parent(path)
        records = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" and isinstance(content, str):
                records.append({"type": "user", "content": content, **_ts()})
            elif role == "assistant":
                records.append({"type": "assistant", "content": content, **_ts()})
            elif role == "user" and isinstance(content, list):
                # Check if this is a tool_result list or a text/image content block list
                first_type = content[0].get("type", "") if content else ""
                if first_type == "tool_result":
                    for block in content:
                        if block.get("type") == "tool_result":
                            records.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.get("tool_use_id", ""),
                                    "content": block.get("content", ""),
                                    "ts": time.time(),
                                }
                            )
                else:
                    # text/image content blocks — extract text, preserve media refs
                    text = " ".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
                    media = [
                        {"media_type": b["source"]["media_type"], "path": b["source"].get("_path", ""), "id": ""}
                        for b in content if b.get("type") == "image" and isinstance(b.get("source"), dict)
                    ]
                    record: dict[str, Any] = {"type": "user", "content": text, **_ts()}
                    if media and any(m["path"] for m in media):
                        record["media"] = [m for m in media if m["path"]]
                    records.append(record)
        with path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _rebuild_history(self, path: Path) -> list[dict[str, Any]]:
        lines = path.read_text(encoding="utf-8").splitlines()
        messages: list[dict[str, Any]] = []
        # Track indices of user messages with media so we can
        # load base64 only for the last N to bound context size.
        user_media_indices: list[int] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                log.warning("Skipping malformed session record in %s", path)
                continue
            rtype = record.get("type")
            if rtype == "user":
                media = record.get("media")
                if media:
                    user_media_indices.append(len(messages))
                messages.append({"role": "user", "content": record["content"], "_media": media})
            elif rtype == "assistant":
                content = record["content"]
                if isinstance(content, str):
                    content = [{"type": "text", "text": content}]
                messages.append({"role": "assistant", "content": content})
            elif rtype == "tool_use":
                block = {
                    "type": "tool_use",
                    "id": record["tool_use_id"],
                    "name": record["name"],
                    "input": record["input"],
                }
                if messages and messages[-1]["role"] == "assistant":
                    messages[-1]["content"].append(block)
                else:
                    messages.append({"role": "assistant", "content": [block]})
            elif rtype == "tool_result":
                block = {
                    "type": "tool_result",
                    "tool_use_id": record["tool_use_id"],
                    "content": record["content"],
                }
                if (
                    messages
                    and messages[-1]["role"] == "user"
                    and isinstance(messages[-1]["content"], list)
                    and messages[-1]["content"]
                    and messages[-1]["content"][0].get("type") == "tool_result"
                ):
                    messages[-1]["content"].append(block)
                else:
                    messages.append({"role": "user", "content": [block]})

        # Resolve media references for the last 5 user messages with media
        # to keep context size bounded.  Import here to avoid circular deps.
        from ker.media import load_media_base64

        recent_media = user_media_indices[-5:] if len(user_media_indices) > 5 else user_media_indices
        recent_set = set(recent_media)

        for idx, msg in enumerate(messages):
            media = msg.pop("_media", None)
            if msg["role"] != "user" or not media:
                continue
            if idx not in recent_set:
                # Old message — keep text only, skip image blocks
                continue
            # Build content blocks with images
            content_blocks = []
            text_content = msg["content"]
            if text_content:
                content_blocks.append({"type": "text", "text": text_content})
            for m in media:
                b64 = load_media_base64(self.ker_root, m)
                if b64:
                    content_blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": m["media_type"], "data": b64},
                    })
            if content_blocks:
                msg["content"] = content_blocks

        return messages
