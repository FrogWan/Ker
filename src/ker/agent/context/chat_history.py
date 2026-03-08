from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import time


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
