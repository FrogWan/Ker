from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ker.longtask.task_board import LongTask, SubTask, TaskBoard
from ker.longtask.worker import Worker, WorkerConfig, WorkerManager
from ker.longtask.orchestrator import LongTaskOrchestrator


# ── TaskBoard tests ──────────────────────────────────────────────


def test_create_task(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("Test Task", "Do something")
    assert task.id
    assert task.title == "Test Task"
    assert task.status == "planning"
    assert (tmp_path / ".ker" / "longtasks" / task.id / "task.json").exists()


def test_create_and_get_task(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T1", "D1", max_workers=5, worker_agent="codex")
    loaded = board.get_task(task.id)
    assert loaded is not None
    assert loaded.title == "T1"
    assert loaded.max_workers == 5
    assert loaded.worker_agent == "codex"


def test_list_tasks(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    board.create_task("A", "a")
    board.create_task("B", "b")
    tasks = board.list_tasks()
    assert len(tasks) == 2


def test_update_task_status(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.update_task_status(task.id, "running")
    loaded = board.get_task(task.id)
    assert loaded.status == "running"


def test_cancel_task(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc1")
    result = board.cancel_task(task.id)
    assert result is True
    loaded = board.get_task(task.id)
    assert loaded.status == "cancelled"
    assert loaded.subtasks[0].status == "failed"


def test_get_nonexistent_task(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    assert board.get_task("nope") is None


# ── Subtask tests ────────────────────────────────────────────────


def test_add_subtask(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    sub = board.add_subtask(task.id, "S1", "Do thing")
    assert sub.id == "sub_001"
    assert sub.status == "pending"

    loaded = board.get_task(task.id)
    assert len(loaded.subtasks) == 1


def test_claim_subtask(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    sub = board.add_subtask(task.id, "S1", "Do thing")

    claimed = board.claim_subtask(task.id, sub.id, "worker_0")
    assert claimed is True

    loaded = board.get_task(task.id)
    assert loaded.subtasks[0].status == "claimed"
    assert loaded.subtasks[0].owner == "worker_0"

    # Can't claim again
    assert board.claim_subtask(task.id, sub.id, "worker_1") is False


def test_complete_subtask(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    sub = board.add_subtask(task.id, "S1", "Do thing")
    board.claim_subtask(task.id, sub.id, "w0")
    board.complete_subtask(task.id, sub.id, "All done!")

    loaded = board.get_task(task.id)
    assert loaded.subtasks[0].status == "done"
    assert loaded.subtasks[0].result == "All done!"

    # Result file written
    result_path = board._task_dir(task.id) / "sub_001.md"
    assert result_path.exists()
    assert result_path.read_text() == "All done!"


def test_fail_subtask(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    sub = board.add_subtask(task.id, "S1", "Do thing")
    board.fail_subtask(task.id, sub.id, "boom")

    loaded = board.get_task(task.id)
    assert loaded.subtasks[0].status == "failed"
    assert loaded.subtasks[0].attempts == 1


def test_reset_for_retry(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    sub = board.add_subtask(task.id, "S1", "Do thing")

    # First failure (attempts=1) → can retry
    board.fail_subtask(task.id, sub.id, "err1")
    assert board.reset_subtask_for_retry(task.id, sub.id) is True
    loaded = board.get_task(task.id)
    assert loaded.subtasks[0].status == "pending"
    assert loaded.subtasks[0].attempts == 1  # attempts preserved

    # Second failure (attempts=2) → can still retry (max is 3)
    board.fail_subtask(task.id, sub.id, "err2")
    assert board.reset_subtask_for_retry(task.id, sub.id) is True

    # Third failure (attempts=3) → max reached, can't retry
    board.fail_subtask(task.id, sub.id, "err3")
    assert board.reset_subtask_for_retry(task.id, sub.id) is False
    loaded = board.get_task(task.id)
    assert loaded.subtasks[0].status == "failed"


# ── Blocking logic ───────────────────────────────────────────────


def test_get_claimable_no_blockers(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")
    board.add_subtask(task.id, "S2", "desc")

    claimable = board.get_claimable(task.id)
    assert len(claimable) == 2


def test_get_claimable_with_blocker(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "base work")
    board.add_subtask(task.id, "S2", "depends on S1", blocked_by=["sub_001"])

    claimable = board.get_claimable(task.id)
    assert len(claimable) == 1
    assert claimable[0].id == "sub_001"

    # Complete S1 → S2 becomes claimable
    board.claim_subtask(task.id, "sub_001", "w0")
    board.complete_subtask(task.id, "sub_001", "done")

    claimable = board.get_claimable(task.id)
    assert len(claimable) == 1
    assert claimable[0].id == "sub_002"


def test_get_claimable_excludes_non_pending(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")
    board.claim_subtask(task.id, "sub_001", "w0")

    # Claimed subtask is not claimable
    assert board.get_claimable(task.id) == []


# ── Inbox tests ──────────────────────────────────────────────────


def test_inbox_send_read(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")

    board.send_message(task.id, "lead", "help please")
    board.send_message(task.id, "lead", "still stuck")

    messages = board.read_inbox(task.id, "lead")
    assert len(messages) == 2
    assert messages[0]["content"] == "help please"

    # Inbox cleared after read
    assert board.read_inbox(task.id, "lead") == []


def test_inbox_empty(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    assert board.read_inbox(task.id, "worker_0") == []


# ── Task prompt ──────────────────────────────────────────────────


def test_task_prompt(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")

    board.write_task_prompt(task.id, "Shared context here")
    assert board.read_task_prompt(task.id) == "Shared context here"


def test_task_prompt_empty(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    assert board.read_task_prompt(task.id) == ""


# ── Milestone fields ─────────────────────────────────────────────


def test_milestone_fields_default(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    loaded = board.get_task(task.id)
    assert loaded.last_milestone == ""
    assert loaded.last_milestone_at == 0.0


def test_milestone_fields_persist(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")

    # Simulate supervisor writing milestones
    loaded = board._load(task.id)
    loaded.last_milestone = "sub_001 completed"
    loaded.last_milestone_at = 1234567890.0
    board._save(loaded)

    reloaded = board.get_task(task.id)
    assert reloaded.last_milestone == "sub_001 completed"
    assert reloaded.last_milestone_at == 1234567890.0


# ── WorkerManager tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_command_claude(tmp_path: Path):
    """Verify command construction for claude worker."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    sub = board.add_subtask(task.id, "S1", "desc")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    mock_proc = AsyncMock()
    mock_proc.pid = 12345
    mock_proc.returncode = None

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        # Mock worktree creation
        wt_proc = AsyncMock()
        wt_proc.returncode = 0
        wt_proc.communicate = AsyncMock(return_value=(b"", b""))

        mock_exec.side_effect = [wt_proc, mock_proc]

        config = WorkerConfig(agent="claude", model="opus-4", dangerous_mode=True)
        worker = await manager.spawn_worker(task.id, "worker_0", sub, "shared ctx", config)

        assert worker.status == "working"
        assert worker.pid == 12345

        # Verify the second call (the claude command)
        call_args = mock_exec.call_args_list[1]
        cmd = call_args[0]
        assert cmd[0] == "claude"
        assert "--dangerously-skip-permissions" in cmd
        assert "--print" in cmd
        assert "--model" in cmd
        assert "opus-4" in cmd
        # Must NOT have --output-format stream-json (requires --verbose)
        assert "--output-format" not in cmd


@pytest.mark.asyncio
async def test_worker_command_codex(tmp_path: Path):
    """Verify command construction for codex worker."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    sub = board.add_subtask(task.id, "S1", "desc")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    mock_proc = AsyncMock()
    mock_proc.pid = 99999
    mock_proc.returncode = None

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        wt_proc = AsyncMock()
        wt_proc.returncode = 0
        wt_proc.communicate = AsyncMock(return_value=(b"", b""))

        mock_exec.side_effect = [wt_proc, mock_proc]

        config = WorkerConfig(agent="codex")
        worker = await manager.spawn_worker(task.id, "worker_0", sub, "ctx", config)

        call_args = mock_exec.call_args_list[1]
        cmd = call_args[0]
        assert cmd[0] == "codex"
        assert "--full-auto" in cmd


@pytest.mark.asyncio
async def test_check_worker_done(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    worker = Worker(name="w0", process=mock_proc, subtask_id="sub_001", task_id="t1")

    status = await manager.check_worker(worker)
    assert status == "done"
    assert worker.status == "done"


@pytest.mark.asyncio
async def test_check_worker_failed(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    worker = Worker(name="w0", process=mock_proc, subtask_id="sub_001", task_id="t1")

    status = await manager.check_worker(worker)
    assert status == "failed"


@pytest.mark.asyncio
async def test_check_worker_still_working(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    mock_proc = MagicMock()
    mock_proc.returncode = None
    worker = Worker(name="w0", process=mock_proc, subtask_id="sub_001", task_id="t1")

    status = await manager.check_worker(worker)
    assert status == "working"


def test_collect_result(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    # Write a result file
    task_dir = tmp_path / ".ker" / "longtasks" / task.id
    (task_dir / "sub_001.md").write_text("Worker output here")

    worker = Worker(name="w0", subtask_id="sub_001", task_id=task.id)
    result = manager.collect_result(worker)
    assert result == "Worker output here"


def test_collect_result_missing(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    worker = Worker(name="w0", subtask_id="sub_001", task_id=task.id)
    assert manager.collect_result(worker) is None


# ── Supervisor spawn tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_spawn_supervisor_claude(tmp_path: Path):
    """Verify supervisor spawns with correct claude command."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    mock_proc = AsyncMock()
    mock_proc.pid = 55555
    mock_proc.returncode = None

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_proc

        config = WorkerConfig(agent="claude", dangerous_mode=True)
        worker = await manager.spawn_supervisor(task.id, "test prompt", config)

        assert worker.name == "supervisor"
        assert worker.status == "working"
        assert worker.pid == 55555
        assert worker.worktree_path is None  # runs in main workspace

        call_args = mock_exec.call_args
        cmd = call_args[0]
        assert cmd[0] == "claude"
        assert "--dangerously-skip-permissions" in cmd
        assert "--print" in cmd
        assert str(tmp_path) == str(call_args[1]["cwd"])


@pytest.mark.asyncio
async def test_get_supervisor(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    # No supervisor yet
    assert manager.get_supervisor(task.id) is None

    # Add a supervisor worker manually
    supervisor = Worker(name="supervisor", task_id=task.id, status="working")
    manager._workers[task.id] = [supervisor]
    assert manager.get_supervisor(task.id) is supervisor

    # Regular workers are not returned
    regular = Worker(name="worker_0", task_id=task.id)
    manager._workers[task.id].append(regular)
    assert manager.get_supervisor(task.id) is supervisor


# ── Orchestrator tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestrator_spawns_supervisor_and_monitors(tmp_path: Path):
    """Integration: orchestrator spawns supervisor, supervisor marks task done, monitor detects it."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("Test", "Integration test", max_workers=2)
    board.add_subtask(task.id, "Part A", "Do A")
    board.add_subtask(task.id, "Part B", "Do B")

    outbound = asyncio.Queue()
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    # Write SUPERVISOR.md template for prompt building
    templates_dir = Path(__file__).resolve().parents[0] / ".." / "src" / "ker" / "memory" / "templates"
    # Use ker_root templates as fallback
    tmpl_dir = tmp_path / ".ker" / "templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "SUPERVISOR.md").write_text(
        "Supervisor for: {task_description}\n"
        "Subtasks: {subtask_list}\n"
        "Context: {task_prompt}\n"
        "Paths: {task_json_path} {task_dir} {workspace}\n"
        "Max workers: {max_workers}\n"
    )

    orchestrator = LongTaskOrchestrator(
        board, manager, outbound, ker_root=tmp_path / ".ker",
    )

    # Mock spawn_supervisor to simulate a supervisor that completes the task
    mock_supervisor_proc = MagicMock()
    # Supervisor starts alive, then we'll mark the task done and let it exit
    call_count = 0

    def returncode_side_effect():
        nonlocal call_count
        call_count += 1
        # Supervisor "exits" after a few polls, but task is already marked done
        if call_count > 2:
            return 0
        return None

    type(mock_supervisor_proc).returncode = property(lambda self: returncode_side_effect())

    async def mock_spawn_supervisor(task_id, prompt, config=None):
        worker = Worker(
            name="supervisor", process=mock_supervisor_proc,
            task_id=task_id, status="working", pid=99999,
        )
        manager._workers[task_id] = [worker]

        # Simulate supervisor completing all subtasks
        for st in board.get_task(task_id).subtasks:
            task_d = tmp_path / ".ker" / "longtasks" / task_id
            (task_d / f"{st.id}.md").write_text(f"Done: {st.subject}")
            board.complete_subtask(task_id, st.id, f"Done: {st.subject}")

        # Supervisor updates task status
        board.update_task_status(task_id, "done")
        return worker

    manager.spawn_supervisor = mock_spawn_supervisor
    manager.cleanup_task_worktrees = AsyncMock()
    manager.kill_worker = AsyncMock()

    await orchestrator.start_task(task.id)
    loop_task = orchestrator._active_tasks.get(task.id)
    assert loop_task is not None
    await asyncio.wait_for(loop_task, timeout=30)

    final = board.get_task(task.id)
    assert final.status == "done"

    # Post-task cleanup should have been called
    manager.cleanup_task_worktrees.assert_called()


@pytest.mark.asyncio
async def test_orchestrator_cancel(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager)

    await orchestrator.cancel_task(task.id)

    loaded = board.get_task(task.id)
    assert loaded.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_kills_supervisor_and_cleans_worktrees(tmp_path: Path):
    """Cancel calls kill_worker on supervisor and cleanup_task_worktrees."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager)

    # Add a fake supervisor
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 12345
    supervisor = Worker(name="supervisor", process=mock_proc, task_id=task.id, status="working")
    manager._workers[task.id] = [supervisor]

    # Mock kill and cleanup
    manager.kill_worker = AsyncMock()
    manager.cleanup_task_worktrees = AsyncMock()

    await orchestrator.cancel_task(task.id)

    # Supervisor was killed
    manager.kill_worker.assert_called()
    killed_workers = [call.args[0] for call in manager.kill_worker.call_args_list]
    assert any(w.name == "supervisor" for w in killed_workers)

    # Worktree cleanup was called
    manager.cleanup_task_worktrees.assert_called_once_with(task.id)

    assert board.get_task(task.id).status == "cancelled"


@pytest.mark.asyncio
async def test_merge_results_full_merge_without_manifest(tmp_path: Path):
    """Without manifest, _merge_results falls back to full git merge."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")
    board.add_subtask(task.id, "S2", "desc")
    board.complete_subtask(task.id, "sub_001", "done")
    board.complete_subtask(task.id, "sub_002", "done")

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager)

    manager.list_task_branches = AsyncMock(return_value=[
        f"longtask/{task.id}/sub_001",
        f"longtask/{task.id}/sub_002",
    ])
    manager.remove_branch = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        merge_proc = AsyncMock()
        merge_proc.returncode = 0
        merge_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_exec.return_value = merge_proc

        await orchestrator._merge_results(task.id)

    # Should have called git merge for both branches (no manifest → full merge)
    merge_calls = [c for c in mock_exec.call_args_list if "merge" in c[0]]
    assert len(merge_calls) == 2
    manager.remove_branch.call_count == 2


@pytest.mark.asyncio
async def test_merge_results_with_manifest_filters_files(tmp_path: Path):
    """With manifest, _merge_results only checks out declared files."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")
    board.complete_subtask(task.id, "sub_001", "done")

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager)

    # Write a manifest for sub_001
    task_dir = tmp_path / ".ker" / "longtasks" / task.id
    (task_dir / "sub_001.manifest.json").write_text(json.dumps({
        "files_modified": ["src/app.py"],
        "files_created": ["src/new_module.py"],
    }))

    branch = f"longtask/{task.id}/sub_001"
    manager.list_task_branches = AsyncMock(return_value=[branch])
    manager.remove_branch = AsyncMock()
    # Branch has 3 files changed, but manifest only declares 2
    manager.get_branch_changed_files = AsyncMock(return_value=[
        "src/app.py", "src/new_module.py", "node_modules/.cache/something"
    ])
    manager.checkout_files_from_branch = AsyncMock(return_value=True)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        commit_proc = AsyncMock()
        commit_proc.returncode = 0
        commit_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_exec.return_value = commit_proc

        await orchestrator._merge_results(task.id)

    # Should have done selective checkout, not full merge
    manager.checkout_files_from_branch.assert_called_once()
    checkout_call = manager.checkout_files_from_branch.call_args
    checked_out_files = checkout_call[0][1]
    assert "src/app.py" in checked_out_files
    assert "src/new_module.py" in checked_out_files
    assert "node_modules/.cache/something" not in checked_out_files


@pytest.mark.asyncio
async def test_merge_skips_non_done_subtasks(tmp_path: Path):
    """_merge_results skips branches for failed subtasks."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")
    board.add_subtask(task.id, "S2", "desc")
    board.complete_subtask(task.id, "sub_001", "done")
    board.fail_subtask(task.id, "sub_002", "error")

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager)

    manager.list_task_branches = AsyncMock(return_value=[
        f"longtask/{task.id}/sub_001",
        f"longtask/{task.id}/sub_002",
    ])
    manager.remove_branch = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        merge_proc = AsyncMock()
        merge_proc.returncode = 0
        merge_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_exec.return_value = merge_proc

        await orchestrator._merge_results(task.id)

    # Only sub_001 should have been merged (sub_002 is failed)
    merge_calls = [c for c in mock_exec.call_args_list if "merge" in c[0]]
    assert len(merge_calls) == 1


@pytest.mark.asyncio
async def test_no_double_notification_on_fallback_finish(tmp_path: Path):
    """When monitor fallback finishes the task, only one notification is sent."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("Test", "Double notify test", max_workers=1)
    board.add_subtask(task.id, "S1", "work")

    outbound = asyncio.Queue()
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    tmpl_dir = tmp_path / ".ker" / "templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "SUPERVISOR.md").write_text(
        "{task_description}\n{subtask_list}\n{task_prompt}\n"
        "{task_json_path}\n{task_dir}\n{workspace}\n{max_workers}\n"
    )

    orchestrator = LongTaskOrchestrator(board, manager, outbound, ker_root=tmp_path / ".ker")

    async def mock_spawn_supervisor(task_id, prompt, config=None):
        # Supervisor completes subtask but doesn't set task status to done
        board.complete_subtask(task_id, "sub_001", "Done")

        mock_proc = MagicMock()
        mock_proc.returncode = 0  # exited
        worker = Worker(
            name="supervisor", process=mock_proc,
            task_id=task_id, status="working", pid=11111,
        )
        manager._workers[task_id] = [worker]
        return worker

    manager.spawn_supervisor = mock_spawn_supervisor
    manager.list_task_branches = AsyncMock(return_value=[])
    manager.cleanup_task_worktrees = AsyncMock()

    await orchestrator.start_task(task.id)
    await asyncio.wait_for(orchestrator._active_tasks[task.id], timeout=30)

    # Count notifications containing "completed"
    notifications = []
    while not outbound.empty():
        msg = outbound.get_nowait()
        notifications.append(msg.text)

    completed_msgs = [n for n in notifications if "completed" in n.lower()]
    assert len(completed_msgs) == 1, f"Expected 1 completion notification, got {len(completed_msgs)}: {completed_msgs}"


@pytest.mark.asyncio
async def test_orchestrator_status(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager)

    status = await orchestrator.get_status(task.id)
    assert status["id"] == task.id
    assert status["status"] == "planning"
    assert status["supervisor"] == "not started"
    assert len(status["subtasks"]) == 1
    assert status["subtasks"][0]["status"] == "pending"


# ── Supervisor prompt generation tests ───────────────────────────


def test_build_supervisor_prompt(tmp_path: Path):
    """Verify supervisor prompt includes task info and subtask status."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("Build App", "Build a web application")
    board.add_subtask(task.id, "Frontend", "Build React frontend")
    board.add_subtask(task.id, "Backend", "Build API backend", blocked_by=["sub_001"])
    board.write_task_prompt(task.id, "Use TypeScript throughout")

    # Write template
    tmpl_dir = tmp_path / ".ker" / "templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "SUPERVISOR.md").write_text(
        "Task: {task_description}\n"
        "Subtasks:\n{subtask_list}\n"
        "Context: {task_prompt}\n"
        "JSON: {task_json_path}\n"
        "Task dir: {task_dir}\n"
        "Workspace: {workspace}\n"
        "Max: {max_workers}\n"
    )

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager, ker_root=tmp_path / ".ker")

    prompt = orchestrator._build_supervisor_prompt(task.id)

    assert "Build App" in prompt
    assert "Build a web application" in prompt
    assert "sub_001" in prompt
    assert "Frontend" in prompt
    assert "Backend" in prompt
    assert "blocked_by" in prompt
    assert "Use TypeScript throughout" in prompt
    assert str(tmp_path) in prompt


def test_build_supervisor_prompt_with_completed_results(tmp_path: Path):
    """Re-spawn prompt includes completed subtask results."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("Test", "Test task")
    board.add_subtask(task.id, "S1", "First part")
    board.add_subtask(task.id, "S2", "Second part")
    board.complete_subtask(task.id, "sub_001", "First part completed successfully")

    tmpl_dir = tmp_path / ".ker" / "templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "SUPERVISOR.md").write_text(
        "{task_description}\n{subtask_list}\n{task_prompt}\n"
        "{task_json_path}\n{task_dir}\n{workspace}\n{max_workers}\n"
    )

    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager, ker_root=tmp_path / ".ker")

    prompt = orchestrator._build_supervisor_prompt(task.id)

    assert "[done]" in prompt
    assert "First part completed successfully" in prompt
    assert "[pending]" in prompt


# ── Monitor milestone detection tests ────────────────────────────


@pytest.mark.asyncio
async def test_milestone_notification(tmp_path: Path):
    """Monitor sends notification when milestone changes."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")
    board.add_subtask(task.id, "S2", "desc")

    outbound = asyncio.Queue()
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager, outbound)

    # Simulate supervisor writing milestone
    loaded = board._load(task.id)
    loaded.last_milestone = "sub_001 completed"
    loaded.last_milestone_at = time.time()
    loaded.subtasks[0].status = "done"
    board._save(loaded)

    task = board.get_task(task.id)
    await orchestrator._check_milestones(task)

    # Should have sent a notification
    assert not outbound.empty()
    msg = outbound.get_nowait()
    assert "1/2 subtasks completed" in msg.text
    assert "sub_001 completed" in msg.text


@pytest.mark.asyncio
async def test_milestone_rate_limiting(tmp_path: Path):
    """Monitor respects notification cooldown."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "desc")

    outbound = asyncio.Queue()
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager, outbound)

    # First milestone
    loaded = board._load(task.id)
    loaded.last_milestone = "first"
    loaded.last_milestone_at = time.time()
    board._save(loaded)
    task = board.get_task(task.id)
    await orchestrator._check_milestones(task)
    assert not outbound.empty()
    outbound.get_nowait()

    # Second milestone immediately after — should be rate-limited
    loaded = board._load(task.id)
    loaded.last_milestone = "second"
    loaded.last_milestone_at = time.time()
    board._save(loaded)
    task = board.get_task(task.id)
    await orchestrator._check_milestones(task)
    assert outbound.empty()  # rate-limited, no notification


# ── Supervisor re-spawn logic tests ──────────────────────────────


@pytest.mark.asyncio
async def test_supervisor_respawn_on_exit(tmp_path: Path):
    """Monitor re-spawns supervisor when it exits with work remaining."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("Test", "Re-spawn test", max_workers=2)
    board.add_subtask(task.id, "S1", "Work item")

    outbound = asyncio.Queue()
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    tmpl_dir = tmp_path / ".ker" / "templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "SUPERVISOR.md").write_text(
        "{task_description}\n{subtask_list}\n{task_prompt}\n"
        "{task_json_path}\n{task_dir}\n{workspace}\n{max_workers}\n"
    )

    orchestrator = LongTaskOrchestrator(board, manager, outbound, ker_root=tmp_path / ".ker")

    spawn_count = 0

    async def mock_spawn_supervisor(task_id, prompt, config=None):
        nonlocal spawn_count
        spawn_count += 1

        mock_proc = MagicMock()
        # First spawn: supervisor exits immediately (simulating crash)
        # Second spawn: supervisor completes the task
        if spawn_count == 1:
            mock_proc.returncode = 1  # exited
        else:
            mock_proc.returncode = 0
            # Complete all subtasks and mark task done
            for st in board.get_task(task_id).subtasks:
                board.complete_subtask(task_id, st.id, "Done")
            board.update_task_status(task_id, "done")

        worker = Worker(
            name="supervisor", process=mock_proc,
            task_id=task_id, status="working", pid=spawn_count * 1000,
        )
        manager._workers[task_id] = [w for w in manager._workers.get(task_id, []) if w.name != "supervisor"]
        manager._workers.setdefault(task_id, []).append(worker)
        return worker

    manager.spawn_supervisor = mock_spawn_supervisor
    manager.cleanup_task_worktrees = AsyncMock()

    await orchestrator.start_task(task.id)
    await asyncio.wait_for(orchestrator._active_tasks[task.id], timeout=30)

    # Should have spawned supervisor twice (initial + 1 re-spawn)
    assert spawn_count == 2
    assert board.get_task(task.id).status == "done"


# ── tool_longtask tests ──────────────────────────────────────────


def test_tool_longtask_plan():
    from ker.tools.tool_longtask import _detect_cycle

    # No cycle
    subtasks = [
        {"subject": "A", "blocked_by": []},
        {"subject": "B", "blocked_by": ["sub_001"]},
    ]
    assert _detect_cycle(subtasks, ["sub_001", "sub_002"]) is None

    # Cycle: sub_001 → sub_002 → sub_001
    subtasks_cycle = [
        {"subject": "A", "blocked_by": ["sub_002"]},
        {"subject": "B", "blocked_by": ["sub_001"]},
    ]
    result = _detect_cycle(subtasks_cycle, ["sub_001", "sub_002"])
    assert result is not None


def test_progress_bar():
    from ker.tools.tool_longtask import _progress_bar

    assert _progress_bar(0, 5) == "[..........]"
    assert _progress_bar(5, 5) == "[##########]"
    assert _progress_bar(3, 5) == "[######....]"
    assert _progress_bar(0, 0) == "[..........]"


# ── Manifest tests ──────────────────────────────────────────────


def test_read_manifest(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    # Write a manifest
    task_dir = tmp_path / ".ker" / "longtasks" / task.id
    (task_dir / "sub_001.manifest.json").write_text(json.dumps({
        "files_modified": ["src/foo.py"],
        "files_created": ["src/bar.py"],
        "files_deleted": ["src/old.py"],
    }))

    manifest = manager.read_manifest(task.id, "sub_001")
    assert manifest is not None
    assert manifest["files_modified"] == ["src/foo.py"]
    assert manifest["files_created"] == ["src/bar.py"]
    assert manifest["files_deleted"] == ["src/old.py"]


def test_read_manifest_missing(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    assert manager.read_manifest(task.id, "sub_001") is None


def test_get_manifest_files(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    task_dir = tmp_path / ".ker" / "longtasks" / task.id
    (task_dir / "sub_001.manifest.json").write_text(json.dumps({
        "files_modified": ["src/a.py"],
        "files_created": ["src/b.py"],
        "files_deleted": ["src/c.py"],
    }))

    files = manager.get_manifest_files(task.id, "sub_001")
    # files_modified + files_created (not deleted)
    assert files == {"src/a.py", "src/b.py"}


def test_get_manifest_files_empty(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    assert manager.get_manifest_files(task.id, "sub_999") == set()


@pytest.mark.asyncio
async def test_post_task_cleanup(tmp_path: Path):
    """Post-task cleanup removes worktrees and kills supervisor."""
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)
    orchestrator = LongTaskOrchestrator(board, manager)

    # Add a running supervisor
    mock_proc = MagicMock()
    mock_proc.returncode = None
    supervisor = Worker(name="supervisor", process=mock_proc, task_id=task.id, status="working")
    manager._workers[task.id] = [supervisor]

    manager.cleanup_task_worktrees = AsyncMock()
    manager.kill_worker = AsyncMock()

    await orchestrator._post_task_cleanup(task.id)

    manager.cleanup_task_worktrees.assert_called_once_with(task.id)
    manager.kill_worker.assert_called_once_with(supervisor)


# ── update_subtask_description tests ────────────────────────────


def test_update_subtask_description(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    board.add_subtask(task.id, "S1", "original description")

    result = board.update_subtask_description(task.id, "sub_001", "refined description")
    assert result is True

    loaded = board.get_task(task.id)
    assert loaded.subtasks[0].description == "refined description"


def test_update_subtask_description_nonexistent(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    result = board.update_subtask_description(task.id, "sub_999", "nope")
    assert result is False


# ── Worker stderr/event logging tests ──────────────────────────


def test_read_stderr(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    # Write a stderr log file
    task_dir = tmp_path / ".ker" / "longtasks" / task.id
    (task_dir / "w0.stderr.log").write_text("Error: command not found\n")

    worker = Worker(name="w0", subtask_id="sub_001", task_id=task.id)
    stderr = manager.read_stderr(worker)
    assert "command not found" in stderr


def test_read_stderr_missing(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    worker = Worker(name="w0", subtask_id="sub_001", task_id=task.id)
    assert manager.read_stderr(worker) == ""


def test_worker_event_log(tmp_path: Path):
    board = TaskBoard(ker_root=tmp_path / ".ker", workspace=tmp_path)
    task = board.create_task("T", "D")
    manager = WorkerManager(workspace=tmp_path, ker_root=tmp_path / ".ker", task_board=board)

    manager._log_worker_event(task.id, "w0", "spawn", {"pid": 123})
    manager._log_worker_event(task.id, "w0", "done", {"exit_code": 0})

    events_path = tmp_path / ".ker" / "longtasks" / task.id / "events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "spawn"
    assert json.loads(lines[1])["event"] == "done"


# ── Orchestrator _extract_json tests ───────────────────────────


def test_extract_json_code_block():
    orch = LongTaskOrchestrator(
        task_board=MagicMock(), worker_manager=MagicMock(),
    )
    text = 'Here is my analysis:\n```json\n{"action": "retry", "description": "new desc"}\n```'
    result = orch._extract_json(text)
    assert result == {"action": "retry", "description": "new desc"}


def test_extract_json_bare():
    orch = LongTaskOrchestrator(
        task_board=MagicMock(), worker_manager=MagicMock(),
    )
    text = 'I think we should skip. {"action": "skip", "reason": "impossible"}'
    result = orch._extract_json(text)
    assert result == {"action": "skip", "reason": "impossible"}


def test_extract_json_no_json():
    orch = LongTaskOrchestrator(
        task_board=MagicMock(), worker_manager=MagicMock(),
    )
    result = orch._extract_json("no json here at all")
    assert result is None
