from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ker.tools.tool_base import ToolContext
from ker.tools.tool_fallback import (
    fallback,
    _resolve_cli_order,
    _build_command,
    _read_output,
    _run_fallback,
    _background_tasks,
    MAX_OUTPUT,
)


def _make_ctx(tmp_path: Path) -> ToolContext:
    ker_root = tmp_path / ".ker"
    ker_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(workspace=tmp_path, ker_root=ker_root)
    ctx.outbound_queue = asyncio.Queue()
    return ctx


# ---------------------------------------------------------------------------
# CLI detection
# ---------------------------------------------------------------------------

class TestCLIDetection:
    @patch("ker.tools.tool_fallback.shutil.which", return_value=None)
    @pytest.mark.asyncio
    async def test_neither_cli_available(self, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = await fallback(ctx, request="do something")
        assert "neither" in result.lower() or "not found" in result.lower()

    @patch("ker.tools.tool_fallback.shutil.which", side_effect=lambda name: "/usr/bin/claude" if name == "claude" else None)
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_only_claude_available(self, mock_exec, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        proc = AsyncMock()
        proc.pid = 1234
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=0)
        mock_exec.return_value = proc

        result = await fallback(ctx, request="hello", task_name="test-claude")
        assert "working on your request" in result.lower()
        # Let background task run
        await asyncio.sleep(0.1)

    @patch("ker.tools.tool_fallback.shutil.which", side_effect=lambda name: "/usr/bin/codex" if name == "codex" else None)
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_only_codex_available(self, mock_exec, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        proc = AsyncMock()
        proc.pid = 1234
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=0)
        mock_exec.return_value = proc

        result = await fallback(ctx, request="hello", task_name="test-codex")
        assert "working on your request" in result.lower()
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# CLI preference ordering
# ---------------------------------------------------------------------------

class TestCLIOrder:
    def test_default_order_claude_first(self):
        order = _resolve_cli_order(None, "/bin/claude", "/bin/codex")
        assert order[0][0] == "claude"
        assert order[1][0] == "codex"

    def test_prefer_codex(self):
        order = _resolve_cli_order("codex", "/bin/claude", "/bin/codex")
        assert order[0][0] == "codex"
        assert order[1][0] == "claude"

    def test_prefer_claude(self):
        order = _resolve_cli_order("claude", "/bin/claude", "/bin/codex")
        assert order[0][0] == "claude"

    def test_prefer_unavailable_ignored(self):
        order = _resolve_cli_order("codex", "/bin/claude", None)
        assert len(order) == 1
        assert order[0][0] == "claude"

    def test_only_codex(self):
        order = _resolve_cli_order(None, None, "/bin/codex")
        assert len(order) == 1
        assert order[0][0] == "codex"


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

class TestBuildCommand:
    def test_claude_command(self):
        cmd = _build_command("claude", "/bin/claude", "do stuff")
        assert cmd == ["/bin/claude", "--dangerously-skip-permissions", "-p", "do stuff"]

    def test_codex_command(self):
        cmd = _build_command("codex", "/bin/codex", "do stuff")
        assert cmd == ["/bin/codex", "exec", "do stuff", "--full-auto"]


# ---------------------------------------------------------------------------
# Immediate return message
# ---------------------------------------------------------------------------

class TestImmediateReturn:
    @patch("ker.tools.tool_fallback.shutil.which", return_value="/usr/bin/claude")
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_returns_working_message(self, mock_exec, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        proc = AsyncMock()
        proc.pid = 99
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=0)
        mock_exec.return_value = proc

        result = await fallback(ctx, request="hello")
        assert "working on your request" in result.lower()
        assert "notify" in result.lower() or "answer" in result.lower()
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Auto-generated task name
# ---------------------------------------------------------------------------

class TestAutoTaskName:
    @patch("ker.tools.tool_fallback.shutil.which", return_value="/usr/bin/claude")
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_auto_task_name(self, mock_exec, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        proc = AsyncMock()
        proc.pid = 99
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=0)
        mock_exec.return_value = proc

        result = await fallback(ctx, request="hello world")
        assert "fb_" in result
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Background task notification
# ---------------------------------------------------------------------------

class TestBackgroundNotification:
    @patch("ker.tools.tool_fallback.shutil.which", return_value="/usr/bin/claude")
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_success_notification(self, mock_exec, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        proc = AsyncMock()
        proc.pid = 42
        proc.returncode = 0
        proc.wait = AsyncMock(return_value=0)
        mock_exec.return_value = proc

        await fallback(ctx, request="solve problem", task_name="notif-test")

        # Wait for background task to complete
        task = _background_tasks.get("notif-test")
        if task:
            await asyncio.wait_for(task, timeout=5)

        msg = ctx.outbound_queue.get_nowait()
        assert "[fallback]" in msg.text
        assert "notif-test" in msg.text

    @patch("ker.tools.tool_fallback.shutil.which", return_value="/usr/bin/claude")
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_failure_notification(self, mock_exec, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        proc = AsyncMock()
        proc.pid = 42
        proc.returncode = 1
        proc.wait = AsyncMock(return_value=1)
        mock_exec.return_value = proc

        await fallback(ctx, request="bad request", task_name="fail-test")

        task = _background_tasks.get("fail-test")
        if task:
            await asyncio.wait_for(task, timeout=5)

        msg = ctx.outbound_queue.get_nowait()
        assert "[fallback]" in msg.text
        assert "could not complete" in msg.text.lower()


# ---------------------------------------------------------------------------
# Fallback to second CLI
# ---------------------------------------------------------------------------

class TestFallbackToSecondCLI:
    @patch("ker.tools.tool_fallback.shutil.which", side_effect=lambda name: f"/usr/bin/{name}")
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_first_fails_second_succeeds(self, mock_exec, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)

        call_count = [0]

        async def fake_exec(*args, **kwargs):
            call_count[0] += 1
            proc = AsyncMock()
            proc.pid = 100 + call_count[0]
            if call_count[0] == 1:
                proc.returncode = 1
                proc.wait = AsyncMock(return_value=1)
            else:
                proc.returncode = 0
                proc.wait = AsyncMock(return_value=0)
            return proc

        mock_exec.side_effect = fake_exec

        await fallback(ctx, request="try both", task_name="fallback-test")

        task = _background_tasks.get("fallback-test")
        if task:
            await asyncio.wait_for(task, timeout=5)

        msg = ctx.outbound_queue.get_nowait()
        assert "[fallback]" in msg.text
        assert "result" in msg.text.lower()
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    @patch("ker.tools.tool_fallback._kill_process_tree")
    @patch("ker.tools.tool_fallback.shutil.which", side_effect=lambda name: "/usr/bin/claude" if name == "claude" else None)
    @patch("ker.tools.tool_fallback.asyncio.create_subprocess_exec")
    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, mock_exec, mock_which, mock_kill, tmp_path: Path):
        ctx = _make_ctx(tmp_path)

        proc = AsyncMock()
        proc.pid = 999

        # First call hangs (triggers timeout), second call returns immediately (after kill)
        call_count = [0]
        async def wait_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                await asyncio.sleep(100)
            return -1

        proc.wait = wait_side_effect
        proc.returncode = -1
        proc.kill = MagicMock()
        mock_exec.return_value = proc

        await fallback(ctx, request="slow task", task_name="timeout-test", timeout=1)

        task = _background_tasks.get("timeout-test")
        if task:
            await asyncio.wait_for(task, timeout=5)

        msg = ctx.outbound_queue.get_nowait()
        assert "could not complete" in msg.text.lower()
        assert "timed out" in msg.text.lower()
        mock_kill.assert_called_once_with(999)


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------

class TestOutputTruncation:
    def test_short_output(self, tmp_path: Path):
        f = tmp_path / "short.log"
        f.write_text("hello", encoding="utf-8")
        assert _read_output(f) == "hello"

    def test_long_output_truncated(self, tmp_path: Path):
        f = tmp_path / "long.log"
        content = "x" * (MAX_OUTPUT + 5000)
        f.write_text(content, encoding="utf-8")
        result = _read_output(f)
        assert len(result) < len(content)
        assert "truncated" in result

    def test_missing_file(self, tmp_path: Path):
        result = _read_output(tmp_path / "nope.log")
        assert "could not read" in result.lower()
