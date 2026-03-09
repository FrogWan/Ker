from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ker.tools.tool_base import ToolContext
from ker.tools.tool_longtask import (
    long_task,
    _parse_reviewer_log,
    _read_status,
    _write_status,
    _update_status,
    _append_history,
    _kill_process_tree,
    _task_runner,
)


def _make_ctx(tmp_path: Path) -> ToolContext:
    ker_root = tmp_path / ".ker"
    ker_root.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=tmp_path, ker_root=ker_root)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestStartValidation:
    def test_missing_task_name(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="start")
        assert "task_name is required" in result

    def test_missing_workspace(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="start", task_name="test")
        assert "workspace is required" in result

    def test_missing_description(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="start", task_name="test", workspace=str(tmp_path))
        assert "description is required" in result

    def test_nonexistent_workspace(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="start", task_name="test", workspace="/nonexistent/path", description="do stuff")
        assert "does not exist" in result

    @patch("ker.tools.tool_longtask.shutil.which", return_value=None)
    def test_claude_not_found(self, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="start", task_name="test", workspace=str(tmp_path), description="do stuff")
        assert "claude" in result.lower() and "not found" in result.lower()

    @patch("ker.tools.tool_longtask.shutil.which", return_value="/usr/bin/claude")
    @patch("ker.tools.tool_longtask.threading.Thread")
    def test_duplicate_running_task(self, mock_thread, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        # Pre-create a running task
        task_dir = ctx.ker_root / "longTask" / "my-task"
        task_dir.mkdir(parents=True)
        _write_status(task_dir / "status.json", {
            "task_name": "my-task",
            "status": "implementing",
            "cancelled": False,
        })

        result = long_task(ctx, action="start", task_name="my-task", workspace=str(tmp_path), description="again")
        assert "already running" in result

    @patch("ker.tools.tool_longtask.shutil.which", return_value="/usr/bin/claude")
    @patch("ker.tools.tool_longtask.threading.Thread")
    def test_start_success(self, mock_thread, mock_which, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="start", task_name="my-task", workspace=str(tmp_path), description="build it")
        assert "started" in result.lower()
        mock_thread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# Status / List / Cancel
# ---------------------------------------------------------------------------

class TestStatusListCancel:
    def test_status_missing_name(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="status")
        assert "task_name is required" in result

    def test_status_not_found(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="status", task_name="nope")
        assert "no task" in result.lower()

    def test_status_found(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        task_dir = ctx.ker_root / "longTask" / "task1"
        task_dir.mkdir(parents=True)
        _write_status(task_dir / "status.json", {
            "task_name": "task1",
            "status": "implementing",
            "iteration": 2,
            "max_iterations": 3,
            "current_agent": "worker",
            "started_at": "2026-03-09T10:00:00Z",
            "updated_at": "2026-03-09T10:05:00Z",
            "result": None,
            "error": None,
            "history": [],
        })

        result = long_task(ctx, action="status", task_name="task1")
        assert "task1" in result
        assert "implementing" in result
        assert "2/3" in result

    def test_list_empty(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="list")
        assert "No long tasks" in result

    def test_list_with_tasks(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        for name, status in [("task-a", "complete"), ("task-b", "implementing")]:
            d = ctx.ker_root / "longTask" / name
            d.mkdir(parents=True)
            _write_status(d / "status.json", {
                "task_name": name,
                "status": status,
                "iteration": 1,
                "max_iterations": 3,
            })

        result = long_task(ctx, action="list")
        assert "task-a" in result
        assert "task-b" in result
        assert "complete" in result

    def test_cancel_not_found(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        result = long_task(ctx, action="cancel", task_name="nope")
        assert "no task" in result.lower()

    def test_cancel_already_done(self, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        d = ctx.ker_root / "longTask" / "done-task"
        d.mkdir(parents=True)
        _write_status(d / "status.json", {
            "task_name": "done-task",
            "status": "complete",
            "cancelled": False,
            "pid": None,
        })

        result = long_task(ctx, action="cancel", task_name="done-task")
        assert "already complete" in result

    @patch("ker.tools.tool_longtask._kill_process_tree")
    def test_cancel_running(self, mock_kill, tmp_path: Path):
        ctx = _make_ctx(tmp_path)
        d = ctx.ker_root / "longTask" / "running"
        d.mkdir(parents=True)
        _write_status(d / "status.json", {
            "task_name": "running",
            "status": "implementing",
            "cancelled": False,
            "pid": 12345,
        })

        result = long_task(ctx, action="cancel", task_name="running")
        assert "cancelled" in result.lower()
        mock_kill.assert_called_once_with(12345)

        status = _read_status(d / "status.json")
        assert status["cancelled"] is True
        assert status["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------

def test_unknown_action(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = long_task(ctx, action="bogus")
    assert "Unknown action" in result


# ---------------------------------------------------------------------------
# Reviewer log parsing
# ---------------------------------------------------------------------------

class TestParseReviewerLog:
    def test_pass_verdict(self, tmp_path: Path):
        log_file = tmp_path / "reviewer.log"
        log_file.write_text("All checks passed.\nVERDICT: PASS\nGreat work!", encoding="utf-8")
        verdict, feedback = _parse_reviewer_log(log_file)
        assert verdict == "PASS"
        assert "Great work!" in feedback

    def test_fail_verdict(self, tmp_path: Path):
        log_file = tmp_path / "reviewer.log"
        log_file.write_text("Missing tests.\nVERDICT: FAIL\nNeed unit tests.", encoding="utf-8")
        verdict, feedback = _parse_reviewer_log(log_file)
        assert verdict == "FAIL"
        assert "unit tests" in feedback

    def test_no_verdict(self, tmp_path: Path):
        log_file = tmp_path / "reviewer.log"
        log_file.write_text("Some random output without verdict.", encoding="utf-8")
        verdict, feedback = _parse_reviewer_log(log_file)
        assert verdict == "FAIL"

    def test_missing_log(self, tmp_path: Path):
        verdict, feedback = _parse_reviewer_log(tmp_path / "missing.log")
        assert verdict == "FAIL"
        assert "not found" in feedback.lower()

    def test_fail_verdict_feedback_before(self, tmp_path: Path):
        log_file = tmp_path / "reviewer.log"
        log_file.write_text("Missing error handling for JWT.\nVERDICT: FAIL", encoding="utf-8")
        verdict, feedback = _parse_reviewer_log(log_file)
        assert verdict == "FAIL"
        assert "JWT" in feedback


# ---------------------------------------------------------------------------
# Runner logic (mocked subprocess)
# ---------------------------------------------------------------------------

class TestTaskRunner:
    def _setup_task(self, tmp_path: Path, max_iter: int = 3) -> tuple[ToolContext, Path, Path]:
        ctx = _make_ctx(tmp_path)
        task_dir = ctx.ker_root / "longTask" / "runner-test"
        task_dir.mkdir(parents=True)
        (task_dir / "task.md").write_text("Build a feature.", encoding="utf-8")
        _write_status(task_dir / "status.json", {
            "task_name": "runner-test",
            "workspace": str(tmp_path),
            "status": "initializing",
            "iteration": 0,
            "max_iterations": max_iter,
            "started_at": "2026-03-09T10:00:00Z",
            "updated_at": "2026-03-09T10:00:00Z",
            "cancelled": False,
            "current_agent": None,
            "pid": None,
            "history": [],
            "result": None,
            "error": None,
        })
        return ctx, task_dir, task_dir / "status.json"

    @patch("ker.tools.tool_longtask._run_claude")
    def test_pass_on_first_iteration(self, mock_run, tmp_path: Path):
        ctx, task_dir, status_path = self._setup_task(tmp_path)

        call_count = [0]
        def side_effect(prompt, workspace, log_file, sp):
            call_count[0] += 1
            # Worker call: exit 0
            if "worker" in str(log_file):
                return 0
            # Reviewer call: write PASS log
            log_file.write_text("All good.\nVERDICT: PASS\n", encoding="utf-8")
            return 0

        mock_run.side_effect = side_effect
        _task_runner(ctx, "runner-test", task_dir, tmp_path, 3)

        status = _read_status(status_path)
        assert status["status"] == "complete"
        assert "1 iteration" in status["result"]

    @patch("ker.tools.tool_longtask._run_claude")
    def test_needs_two_iterations(self, mock_run, tmp_path: Path):
        ctx, task_dir, status_path = self._setup_task(tmp_path)

        iteration_tracker = [0]
        def side_effect(prompt, workspace, log_file, sp):
            name = log_file.name
            if "worker" in name:
                return 0
            if "reviewer_iter1" in name:
                log_file.write_text("Missing tests.\nVERDICT: FAIL\nAdd tests.", encoding="utf-8")
                return 0
            if "reviewer_iter2" in name:
                log_file.write_text("VERDICT: PASS\n", encoding="utf-8")
                return 0
            return 0

        mock_run.side_effect = side_effect
        _task_runner(ctx, "runner-test", task_dir, tmp_path, 3)

        status = _read_status(status_path)
        assert status["status"] == "complete"
        assert "2 iteration" in status["result"]

    @patch("ker.tools.tool_longtask._run_claude")
    def test_exhausts_max_iterations(self, mock_run, tmp_path: Path):
        ctx, task_dir, status_path = self._setup_task(tmp_path, max_iter=2)

        def side_effect(prompt, workspace, log_file, sp):
            if "worker" in log_file.name:
                return 0
            log_file.write_text("VERDICT: FAIL\nStill broken.", encoding="utf-8")
            return 0

        mock_run.side_effect = side_effect
        _task_runner(ctx, "runner-test", task_dir, tmp_path, 2)

        status = _read_status(status_path)
        assert status["status"] == "failed"
        assert "Exhausted" in status["error"]

    @patch("ker.tools.tool_longtask._run_claude")
    def test_worker_crash(self, mock_run, tmp_path: Path):
        ctx, task_dir, status_path = self._setup_task(tmp_path)

        mock_run.return_value = 1
        _task_runner(ctx, "runner-test", task_dir, tmp_path, 3)

        status = _read_status(status_path)
        assert status["status"] == "failed"
        assert "code 1" in status["error"]

    @patch("ker.tools.tool_longtask._run_claude")
    def test_cancelled_mid_run(self, mock_run, tmp_path: Path):
        ctx, task_dir, status_path = self._setup_task(tmp_path)

        def side_effect(prompt, workspace, log_file, sp):
            if "worker" in log_file.name:
                # Set cancelled flag while worker is "running"
                _update_status(sp, {"cancelled": True})
                return 0
            return 0

        mock_run.side_effect = side_effect
        _task_runner(ctx, "runner-test", task_dir, tmp_path, 3)

        status = _read_status(status_path)
        # Runner should have exited early after detecting cancellation
        assert status["cancelled"] is True


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

class TestStatusHelpers:
    def test_read_nonexistent(self, tmp_path: Path):
        assert _read_status(tmp_path / "nope.json") is None

    def test_malformed_json(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("{bad json", encoding="utf-8")
        assert _read_status(p) is None

    def test_write_and_read(self, tmp_path: Path):
        p = tmp_path / "s.json"
        _write_status(p, {"status": "ok"})
        assert _read_status(p) == {"status": "ok"}

    def test_update(self, tmp_path: Path):
        p = tmp_path / "s.json"
        _write_status(p, {"status": "old", "iteration": 0})
        _update_status(p, {"status": "new", "iteration": 1})
        s = _read_status(p)
        assert s["status"] == "new"
        assert s["iteration"] == 1
        assert "updated_at" in s

    def test_append_history(self, tmp_path: Path):
        p = tmp_path / "s.json"
        _write_status(p, {"history": []})
        _append_history(p, {"agent": "worker", "iteration": 1})
        _append_history(p, {"agent": "reviewer", "iteration": 1})
        s = _read_status(p)
        assert len(s["history"]) == 2
        assert s["history"][0]["agent"] == "worker"
        assert s["history"][1]["agent"] == "reviewer"
