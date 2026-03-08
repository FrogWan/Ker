from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ker.logger import get_logger

log = get_logger("delivery")

BACKOFF_MS = [5_000, 25_000, 120_000, 600_000]
MAX_RETRIES = 5


def compute_backoff_ms(retry_count: int) -> int:
    if retry_count <= 0:
        return 0
    idx = min(retry_count - 1, len(BACKOFF_MS) - 1)
    base = BACKOFF_MS[idx]
    jitter = random.randint(-base // 5, base // 5)
    return max(0, base + jitter)


def chunk_message(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = para if not current else current + "\n\n" + para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= max_chars:
            current = para
        else:
            for i in range(0, len(para), max_chars):
                chunks.append(para[i : i + max_chars])
            current = ""
    if current:
        chunks.append(current)
    return chunks


@dataclass
class QueuedDelivery:
    id: str
    channel: str
    to: str
    text: str
    enqueued_at: float
    retry_count: int = 0
    next_retry_at: float = 0.0
    last_error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel": self.channel,
            "to": self.to,
            "text": self.text,
            "enqueued_at": self.enqueued_at,
            "retry_count": self.retry_count,
            "next_retry_at": self.next_retry_at,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QueuedDelivery:
        return cls(
            id=data["id"],
            channel=data["channel"],
            to=data["to"],
            text=data["text"],
            enqueued_at=float(data.get("enqueued_at", 0.0)),
            retry_count=int(data.get("retry_count", 0)),
            next_retry_at=float(data.get("next_retry_at", 0.0)),
            last_error=str(data.get("last_error", "")),
        )


class AsyncDeliveryQueue:
    def __init__(self, root: Path) -> None:
        self.queue_dir = root / "delivery" / "queue"
        self.failed_dir = root / "delivery" / "failed"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, channel: str, to: str, text: str) -> str:
        did = uuid.uuid4().hex[:12]
        entry = QueuedDelivery(id=did, channel=channel, to=to, text=text, enqueued_at=time.time())
        self._write_entry(entry)
        return did

    def _entry_path(self, did: str) -> Path:
        return self.queue_dir / f"{did}.json"

    def _write_entry(self, entry: QueuedDelivery) -> None:
        path = self._entry_path(entry.id)
        path.write_text(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_pending(self) -> list[QueuedDelivery]:
        items = []
        for p in self.queue_dir.glob("*.json"):
            try:
                items.append(QueuedDelivery.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError):
                continue
        items.sort(key=lambda x: x.enqueued_at)
        return items

    def ack(self, did: str) -> None:
        p = self._entry_path(did)
        if p.exists():
            p.unlink()

    def fail(self, did: str, error: str) -> None:
        import os

        p = self._entry_path(did)
        if not p.exists():
            return
        entry = QueuedDelivery.from_dict(json.loads(p.read_text(encoding="utf-8")))
        entry.retry_count += 1
        entry.last_error = error
        if entry.retry_count >= MAX_RETRIES:
            os.replace(p, self.failed_dir / p.name)
            return
        entry.next_retry_at = time.time() + compute_backoff_ms(entry.retry_count) / 1000.0
        self._write_entry(entry)

    def failed(self) -> list[QueuedDelivery]:
        out = []
        for p in self.failed_dir.glob("*.json"):
            try:
                out.append(QueuedDelivery.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError):
                continue
        return out
