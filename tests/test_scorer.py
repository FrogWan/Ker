import time

from ker.agent.context.scorer import MemoryScorer, STOP_WORDS


class TestTokenize:
    def test_basic_tokenization(self):
        tokens = MemoryScorer.tokenize("hello world test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_stop_words_removed(self):
        tokens = MemoryScorer.tokenize("the quick brown fox is a test")
        for sw in ("the", "is", "a"):
            assert sw not in tokens

    def test_camel_case_split(self):
        tokens = MemoryScorer.tokenize("camelCaseWord")
        assert "camel" in tokens
        assert "case" in tokens or "cas" in tokens  # stemming may apply

    def test_suffix_stemming(self):
        tokens = MemoryScorer.tokenize("debugging running")
        # "debugging" -> stem removes "ing" -> "debugg"
        # "running" -> stem removes "ing" -> "runn"
        assert any("debug" in t for t in tokens)

    def test_empty_input(self):
        assert MemoryScorer.tokenize("") == []

    def test_numbers_preserved(self):
        tokens = MemoryScorer.tokenize("version 15 release")
        assert "15" in tokens


class TestScore:
    def test_empty_chunks(self):
        hits = MemoryScorer.score([], "test query")
        assert hits == []

    def test_empty_query(self):
        chunks = [{"text": "hello world", "ts": time.time(), "path": "test.txt"}]
        hits = MemoryScorer.score(chunks, "")
        assert hits == []

    def test_basic_scoring(self):
        now = time.time()
        chunks = [
            {"text": "python debugging session", "ts": now, "path": "daily/today.jsonl"},
            {"text": "rust memory safety", "ts": now, "path": "daily/today.jsonl"},
            {"text": "python web framework", "ts": now, "path": "daily/today.jsonl"},
        ]
        hits = MemoryScorer.score(chunks, "python", top_k=5)
        assert len(hits) >= 1
        # Python entries should rank higher
        assert "python" in hits[0].snippet.lower()

    def test_recency_decay(self):
        now = time.time()
        chunks = [
            {"text": "python project work", "ts": now - 86400 * 30, "path": "old.jsonl"},  # 30 days old
            {"text": "python project work", "ts": now, "path": "new.jsonl"},  # just now
        ]
        hits = MemoryScorer.score(chunks, "python project", top_k=2)
        assert len(hits) == 2
        # Recent entry should score higher
        assert hits[0].path == "new.jsonl"

    def test_importance_weighting(self):
        now = time.time()
        chunks = [
            {"text": "python task completed", "ts": now, "path": "a.jsonl", "importance": 0.9},
            {"text": "python task completed", "ts": now, "path": "b.jsonl", "importance": 0.3},
        ]
        hits = MemoryScorer.score(chunks, "python task", top_k=2)
        assert len(hits) == 2
        assert hits[0].path == "a.jsonl"

    def test_source_weight(self):
        now = time.time()
        chunks = [
            {"text": "python memory test", "ts": now, "path": "a.jsonl", "source": "working"},
            {"text": "python memory test", "ts": now, "path": "b.jsonl", "source": "chat_history"},
        ]
        hits = MemoryScorer.score(chunks, "python memory", top_k=2)
        assert len(hits) == 2
        # Working memory has higher source weight (1.5 vs 0.8)
        assert hits[0].path == "a.jsonl"

    def test_top_k_limit(self):
        now = time.time()
        chunks = [
            {"text": f"python item {i}", "ts": now, "path": f"{i}.jsonl"}
            for i in range(10)
        ]
        hits = MemoryScorer.score(chunks, "python", top_k=3)
        assert len(hits) == 3

    def test_no_match_returns_empty(self):
        now = time.time()
        chunks = [
            {"text": "rust memory safety", "ts": now, "path": "test.jsonl"},
        ]
        hits = MemoryScorer.score(chunks, "javascript react", top_k=5)
        assert hits == []
