from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import re
import shutil
import time

from ker.agent.context.scorer import MemoryScorer
from ker.agent.context.scorer import MemoryHit as _ScorerHit
from ker.logger import get_logger

log = get_logger("memory")


@dataclass
class MemoryHit:
    path: str
    score: float
    snippet: str


DEFAULT_IMPORTANCE = 0.5

MEMORY_SECTIONS = ["user", "project", "preferences", "patterns", "general"]
DEDUP_THRESHOLD = 0.70

# Importance heuristic keywords
_DECISION_WORDS = {"decided", "chose", "will use", "switching", "agreed", "decision", "choosing"}
_FIX_WORDS = {"fixed", "bug", "error", "resolved", "broke", "crash", "exception", "traceback"}
_PREFERENCE_WORDS = {"prefer", "like", "want", "don't like", "dislike", "favorite"}
_SYSTEM_WORDS = {"heartbeat", "system tick", "cron fired", "health check"}


class MemoryStore:
    def __init__(self, workspace: Path, ker_root: Path) -> None:
        self.workspace = workspace
        self.ker_root = ker_root

    @property
    def error_log_path(self) -> Path:
        return self.ker_root / "memory" / "ERROR_LOG.jsonl"

    @property
    def memory_md_path(self) -> Path:
        return self.ker_root / "MEMORY.md"

    @property
    def episodes_path(self) -> Path:
        return self.ker_root / "memory" / "episodes.jsonl"

    # ── Long-term memory ───────────────────────────────────────────

    def read_long_term(self) -> str:
        """Return full text of MEMORY.md, or empty string if missing."""
        if self.memory_md_path.exists():
            return self.memory_md_path.read_text(encoding="utf-8")
        return ""

    def write_fact(self, fact: str, category: str = "general", action: str = "add") -> str:
        """Add or remove a fact in MEMORY.md under the given category section."""
        fact = fact.strip()
        if not fact:
            return "Error: empty fact"
        category = category.lower()
        if category not in MEMORY_SECTIONS:
            category = "general"

        # Read or create MEMORY.md
        if self.memory_md_path.exists():
            text = self.memory_md_path.read_text(encoding="utf-8")
        else:
            text = "# Memory\n"

        sections = self._parse_memory_sections(text)

        if action == "remove":
            return self._remove_fact(sections, fact, category)

        # action == "add"
        return self._add_fact(sections, fact, category)

    def _parse_memory_sections(self, text: str) -> dict[str, list[str]]:
        """Parse MEMORY.md into {section_name: [bullet_lines]}."""
        sections: dict[str, list[str]] = {s: [] for s in MEMORY_SECTIONS}
        current: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                header = stripped[3:].strip().lower()
                current = header if header in MEMORY_SECTIONS else None
            elif current and stripped.startswith("- "):
                sections[current].append(stripped[2:].strip())
        return sections

    def _write_memory_sections(self, sections: dict[str, list[str]]) -> None:
        """Write sections back to MEMORY.md."""
        lines = ["# Memory\n"]
        for section in MEMORY_SECTIONS:
            bullets = sections.get(section, [])
            if not bullets:
                continue
            lines.append(f"## {section.capitalize()}\n")
            for b in bullets:
                lines.append(f"- {b}")
            lines.append("")
        self.memory_md_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_md_path.write_text("\n".join(lines), encoding="utf-8")

    def _token_overlap(self, a: str, b: str) -> float:
        """Return overlap coefficient: |intersection| / |smaller set|."""
        ta = set(self._tokenize(a))
        tb = set(self._tokenize(b))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / min(len(ta), len(tb))

    def _add_fact(self, sections: dict[str, list[str]], fact: str, category: str) -> str:
        bullets = sections[category]
        best_idx, best_score = -1, 0.0
        for i, existing in enumerate(bullets):
            score = self._token_overlap(fact, existing)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score >= DEDUP_THRESHOLD:
            if len(fact) > len(bullets[best_idx]):
                old = bullets[best_idx]
                bullets[best_idx] = fact
                self._write_memory_sections(sections)
                return f"Updated existing fact in {category}: '{old}' → '{fact}'"
            return f"Already remembered (similar entry exists in {category})"

        bullets.append(fact)
        self._write_memory_sections(sections)
        return f"Saved to {category}: {fact}"

    def _remove_fact(self, sections: dict[str, list[str]], fact: str, category: str) -> str:
        bullets = sections[category]
        if not bullets:
            return f"No facts found in {category} to remove"

        best_idx, best_score = -1, 0.0
        for i, existing in enumerate(bullets):
            score = self._token_overlap(fact, existing)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score < 0.3:
            return f"No matching fact found in {category}"

        removed = bullets.pop(best_idx)
        self._write_memory_sections(sections)
        return f"Removed from {category}: {removed}"

    # ── Importance scoring (Phase 3) ─────────────────────────────

    @staticmethod
    def _estimate_importance(text: str) -> float:
        """Heuristic importance score for a daily entry."""
        lower = text.lower()
        score = 0.5

        if any(w in lower for w in _DECISION_WORDS):
            score += 0.2
        if any(w in lower for w in _FIX_WORDS):
            score += 0.15
        if any(w in lower for w in _PREFERENCE_WORDS):
            score += 0.1
        if len(text) > 200:
            score += 0.05
        if any(w in lower for w in _SYSTEM_WORDS):
            score -= 0.2

        return max(0.0, min(1.0, score))

    # ── Short-term memory ──────────────────────────────────────────

    def search_short_term(
        self, query: str, agent_name: str = "", top_k: int = 5, source: str = "all"
    ) -> list[MemoryHit]:
        """Search ephemeral sources (daily, episodes, chat history, HISTORY.md).

        Does NOT search MEMORY.md (already in system prompt) or ERROR_LOG.jsonl.
        """
        chunks = self._load_short_term_chunks(agent_name, source)
        if not chunks:
            return []
        hits = MemoryScorer.score(chunks, query, top_k)
        return [MemoryHit(path=h.path, score=h.score, snippet=h.snippet) for h in hits]

    def _load_short_term_chunks(self, agent_name: str, source: str = "all") -> list[dict]:
        """Load chunks from ephemeral sources, respecting source filter."""
        chunks: list[dict] = []

        # Daily files
        if source in ("all", "daily"):
            daily_dir = self.ker_root / "memory" / "daily"
            if daily_dir.exists():
                for p in daily_dir.glob("*.jsonl"):
                    for line in p.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                            chunks.append({
                                "path": str(p),
                                "text": rec.get("text", ""),
                                "ts": float(rec.get("ts", 0.0)),
                                "importance": float(rec.get("importance", DEFAULT_IMPORTANCE)),
                                "source": "daily",
                            })
                        except json.JSONDecodeError:
                            continue

        # Episodes
        if source in ("all", "episodes"):
            for ep in self._load_episodes():
                chunks.append({
                    "path": "episodes.jsonl",
                    "text": ep.get("summary", ""),
                    "ts": float(ep.get("ts", 0.0)),
                    "importance": float(ep.get("importance", DEFAULT_IMPORTANCE)),
                    "source": "episodes",
                })

        # Chat history
        if source in ("all", "chat_history") and agent_name:
            chat_path = self.ker_root / "agents" / agent_name / "chatHistory" / "chatHistory.jsonl"
            if chat_path.exists():
                for line in chat_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        chunks.append({
                            "path": str(chat_path),
                            "text": rec.get("content", ""),
                            "ts": float(rec.get("ts", 0.0)),
                            "importance": DEFAULT_IMPORTANCE,
                            "source": "chat_history",
                        })
                    except json.JSONDecodeError:
                        continue

        # HISTORY.md (consolidated — legacy)
        if source in ("all", "session"):
            if self.history_path.exists():
                text = self.history_path.read_text(encoding="utf-8")
                for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
                    chunks.append({
                        "path": "HISTORY.md",
                        "text": para,
                        "ts": self.history_path.stat().st_mtime,
                        "importance": DEFAULT_IMPORTANCE,
                        "source": "HISTORY.md",
                    })

        return chunks

    def add_daily(self, text: str, importance: float | None = None) -> None:
        daily_dir = self.ker_root / "memory" / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now().strftime("%Y-%m-%d")
        p = daily_dir / f"{day}.jsonl"
        now = time.time()

        if importance is None:
            importance = self._estimate_importance(text)

        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": now,
                "time": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "text": text,
                "importance": round(importance, 3),
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

    def search_memory(self, query: str, top_k: int = 5) -> list[MemoryHit]:
        """Search all memory tiers (MEMORY.md, HISTORY.md, daily, episodes, errors)."""
        chunks = self._load_chunks()
        if not chunks:
            return []
        hits = MemoryScorer.score(chunks, query, top_k)
        return [MemoryHit(path=h.path, score=h.score, snippet=h.snippet) for h in hits]

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
                chunks.append({
                    "path": str(chat_path),
                    "text": rec.get("content", ""),
                    "ts": float(rec.get("ts", 0.0)),
                    "importance": DEFAULT_IMPORTANCE,
                    "source": "chat_history",
                })
            except json.JSONDecodeError:
                continue
        if not chunks:
            return []
        hits = MemoryScorer.score(chunks, query, top_k)
        return [MemoryHit(path=h.path, score=h.score, snippet=h.snippet) for h in hits]

    def _tokenize(self, text: str) -> list[str]:
        """Backward-compatible tokenize — delegates to MemoryScorer."""
        return MemoryScorer.tokenize(text)

    def _score_chunks(self, chunks: list[dict], query: str, top_k: int) -> list[MemoryHit]:
        """Backward-compatible scorer — delegates to MemoryScorer."""
        hits = MemoryScorer.score(chunks, query, top_k)
        return [MemoryHit(path=h.path, score=h.score, snippet=h.snippet) for h in hits]

    @property
    def history_path(self) -> Path:
        return self.ker_root / "HISTORY.md"

    # ── Episodic memory (Phase 4) ────────────────────────────────

    def _load_episodes(self) -> list[dict]:
        """Load episode records from episodes.jsonl."""
        if not self.episodes_path.exists():
            return []
        episodes: list[dict] = []
        for line in self.episodes_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                episodes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return episodes

    def _extract_tags(self, entries: list[str], top_n: int = 5) -> list[str]:
        """Extract top-N TF-IDF tags from a list of text entries."""
        all_tokens: list[str] = []
        entry_token_sets: list[set[str]] = []
        for e in entries:
            toks = MemoryScorer.tokenize(e)
            all_tokens.extend(toks)
            entry_token_sets.append(set(toks))

        if not all_tokens:
            return []

        n = len(entry_token_sets)
        # Term frequency across all entries
        tf: dict[str, int] = {}
        for t in all_tokens:
            tf[t] = tf.get(t, 0) + 1
        # Document frequency
        df: dict[str, int] = {}
        for s in entry_token_sets:
            for t in s:
                df[t] = df.get(t, 0) + 1
        # TF-IDF score per term
        scores: dict[str, float] = {}
        for t, c in tf.items():
            scores[t] = c * (math.log((n + 1) / (df.get(t, 0) + 1)) + 1)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [t for t, _ in ranked[:top_n]]

    async def auto_consolidate(self, summarize_fn=None) -> bool:
        """Consolidate daily files older than 1 day into episodes.jsonl.

        Args:
            summarize_fn: Optional async callable(text) -> str for LLM summarization.

        Returns:
            True if any consolidation was performed.
        """
        daily_dir = self.ker_root / "memory" / "daily"
        if not daily_dir.exists():
            return False

        today = datetime.now().strftime("%Y-%m-%d")
        files = sorted(daily_dir.glob("*.jsonl"))
        # Only consolidate files older than today
        to_consolidate = [f for f in files if f.stem < today]

        if not to_consolidate:
            return False

        # Migrate HISTORY.md -> episodes.jsonl on first run
        self._migrate_history_to_episodes()

        archive_dir = self.ker_root / "memory" / "archive" / "daily"
        archive_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_path.parent.mkdir(parents=True, exist_ok=True)

        consolidated_count = 0
        for f in to_consolidate:
            entries: list[str] = []
            importances: list[float] = []
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    entries.append(rec.get("text", ""))
                    importances.append(float(rec.get("importance", DEFAULT_IMPORTANCE)))
                except json.JSONDecodeError:
                    continue

            if not entries:
                # Empty file — just archive it
                shutil.move(str(f), str(archive_dir / f.name))
                continue

            # Compute weighted summary
            combined = "\n".join(entries)
            if summarize_fn:
                try:
                    summary = await summarize_fn(
                        f"Summarize these daily memory entries from {f.stem} into 1-3 sentences:\n\n{combined}"
                    )
                except Exception:
                    summary = combined[:500]
            else:
                # Without LLM: pick most important entries
                indexed = sorted(
                    enumerate(entries), key=lambda x: importances[x[0]], reverse=True
                )
                top_entries = [entries[i] for i, _ in indexed[:3]]
                summary = " | ".join(top_entries)[:500]

            tags = self._extract_tags(entries)
            avg_importance = sum(importances) / len(importances) if importances else DEFAULT_IMPORTANCE

            # Determine outcome (last entry often contains the result)
            outcome = entries[-1][:200] if entries else ""

            episode = {
                "id": f"ep_{f.stem}_{consolidated_count:03d}",
                "date": f.stem,
                "summary": summary,
                "tags": tags,
                "outcome": outcome,
                "importance": round(avg_importance, 3),
                "entry_count": len(entries),
                "ts": f.stat().st_mtime,
            }

            with self.episodes_path.open("a", encoding="utf-8") as ep_f:
                ep_f.write(json.dumps(episode, ensure_ascii=False) + "\n")

            # Archive daily file
            shutil.move(str(f), str(archive_dir / f.name))
            consolidated_count += 1

        if consolidated_count > 0:
            # Log consolidation
            log_path = self.ker_root / "memory" / "consolidation_log.jsonl"
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write(json.dumps({
                    "ts": time.time(),
                    "files_consolidated": consolidated_count,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, ensure_ascii=False) + "\n")
            log.info("Auto-consolidated %d daily files into episodes", consolidated_count)

        # Also run rotation
        self.rotate_error_log()

        return consolidated_count > 0

    def _migrate_history_to_episodes(self) -> None:
        """One-time migration: parse HISTORY.md paragraphs into episodes."""
        if not self.history_path.exists() or self.episodes_path.exists():
            return

        text = self.history_path.read_text(encoding="utf-8")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return

        mtime = self.history_path.stat().st_mtime
        self.episodes_path.parent.mkdir(parents=True, exist_ok=True)

        with self.episodes_path.open("a", encoding="utf-8") as f:
            for i, para in enumerate(paragraphs):
                if para.startswith("#"):
                    continue  # Skip headers
                episode = {
                    "id": f"ep_migrated_{i:03d}",
                    "date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"),
                    "summary": para[:500],
                    "tags": self._extract_tags([para]),
                    "outcome": "",
                    "importance": DEFAULT_IMPORTANCE,
                    "entry_count": 1,
                    "ts": mtime,
                }
                f.write(json.dumps(episode, ensure_ascii=False) + "\n")

        log.info("Migrated HISTORY.md into %d episodes", len(paragraphs))

    async def consolidate(self, summarize_fn=None) -> bool:
        """Legacy consolidate — delegates to auto_consolidate with deprecation warning."""
        log.warning("consolidate() is deprecated, use auto_consolidate() instead")
        return await self.auto_consolidate(summarize_fn)

    # ── Rotation (Phase 5) ───────────────────────────────────────

    def rotate_error_log(self, max_entries: int = 1000) -> bool:
        """Archive oldest 80% of error log entries when exceeding max_entries."""
        if not self.error_log_path.exists():
            return False

        lines = self.error_log_path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_entries:
            return False

        keep_count = max(1, len(lines) // 5)  # Keep newest 20%
        to_archive = lines[:-keep_count]
        to_keep = lines[-keep_count:]

        # Archive old entries
        archive_dir = self.ker_root / "memory" / "archive" / "errors"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"errors_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.jsonl"
        (archive_dir / archive_name).write_text("\n".join(to_archive) + "\n", encoding="utf-8")

        # Rewrite active file
        self.error_log_path.write_text("\n".join(to_keep) + "\n", encoding="utf-8")
        log.info("Rotated error log: archived %d entries, kept %d", len(to_archive), len(to_keep))
        return True

    # ── Memory stats ─────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return counts/sizes of all memory stores."""
        stats: dict = {}

        # MEMORY.md facts
        if self.memory_md_path.exists():
            text = self.memory_md_path.read_text(encoding="utf-8")
            sections = self._parse_memory_sections(text)
            fact_count = sum(len(v) for v in sections.values())
            stats["long_term_facts"] = fact_count
            stats["long_term_size"] = len(text)
        else:
            stats["long_term_facts"] = 0
            stats["long_term_size"] = 0

        # Daily files
        daily_dir = self.ker_root / "memory" / "daily"
        if daily_dir.exists():
            daily_files = list(daily_dir.glob("*.jsonl"))
            daily_entries = 0
            for f in daily_files:
                daily_entries += sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
            stats["daily_files"] = len(daily_files)
            stats["daily_entries"] = daily_entries
        else:
            stats["daily_files"] = 0
            stats["daily_entries"] = 0

        # Episodes
        episodes = self._load_episodes()
        stats["episode_count"] = len(episodes)

        # Error log
        if self.error_log_path.exists():
            error_lines = sum(1 for line in self.error_log_path.read_text(encoding="utf-8").splitlines() if line.strip())
            stats["error_entries"] = error_lines
        else:
            stats["error_entries"] = 0

        return stats

    # ── Internal loading ─────────────────────────────────────────

    def _load_chunks(self) -> list[dict]:
        chunks: list[dict] = []
        memory_md = self.ker_root / "MEMORY.md"
        if memory_md.exists():
            text = memory_md.read_text(encoding="utf-8")
            for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
                chunks.append({
                    "path": "MEMORY.md",
                    "text": para,
                    "ts": memory_md.stat().st_mtime,
                    "importance": DEFAULT_IMPORTANCE,
                    "source": "MEMORY.md",
                })

        # Include HISTORY.md in search
        if self.history_path.exists():
            text = self.history_path.read_text(encoding="utf-8")
            for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
                chunks.append({
                    "path": "HISTORY.md",
                    "text": para,
                    "ts": self.history_path.stat().st_mtime,
                    "importance": DEFAULT_IMPORTANCE,
                    "source": "HISTORY.md",
                })

        # Episodes
        for ep in self._load_episodes():
            chunks.append({
                "path": "episodes.jsonl",
                "text": ep.get("summary", ""),
                "ts": float(ep.get("ts", 0.0)),
                "importance": float(ep.get("importance", DEFAULT_IMPORTANCE)),
                "source": "episodes",
            })

        daily_dir = self.ker_root / "memory" / "daily"
        if daily_dir.exists():
            for p in daily_dir.glob("*.jsonl"):
                for line in p.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        chunks.append({
                            "path": str(p),
                            "text": rec.get("text", ""),
                            "ts": float(rec.get("ts", 0.0)),
                            "importance": float(rec.get("importance", DEFAULT_IMPORTANCE)),
                            "source": "daily",
                        })
                    except json.JSONDecodeError:
                        continue

        if self.error_log_path.exists():
            for line in self.error_log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    txt = f"{rec.get('source', '')}: {rec.get('message', '')}"
                    chunks.append({
                        "path": str(self.error_log_path),
                        "text": txt,
                        "ts": float(rec.get("ts", 0.0)),
                        "importance": DEFAULT_IMPORTANCE,
                        "source": "ERROR_LOG",
                    })
                except json.JSONDecodeError:
                    continue

        return chunks
