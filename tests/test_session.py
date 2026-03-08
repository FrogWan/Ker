from pathlib import Path
import pytest
from ker.agent.context.session import SessionStore, sanitize_session_name


def test_session_roundtrip(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.append_user("ker", "test_session", "hello")
    store.append_assistant("ker", "test_session", [{"type": "text", "text": "hi there"}])

    messages = store.load_messages("ker", "test_session")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][0]["text"] == "hi there"


def test_session_path(tmp_path: Path):
    store = SessionStore(tmp_path)
    path = store._session_path("ker", "cli_user_default")
    assert "agents" in str(path)
    assert "ker" in str(path)
    assert path.suffix == ".jsonl"


def test_replace_messages(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.append_user("ker", "test", "msg1")
    store.append_user("ker", "test", "msg2")
    store.append_assistant("ker", "test", [{"type": "text", "text": "reply"}])

    messages = store.load_messages("ker", "test")
    assert len(messages) == 3

    compacted = [
        {"role": "user", "content": "summary"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    ]
    store.replace_messages("ker", "test", compacted)
    reloaded = store.load_messages("ker", "test")
    assert len(reloaded) == 2


class TestSanitizeSessionName:
    def test_valid_passthrough(self):
        assert sanitize_session_name("my-session") == "my-session"
        assert sanitize_session_name("session_1") == "session_1"
        assert sanitize_session_name("ABC123") == "ABC123"

    def test_whitespace_stripped(self):
        assert sanitize_session_name("  hello  ") == "hello"
        assert sanitize_session_name("\ttabs\t") == "tabs"

    def test_empty_and_dots_default(self):
        assert sanitize_session_name("") == "default"
        assert sanitize_session_name("   ") == "default"
        assert sanitize_session_name(".") == "default"
        assert sanitize_session_name("..") == "default"
        assert sanitize_session_name(None) == "default"

    def test_forbidden_chars_replaced(self):
        assert sanitize_session_name("a/b\\c:d") == "a-b-c-d"
        assert sanitize_session_name('a*b?c"d') == "a-b-c-d"
        assert sanitize_session_name("a<b>c|d") == "a-b-c-d"
        assert sanitize_session_name("hello world") == "hello-world"

    def test_consecutive_hyphens_collapsed(self):
        assert sanitize_session_name("a///b") == "a-b"
        assert sanitize_session_name("a---b") == "a-b"

    def test_leading_trailing_hyphens_stripped(self):
        assert sanitize_session_name("-hello-") == "hello"
        assert sanitize_session_name("---test---") == "test"
        assert sanitize_session_name("/hello/") == "hello"

    def test_max_length_enforced(self):
        long_name = "a" * 100
        result = sanitize_session_name(long_name)
        assert len(result) <= 64

    def test_underscores_preserved(self):
        assert sanitize_session_name("my_session_name") == "my_session_name"

    def test_all_forbidden_becomes_default(self):
        assert sanitize_session_name("///") == "default"
        assert sanitize_session_name("***") == "default"
