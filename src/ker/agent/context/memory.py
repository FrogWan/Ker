from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import re
import time

from ker.logger import get_logger

log = get_logger("memory")


@dataclass
class MemoryHit:
    path: str
    score: float
    snippet: str


class MemoryStore:
    def __init__(self, workspace: Path, ker_root: Path) -> None:
        self.workspace = workspace
        self.ker_root = ker_root

    @property
    def error_log_path(self) -> Path:
        return self.ker_root / "memory" / "ERROR_LOG.jsonl"

    def add_daily(self, text: str) -> None:
        daily_dir = self.ker_root / "memory" / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now().strftime("%Y-%m-%d")
        p = daily_dir / f"{day}.jsonl"
        now = time.time()
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now,
                "time": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "text": text,
            }, ensure_ascii=False) + "\n")

    def add_error(self, source: str, message: str, context: dict | None = None) -> None:
        self.error_log_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        rec = {
            "ts": now,
            "time": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "source": source,
            "message": message,
            "context": context or {},
        }
        with self.error_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.error("%s: %s", source, message)

    def read_error_log(self, limit: int = 50) -> list[dict]:
        if not self.error_log_path.exists():
            return []
        rows = []
        for line in self.error_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows[-max(1, limit) :]

    def search_memory(self, query: str, top_k: int = 5) -> list[MemoryHit]:
        chunks = self._load_chunks()
        if not chunks:
            return []
        query_tokens = self._tokenize(query)
        chunk_tokens = [self._tokenize(c["text"]) for c in chunks]
        n = len(chunk_tokens)
        df: dict[str, int] = {}
        for toks in chunk_tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1

        def tfidf(tokens: list[str]) -> dict[str, float]:
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            out: dict[str, float] = {}
            for t, c in tf.items():
                out[t] = c * (math.log((n + 1) / (df.get(t, 0) + 1)) + 1)
            return out

        def cosine(a: dict[str, float], b: dict[str, float]) -> float:
            common = set(a).intersection(b)
            if not common:
                return 0.0
            dot = sum(a[k] * b[k] for k in common)
            na = math.sqrt(sum(v * v for v in a.values()))
            nb = math.sqrt(sum(v * v for v in b.values()))
            if na == 0 or nb == 0:
                return 0.0
            return dot / (na * nb)

        qvec = tfidf(query_tokens)
        scored: list[MemoryHit] = []
        now = time.time()
        for i, toks in enumerate(chunk_tokens):
            base = cosine(qvec, tfidf(toks))
            if base <= 0:
                continue
            age_days = max(0.0, (now - chunks[i]["ts"]) / 86400.0)
            score = base * math.exp(-0.02 * age_days)
            scored.append(MemoryHit(path=chunks[i]["path"], score=score, snippet=chunks[i]["text"][:220]))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def search_chat_history(self, agent_name: str, query: str, top_k: int = 5) -> list[MemoryHit]:
        chat_path = self.ker_root / "agents" / agent_name / "chatHistory" / "chatHistory.jsonl"
        if not chat_path.exists():
            return []
        chunks: list[dict] = []
        for line in chat_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                chunks.append({"path": str(chat_path), "text": rec.get("content", ""), "ts": float(rec.get("ts", 0.0))})
            except json.JSONDecodeError:
                continue
        if not chunks:
            return []
        # Reuse the same TF-IDF scoring
        return self._score_chunks(chunks, query, top_k)

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9_]+", text.lower())

    def _score_chunks(self, chunks: list[dict], query: str, top_k: int) -> list[MemoryHit]:
        query_tokens = self._tokenize(query)
        chunk_tokens = [self._tokenize(c["text"]) for c in chunks]
        n = len(chunk_tokens)
        df: dict[str, int] = {}
        for toks in chunk_tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1

        def tfidf(tokens: list[str]) -> dict[str, float]:
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            out: dict[str, float] = {}
            for t, c in tf.items():
                out[t] = c * (math.log((n + 1) / (df.get(t, 0) + 1)) + 1)
            return out

        def cosine(a: dict[str, float], b: dict[str, float]) -> float:
            common = set(a).intersection(b)
            if not common:
                return 0.0
            dot = sum(a[k] * b[k] for k in common)
            na = math.sqrt(sum(v * v for v in a.values()))
            nb = math.sqrt(sum(v * v for v in b.values()))
            if na == 0 or nb == 0:
                return 0.0
            return dot / (na * nb)

        qvec = tfidf(query_tokens)
        scored: list[MemoryHit] = []
        now = time.time()
        for i, toks in enumerate(chunk_tokens):
            base = cosine(qvec, tfidf(toks))
            if base <= 0:
                continue
            age_days = max(0.0, (now - chunks[i]["ts"]) / 86400.0)
            score = base * math.exp(-0.02 * age_days)
            scored.append(MemoryHit(path=chunks[i]["path"], score=score, snippet=chunks[i]["text"][:220]))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    @property
    def history_path(self) -> Path:
        return self.ker_root / "HISTORY.md"

    async def consolidate(self, summarize_fn=None) -> bool:
        """Consolidate old daily memory entries into HISTORY.md.

        Args:
            summarize_fn: Optional async callable(text) -> str that uses an LLM
                to summarize a batch of daily entries. If None, raw entries are
                appended directly.

        Returns:
            True if consolidation was performed.
        """
        daily_dir = self.ker_root / "memory" / "daily"
        if not daily_dir.exists():
            return False

        files = sorted(daily_dir.glob("*.jsonl"))
        if len(files) < 2:
            return False

        # Consolidate all but the most recent file
        to_consolidate = files[:-1]
        all_entries: list[str] = []
        for f in to_consolidate:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    all_entries.append(rec.get("text", ""))
                except json.JSONDecodeError:
                    continue

        if not all_entries:
            return False

        combined = "\n".join(all_entries)
        if summarize_fn:
            try:
                summary = await summarize_fn(
                    f"Summarize these daily memory entries into a concise history section:\n\n{combined}"
                )
            except Exception:
                summary = combined
        else:
            summary = combined

        # Append to HISTORY.md
        header = f"\n\n## {to_consolidate[0].stem} to {to_consolidate[-1].stem}\n\n"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as f:
            if not self.history_path.exists() or self.history_path.stat().st_size == 0:
                f.write("# History\n\nConsolidated memory entries.\n")
            f.write(header + summary + "\n")

        # Remove consolidated files
        for f in to_consolidate:
            f.unlink()

        log.info("Consolidated %d daily files into HISTORY.md", len(to_consolidate))
        return True

    def _load_chunks(self) -> list[dict]:
        chunks: list[dict] = []
        memory_md = self.ker_root / "MEMORY.md"
        if memory_md.exists():
            text = memory_md.read_text(encoding="utf-8")
            for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
                chunks.append({"path": "MEMORY.md", "text": para, "ts": memory_md.stat().st_mtime})

        # Include HISTORY.md in search
        if self.history_path.exists():
            text = self.history_path.read_text(encoding="utf-8")
            for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
                chunks.append({"path": "HISTORY.md", "text": para, "ts": self.history_path.stat().st_mtime})

        daily_dir = self.ker_root / "memory" / "daily"
        if daily_dir.exists():
            for p in daily_dir.glob("*.jsonl"):
                for line in p.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        chunks.append({"path": str(p), "text": rec.get("text", ""), "ts": float(rec.get("ts", 0.0))})
                    except json.JSONDecodeError:
                        continue
        if self.error_log_path.exists():
            for line in self.error_log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    txt = f"{rec.get('source', '')}: {rec.get('message', '')}"
                    chunks.append({"path": str(self.error_log_path), "text": txt, "ts": float(rec.get("ts", 0.0))})
                except json.JSONDecodeError:
                    continue
        return chunks
