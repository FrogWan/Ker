from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import time

from ker.logger import get_logger

log = get_logger("chat_history")


class ChatHistory:
    def __init__(self, ker_root: Path) -> None:
        self.ker_root = ker_root

    def _history_path(self, agent_name: str) -> Path:
        return self.ker_root / "agents" / agent_name / "chatHistory" / "chatHistory.jsonl"

    def append(self, agent_name: str, role: str, content: str) -> None:
        path = self._history_path(agent_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        record = {
            "role": role,
            "content": content,
            "ts": now,
            "time": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def rotate(self, agent_name: str, max_entries: int = 500) -> bool:
        """Archive oldest 80% of chat history when exceeding max_entries.

        Archived to .ker/memory/archive/chat/{agent}/YYYY-MM-DD.jsonl
        """
        path = self._history_path(agent_name)
        if not path.exists():
            return False

        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_entries:
            return False

        keep_count = max(1, len(lines) // 5)  # Keep newest 20%
        to_archive = lines[:-keep_count]
        to_keep = lines[-keep_count:]

        # Archive old entries
        archive_dir = self.ker_root / "memory" / "archive" / "chat" / agent_name
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        archive_path = archive_dir / archive_name

        # Append to existing archive file for same day
        with archive_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(to_archive) + "\n")

        # Rewrite active file
        path.write_text("\n".join(to_keep) + "\n", encoding="utf-8")
        log.info(
            "Rotated chat history for %s: archived %d entries, kept %d",
            agent_name, len(to_archive), len(to_keep),
        )
        return True
