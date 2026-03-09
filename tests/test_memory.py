import json
from pathlib import Path

from ker.agent.context.memory import MemoryStore


def test_memory_search_empty(tmp_path: Path):
    store = MemoryStore(tmp_path, tmp_path / ".ker")
    hits = store.search_memory("test query")
    assert hits == []


def test_memory_add_daily(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)
    store.add_daily("test memory entry")
    daily_dir = ker_root / "memory" / "daily"
    assert daily_dir.exists()
    files = list(daily_dir.glob("*.jsonl"))
    assert len(files) == 1


def test_memory_add_error(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)
    store.add_error("test_source", "test error message")
    assert store.error_log_path.exists()


def test_memory_search_with_data(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)
    store.add_daily("python debugging tips")
    store.add_daily("rust memory safety patterns")
    hits = store.search_memory("python")
    assert len(hits) >= 1
    assert any("python" in h.snippet.lower() for h in hits)


# ── write_fact tests ───────────────────────────────────────────────


def test_write_fact_add(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    result = store.write_fact("Main database is PostgreSQL 15", category="project")
    assert "Saved to project" in result
    assert store.memory_md_path.exists()
    content = store.memory_md_path.read_text(encoding="utf-8")
    assert "Main database is PostgreSQL 15" in content
    assert "## Project" in content


def test_write_fact_dedup(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    store.write_fact("User prefers dark mode", category="preferences")
    result = store.write_fact("User prefers dark mode", category="preferences")
    assert "Already remembered" in result
    # Verify not duplicated
    content = store.memory_md_path.read_text(encoding="utf-8")
    assert content.count("User prefers dark mode") == 1


def test_write_fact_update(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    store.write_fact("Uses PostgreSQL", category="project")
    result = store.write_fact("Uses PostgreSQL 15 on AWS RDS with read replicas", category="project")
    assert "Updated existing fact" in result
    content = store.memory_md_path.read_text(encoding="utf-8")
    assert "PostgreSQL 15 on AWS RDS" in content
    assert content.count("PostgreSQL") == 1


def test_write_fact_remove(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    store.write_fact("User prefers dark mode", category="preferences")
    result = store.write_fact("dark mode", category="preferences", action="remove")
    assert "Removed from preferences" in result
    content = store.memory_md_path.read_text(encoding="utf-8")
    assert "dark mode" not in content


def test_write_fact_remove_no_match(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    store.write_fact("User prefers dark mode", category="preferences")
    result = store.write_fact("completely unrelated fact xyz", category="preferences", action="remove")
    assert "No matching fact" in result


def test_write_fact_categories(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    store.write_fact("Name: Alex", category="user")
    store.write_fact("Main DB is Postgres", category="project")
    store.write_fact("Use ruff for linting", category="preferences")
    store.write_fact("Build failures usually mean dep updates", category="patterns")
    store.write_fact("Some general note", category="general")

    content = store.memory_md_path.read_text(encoding="utf-8")
    assert "## User" in content
    assert "## Project" in content
    assert "## Preferences" in content
    assert "## Patterns" in content
    assert "## General" in content


def test_write_fact_invalid_category_defaults_to_general(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    result = store.write_fact("Some fact", category="nonexistent")
    assert "Saved to general" in result


def test_write_fact_empty_returns_error(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)
    result = store.write_fact("", category="general")
    assert "Error" in result


def test_read_long_term(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    store = MemoryStore(tmp_path, ker_root)

    # No file yet
    assert store.read_long_term() == ""

    # Write a fact, then read
    store.write_fact("Test fact", category="general")
    text = store.read_long_term()
    assert "Test fact" in text


# ── search_short_term tests ───────────────────────────────────────


def test_search_short_term(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)

    # Add daily entries
    store.add_daily("python debugging session today")
    store.add_daily("reviewed rust code patterns")

    # Also write a long-term fact (should NOT appear in short-term search)
    ker_root.mkdir(parents=True, exist_ok=True)
    store.write_fact("Main language is Python", category="project")

    hits = store.search_short_term("python", agent_name="test_agent")
    assert len(hits) >= 1
    # Should find daily entry
    assert any("python" in h.snippet.lower() for h in hits)
    # Should NOT include MEMORY.md content
    assert not any("MEMORY.md" in h.path for h in hits)


def test_search_short_term_source_filter_daily(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)

    store.add_daily("python daily note")

    # Write chat history
    agent_name = "test_agent"
    chat_dir = ker_root / "agents" / agent_name / "chatHistory"
    chat_dir.mkdir(parents=True, exist_ok=True)
    chat_path = chat_dir / "chatHistory.jsonl"
    import time
    chat_path.write_text(
        json.dumps({"content": "python chat message", "ts": time.time()}) + "\n",
        encoding="utf-8",
    )

    # Filter to daily only
    hits = store.search_short_term("python", agent_name=agent_name, source="daily")
    for h in hits:
        assert "chatHistory" not in h.path


def test_search_short_term_source_filter_chat(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)

    store.add_daily("python daily note")

    agent_name = "test_agent"
    chat_dir = ker_root / "agents" / agent_name / "chatHistory"
    chat_dir.mkdir(parents=True, exist_ok=True)
    chat_path = chat_dir / "chatHistory.jsonl"
    import time
    chat_path.write_text(
        json.dumps({"content": "python chat message", "ts": time.time()}) + "\n",
        encoding="utf-8",
    )

    # Filter to chat_history only
    hits = store.search_short_term("python", agent_name=agent_name, source="chat_history")
    assert len(hits) >= 1
    for h in hits:
        assert "daily" not in h.path


def test_search_short_term_excludes_error_log(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)

    store.add_error("test_source", "python error in module")
    store.add_daily("unrelated daily note")

    hits = store.search_short_term("python error", agent_name="test_agent")
    # Error log entries should not appear
    for h in hits:
        assert "ERROR_LOG" not in h.path
