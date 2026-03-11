import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ker.agent.context.chat_history import ChatHistory
from ker.agent.context.memory import MemoryStore


@pytest.fixture
def store(tmp_path: Path):
    return MemoryStore(tmp_path, tmp_path / ".ker")


@pytest.fixture
def chat_hist(tmp_path: Path):
    return ChatHistory(tmp_path / ".ker")


# ── Importance scoring ───────────────────────────────────────────


class TestImportance:
    def test_default_importance(self, store):
        assert store._estimate_importance("a regular message") == pytest.approx(0.5, abs=0.01)

    def test_decision_words_boost(self, store):
        score = store._estimate_importance("decided to use PostgreSQL for the backend")
        assert score > 0.5

    def test_fix_words_boost(self, store):
        score = store._estimate_importance("fixed the null pointer bug in auth module")
        assert score > 0.5

    def test_preference_words_boost(self, store):
        score = store._estimate_importance("I prefer dark mode for the editor")
        assert score > 0.5

    def test_system_words_penalty(self, store):
        score = store._estimate_importance("heartbeat system tick")
        assert score < 0.5

    def test_clamped_to_range(self, store):
        # Even with many boosts, should not exceed 1.0
        score = store._estimate_importance("decided and fixed error, prefer this approach, agreed on the resolution")
        assert 0.0 <= score <= 1.0


class TestAddDailyImportance:
    def test_daily_includes_importance(self, store: MemoryStore):
        store.add_daily("decided to switch to PostgreSQL")
        daily_dir = store.ker_root / "memory" / "daily"
        files = list(daily_dir.glob("*.jsonl"))
        assert len(files) == 1
        line = files[0].read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert "importance" in rec
        assert rec["importance"] > 0.5  # Decision word should boost

    def test_daily_explicit_importance(self, store: MemoryStore):
        store.add_daily("test entry", importance=0.9)
        daily_dir = store.ker_root / "memory" / "daily"
        files = list(daily_dir.glob("*.jsonl"))
        line = files[0].read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["importance"] == pytest.approx(0.9, abs=0.001)


# ── Episodes ─────────────────────────────────────────────────────


class TestEpisodes:
    def test_load_episodes_empty(self, store):
        assert store._load_episodes() == []

    def test_load_episodes(self, store: MemoryStore):
        store.episodes_path.parent.mkdir(parents=True, exist_ok=True)
        ep = {
            "id": "ep_test_001",
            "date": "2026-03-10",
            "summary": "Test episode summary",
            "tags": ["test", "debug"],
            "outcome": "All tests pass",
            "importance": 0.8,
            "entry_count": 5,
            "ts": time.time(),
        }
        store.episodes_path.write_text(json.dumps(ep) + "\n", encoding="utf-8")
        episodes = store._load_episodes()
        assert len(episodes) == 1
        assert episodes[0]["summary"] == "Test episode summary"

    def test_extract_tags(self, store: MemoryStore):
        entries = [
            "Debugging the websocket connection issue",
            "WebSocket reconnection backoff fixed",
            "Added exponential backoff to websocket",
        ]
        tags = store._extract_tags(entries, top_n=3)
        assert len(tags) <= 3
        assert any("websock" in t for t in tags)


# ── Auto-consolidation ──────────────────────────────────────────


class TestAutoConsolidate:
    def _create_old_daily(self, store: MemoryStore, date_str: str, entries: list[str]):
        """Helper: create a daily file with a specific date."""
        daily_dir = store.ker_root / "memory" / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        p = daily_dir / f"{date_str}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for text in entries:
                f.write(json.dumps({
                    "ts": time.time() - 86400,
                    "text": text,
                    "importance": 0.6,
                }) + "\n")

    def test_no_files(self, store):
        result = asyncio.run(store.auto_consolidate())
        assert result is False

    def test_only_today_not_consolidated(self, store: MemoryStore):
        store.add_daily("today's entry")
        result = asyncio.run(store.auto_consolidate())
        assert result is False

    def test_old_file_consolidated(self, store: MemoryStore):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._create_old_daily(store, yesterday, ["Fixed auth bug", "Deployed new version"])
        store.add_daily("today's entry")

        result = asyncio.run(store.auto_consolidate())
        assert result is True

        # Episodes should be created
        assert store.episodes_path.exists()
        episodes = store._load_episodes()
        assert len(episodes) == 1
        assert episodes[0]["date"] == yesterday

        # Daily file should be archived
        daily_dir = store.ker_root / "memory" / "daily"
        remaining = [f.stem for f in daily_dir.glob("*.jsonl")]
        assert yesterday not in remaining

        # Archive should exist
        archive_dir = store.ker_root / "memory" / "archive" / "daily"
        archived = list(archive_dir.glob("*.jsonl"))
        assert len(archived) == 1

    def test_consolidation_log(self, store: MemoryStore):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self._create_old_daily(store, yesterday, ["test entry"])
        store.add_daily("today")

        asyncio.run(store.auto_consolidate())

        log_path = store.ker_root / "memory" / "consolidation_log.jsonl"
        assert log_path.exists()
        rec = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert rec["files_consolidated"] == 1


