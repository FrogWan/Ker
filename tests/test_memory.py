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
    rows = store.read_error_log()
    assert len(rows) == 1
    assert rows[0]["source"] == "test_source"


def test_memory_search_with_data(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    store = MemoryStore(tmp_path, ker_root)
    store.add_daily("python debugging tips")
    store.add_daily("rust memory safety patterns")
    hits = store.search_memory("python")
    assert len(hits) >= 1
    assert any("python" in h.snippet.lower() for h in hits)
