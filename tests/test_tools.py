from pathlib import Path
from ker.tools.tool_base import ToolContext, safe_path
from ker.tools.tool_filesystem import read_file, write_file, edit_file, list_dir
from ker.tools.tool_exec import _guard_command


def test_safe_path(tmp_path: Path):
    result = safe_path(tmp_path, "test.txt")
    assert result == tmp_path / "test.txt"


def test_safe_path_traversal(tmp_path: Path):
    import pytest
    with pytest.raises(ValueError, match="Path escapes workspace"):
        safe_path(tmp_path, "../../etc/passwd")


def test_read_write_file(tmp_path: Path):
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    result = write_file(ctx, "test.txt", "hello world")
    assert "Wrote" in result

    content = read_file(ctx, "test.txt")
    assert content == "hello world"


def test_edit_file(tmp_path: Path):
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    (tmp_path / "test.txt").write_text("hello world", encoding="utf-8")
    result = edit_file(ctx, "test.txt", "hello", "goodbye")
    assert "Edited" in result
    assert (tmp_path / "test.txt").read_text() == "goodbye world"


def test_list_dir(tmp_path: Path):
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b").mkdir()
    result = list_dir(ctx, ".")
    assert "[F] a.txt" in result
    assert "[D] b" in result


def test_guard_command_blocks_dangerous():
    assert _guard_command("rm -rf /") is not None
    assert _guard_command("shutdown now") is not None
    assert _guard_command("ls -la") is None
