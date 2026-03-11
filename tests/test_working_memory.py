import json
from pathlib import Path

from ker.agent.context.working_memory import (
    WorkingContext,
    WorkingMemoryManager,
    WORKING_CONTEXT_MAX_CHARS,
)


def test_working_context_round_trip():
    ctx = WorkingContext(
        task="Fix bug in memory.py",
        decisions=["Use TF-IDF scorer"],
        pending=["Write tests"],
        last_tools=["read_file path=memory.py"],
    )
    d = ctx.to_dict()
    restored = WorkingContext.from_dict(d)
    assert restored.task == ctx.task
    assert restored.decisions == ctx.decisions
    assert restored.pending == ctx.pending
    assert restored.last_tools == ctx.last_tools


def test_load_empty(tmp_path: Path):
    mgr = WorkingMemoryManager(tmp_path / ".ker")
    ctx = mgr.load("test_agent")
    assert ctx.task == ""
    assert ctx.decisions == []
    assert ctx.pending == []
    assert ctx.last_tools == []


def test_save_and_load(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    mgr = WorkingMemoryManager(ker_root)

    ctx = WorkingContext(task="Implement feature X", decisions=["Use async"])
    mgr.save("test_agent", ctx)

    loaded = mgr.load("test_agent")
    assert loaded.task == "Implement feature X"
    assert loaded.decisions == ["Use async"]
    assert loaded.updated_at > 0


def test_clear(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    mgr = WorkingMemoryManager(ker_root)

    ctx = WorkingContext(task="Some task")
    mgr.save("test_agent", ctx)
    assert mgr._context_path("test_agent").exists()

    mgr.clear("test_agent")
    assert not mgr._context_path("test_agent").exists()


def test_clear_nonexistent(tmp_path: Path):
    mgr = WorkingMemoryManager(tmp_path / ".ker")
    # Should not raise
    mgr.clear("nonexistent_agent")


def test_render_for_prompt_empty(tmp_path: Path):
    mgr = WorkingMemoryManager(tmp_path / ".ker")
    result = mgr.render_for_prompt("test_agent")
    assert result == ""


def test_render_for_prompt_with_data(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    mgr = WorkingMemoryManager(ker_root)

    ctx = WorkingContext(
        task="Build memory redesign",
        decisions=["Use tiered approach"],
        pending=["Write tests"],
        last_tools=["read_file path=memory.py", "edit_file path=scorer.py"],
    )
    mgr.save("test_agent", ctx)

    rendered = mgr.render_for_prompt("test_agent")
    assert "Build memory redesign" in rendered
    assert "Use tiered approach" in rendered
    assert "Write tests" in rendered
    assert "edit_file" in rendered


def test_render_for_prompt_truncation(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    mgr = WorkingMemoryManager(ker_root)

    ctx = WorkingContext(
        task="X" * 5000,  # Very long task
    )
    mgr.save("test_agent", ctx)

    rendered = mgr.render_for_prompt("test_agent")
    assert len(rendered) <= WORKING_CONTEXT_MAX_CHARS


def test_update_from_turn_with_mock_session(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    mgr = WorkingMemoryManager(ker_root)

    # Create a mock session store
    class MockSessionStore:
        def load_messages(self, agent_name, session_id):
            return [
                {"role": "user", "content": "Fix the WebSocket bug"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "read_file", "input": {"path": "ws.py"}},
                    {"type": "text", "text": "I found the issue."},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "123", "content": "file contents..."},
                ]},
            ]

    mgr.update_from_turn("test_agent", "session_1", MockSessionStore())

    ctx = mgr.load("test_agent")
    assert "WebSocket" in ctx.task or "Fix" in ctx.task
    assert any("read_file" in t for t in ctx.last_tools)
