from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ker.scheduler.cron import CronService
from ker.tools.tool_base import ToolContext
from ker.tools.tool_evolve import self_evolve


async def dummy_run(payload: dict) -> str:
    return "ok"


def _make_ctx(tmp_path: Path, with_cron: bool = True, with_subagent: bool = False) -> ToolContext:
    ker_root = tmp_path / ".ker"
    ker_root.mkdir(parents=True, exist_ok=True)

    cron_service = None
    if with_cron:
        cron_service = CronService(workspace=tmp_path, ker_root=ker_root, run_payload=dummy_run)
        cron_service.start()

    subagent_manager = MagicMock() if with_subagent else None

    return ToolContext(
        workspace=tmp_path,
        ker_root=ker_root,
        cron_service=cron_service,
        subagent_manager=subagent_manager,
    )


# --- status ---

def test_status_no_history(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = self_evolve(ctx, action="status")
    assert "0" in result or "Total cycles: 0" in result
    assert "No evolution cycles have run yet" in result


def test_status_with_history(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    log_dir = ctx.ker_root / "memory" / "evolution"
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.time(),
        "date": "2026-03-08",
        "changed": ".ker/agents/ker/AGENT.md",
        "reason": "Recurring file-read errors",
        "action": "Added guideline: re-read after edits",
        "axis": "technical",
    }
    (log_dir / "log.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

    result = self_evolve(ctx, action="status")
    assert "Total cycles: 1" in result
    assert "2026-03-08" in result
    assert "technical" in result


# --- history ---

def test_history_empty(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = self_evolve(ctx, action="history")
    assert "No evolution history yet" in result


def test_history_with_entries(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    log_dir = ctx.ker_root / "memory" / "evolution"
    log_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(5):
        entries.append(json.dumps({
            "ts": time.time() + i,
            "date": f"2026-03-0{i+1}",
            "changed": None if i % 2 == 0 else ".ker/agents/ker/AGENT.md",
            "reason": f"reason-{i}",
            "action": f"action-{i}",
            "axis": "technical",
        }))
    (log_dir / "log.jsonl").write_text("\n".join(entries) + "\n", encoding="utf-8")

    result = self_evolve(ctx, action="history", limit=3)
    assert "last 3 entries" in result
    # Should only show last 3
    assert "2026-03-03" in result
    assert "2026-03-05" in result


def test_history_limit_respected(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    log_dir = ctx.ker_root / "memory" / "evolution"
    log_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(20):
        entries.append(json.dumps({
            "ts": time.time() + i,
            "date": f"2026-01-{i+1:02d}",
            "changed": None,
            "reason": "test",
            "action": "skip",
            "axis": "technical",
        }))
    (log_dir / "log.jsonl").write_text("\n".join(entries) + "\n", encoding="utf-8")

    result = self_evolve(ctx, action="history", limit=5)
    assert "last 5 entries" in result


# --- config ---

def test_config_read(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = self_evolve(ctx, action="config")
    assert "cron_expr" in result
    assert "0 3 * * *" in result


def test_config_update(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = self_evolve(ctx, action="config", cron_expr="0 6 * * *", enabled=True)
    assert "0 6 * * *" in result
    assert "updated" in result.lower() or "config" in result.lower()

    # Verify config was written
    cfg_path = ctx.ker_root / "memory" / "evolution" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["cron_expr"] == "0 6 * * *"
    assert cfg["enabled"] is True

    # Verify cron job was recreated
    jobs = ctx.cron_service.list_jobs()
    evolve_jobs = [j for j in jobs if j.name == "self-evolve"]
    assert len(evolve_jobs) == 1
    assert evolve_jobs[0].schedule_config["expr"] == "0 6 * * *"


def test_config_disable(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    # First create a job
    self_evolve(ctx, action="config", enabled=True)
    jobs_before = [j for j in ctx.cron_service.list_jobs() if j.name == "self-evolve"]
    assert len(jobs_before) == 1

    # Disable
    self_evolve(ctx, action="config", enabled=False)
    jobs_after = [j for j in ctx.cron_service.list_jobs() if j.name == "self-evolve"]
    assert len(jobs_after) == 0


# --- trigger ---

def test_trigger_without_subagent(tmp_path: Path):
    ctx = _make_ctx(tmp_path, with_subagent=False)
    result = self_evolve(ctx, action="trigger")
    assert "error" in result.lower()
    assert "subagent" in result.lower()


# --- unknown action ---

def test_unknown_action(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = self_evolve(ctx, action="bogus")
    assert "Unknown action" in result


# --- gateway integration ---

def test_ensure_evolution_cron_creates_job(tmp_path: Path):
    """Test that _ensure_evolution_cron creates the job when none exists."""
    ker_root = tmp_path / ".ker"
    ker_root.mkdir(parents=True, exist_ok=True)

    cron = CronService(workspace=tmp_path, ker_root=ker_root, run_payload=dummy_run)
    cron.start()

    ctx = ToolContext(workspace=tmp_path, ker_root=ker_root, cron_service=cron)

    # Simulate what gateway._ensure_evolution_cron does
    from ker.tools.tool_evolve import (
        DEFAULT_CONFIG,
        JOB_NAME,
        _config_path,
        _evolve_prompt,
        _read_config,
        _write_config,
    )

    cfg_path = _config_path(ctx)
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        _write_config(ctx, dict(DEFAULT_CONFIG))

    cfg = _read_config(ctx)
    assert cfg["enabled"] is True

    # No existing job
    for j in cron.list_jobs(include_disabled=True):
        assert j.name != JOB_NAME

    # Create job
    prompt = _evolve_prompt(ctx)
    cron.add_job(
        name=JOB_NAME,
        schedule_kind="cron",
        schedule_config={"kind": "cron", "expr": cfg["cron_expr"]},
        payload={"kind": "agent_turn", "message": prompt, "deliver": False},
    )

    jobs = [j for j in cron.list_jobs() if j.name == JOB_NAME]
    assert len(jobs) == 1


def test_ensure_evolution_cron_idempotent(tmp_path: Path):
    """Calling _ensure_evolution_cron twice should not duplicate the job."""
    ker_root = tmp_path / ".ker"
    ker_root.mkdir(parents=True, exist_ok=True)

    cron = CronService(workspace=tmp_path, ker_root=ker_root, run_payload=dummy_run)
    cron.start()

    ctx = ToolContext(workspace=tmp_path, ker_root=ker_root, cron_service=cron)

    from ker.tools.tool_evolve import (
        DEFAULT_CONFIG,
        JOB_NAME,
        _config_path,
        _evolve_prompt,
        _write_config,
    )

    cfg_path = _config_path(ctx)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    _write_config(ctx, dict(DEFAULT_CONFIG))

    # Create job twice (simulating two gateway starts)
    for _ in range(2):
        existing = any(j.name == JOB_NAME for j in cron.list_jobs(include_disabled=True))
        if not existing:
            prompt = _evolve_prompt(ctx)
            cron.add_job(
                name=JOB_NAME,
                schedule_kind="cron",
                schedule_config={"kind": "cron", "expr": "0 3 * * *"},
                payload={"kind": "agent_turn", "message": prompt, "deliver": False},
            )

    jobs = [j for j in cron.list_jobs() if j.name == JOB_NAME]
    assert len(jobs) == 1