# ── History migration ────────────────────────────────────────────


class TestHistoryMigration:
    def test_migrate_history_to_episodes(self, store: MemoryStore):
        # Create a HISTORY.md file
        store.history_path.parent.mkdir(parents=True, exist_ok=True)
        store.history_path.write_text(
            "# History\n\nConsolidated memory.\n\n"
            "Fixed a major auth bug affecting all users.\n\n"
            "Deployed v2.0 of the API gateway.\n",
            encoding="utf-8",
        )

        store._migrate_history_to_episodes()

        assert store.episodes_path.exists()
        episodes = store._load_episodes()
        # Should have migrated non-header paragraphs
        assert len(episodes) >= 1

    def test_no_migration_if_episodes_exist(self, store: MemoryStore):
        store.history_path.parent.mkdir(parents=True, exist_ok=True)
        store.history_path.write_text("# History\n\nSome content.\n", encoding="utf-8")
        store.episodes_path.parent.mkdir(parents=True, exist_ok=True)
        store.episodes_path.write_text("{}\n", encoding="utf-8")

        store._migrate_history_to_episodes()
        # Should not double-migrate — episodes file should still just have the one line
        content = store.episodes_path.read_text(encoding="utf-8")
        assert content.count("\n") == 1


# ── Error log rotation ──────────────────────────────────────────


class TestErrorLogRotation:
    def test_no_rotation_under_limit(self, store: MemoryStore):
        store.error_log_path.parent.mkdir(parents=True, exist_ok=True)
        for i in range(10):
            store.add_error("test", f"error {i}")
        assert store.rotate_error_log(max_entries=1000) is False

    def test_rotation_over_limit(self, store: MemoryStore):
        store.error_log_path.parent.mkdir(parents=True, exist_ok=True)
        for i in range(50):
            store.add_error("test", f"error {i}")

        result = store.rotate_error_log(max_entries=20)
        assert result is True

        # Active file should have ~20% of entries
        remaining = store.error_log_path.read_text(encoding="utf-8").splitlines()
        remaining = [l for l in remaining if l.strip()]
        assert len(remaining) == 10  # 50 // 5 = 10

        # Archive should exist
        archive_dir = store.ker_root / "memory" / "archive" / "errors"
        archived = list(archive_dir.glob("*.jsonl"))
        assert len(archived) == 1


# ── Chat history rotation ───────────────────────────────────────


class TestChatHistoryRotation:
    def test_no_rotation_under_limit(self, chat_hist: ChatHistory):
        for i in range(10):
            chat_hist.append("test_agent", "user", f"message {i}")
        assert chat_hist.rotate("test_agent", max_entries=500) is False

    def test_rotation_over_limit(self, chat_hist: ChatHistory):
        for i in range(50):
            chat_hist.append("test_agent", "user", f"message {i}")

        result = chat_hist.rotate("test_agent", max_entries=20)
        assert result is True

        # Active file should have ~20% of entries
        path = chat_hist._history_path("test_agent")
        remaining = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(remaining) == 10  # 50 // 5 = 10

        # Archive should exist
        archive_dir = chat_hist.ker_root / "memory" / "archive" / "chat" / "test_agent"
        archived = list(archive_dir.glob("*.jsonl"))
        assert len(archived) == 1


# ── Short-term search with episodes ─────────────────────────────


class TestShortTermWithEpisodes:
    def test_episodes_included_in_search(self, store: MemoryStore):
        store.episodes_path.parent.mkdir(parents=True, exist_ok=True)
        ep = {
            "id": "ep_test",
            "date": "2026-03-10",
            "summary": "Fixed WebSocket reconnection issue with exponential backoff",
            "tags": ["websocket", "debugging"],
            "outcome": "Working correctly now",
            "importance": 0.8,
            "entry_count": 5,
            "ts": time.time(),
        }
        store.episodes_path.write_text(json.dumps(ep) + "\n", encoding="utf-8")

        hits = store.search_short_term("WebSocket", source="episodes")
        assert len(hits) >= 1
        assert "WebSocket" in hits[0].snippet


# ── Memory stats ─────────────────────────────────────────────────


class TestMemoryStats:
    def test_empty_stats(self, store: MemoryStore):
        stats = store.get_stats()
        assert stats["long_term_facts"] == 0
        assert stats["daily_files"] == 0
        assert stats["daily_entries"] == 0
        assert stats["episode_count"] == 0
        assert stats["error_entries"] == 0

    def test_stats_with_data(self, store: MemoryStore):
        store.ker_root.mkdir(parents=True, exist_ok=True)
        store.write_fact("Test fact", category="general")
        store.add_daily("Daily entry")
        store.add_error("test", "An error")

        stats = store.get_stats()
        assert stats["long_term_facts"] == 1
        assert stats["daily_entries"] == 1
        assert stats["error_entries"] == 1
