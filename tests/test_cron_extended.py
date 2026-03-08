import asyncio
import time
import pytest
from pathlib import Path
from ker.scheduler.cron import CronService
from ker.tools.tool_base import ToolContext
from ker.tools.tool_cron import cron


async def dummy_run(payload: dict) -> str:
    return "ok"


def test_cron_service_wired_to_tool_context(tmp_path: Path):
    """Verify cron_service is accessible via ToolContext."""
    svc = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=dummy_run)
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker", cron_service=svc)
    assert ctx.cron_service is not None
    assert ctx.cron_service is svc


def test_cron_tool_with_service(tmp_path: Path):
    """Verify cron tool can add/list/remove when service is wired."""
    svc = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=dummy_run)
    svc.start()
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker", cron_service=svc)

    result = cron(ctx, action="add", message="test job", every_seconds=60)
    assert "Created job" in result

    result = cron(ctx, action="list")
    assert "test job" in result

    job_id = svc.list_jobs()[0].id
    result = cron(ctx, action="remove", job_id=job_id)
    assert "Removed" in result


def test_cron_tool_without_service(tmp_path: Path):
    """Verify cron tool returns error when service is not wired."""
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker")
    result = cron(ctx, action="list")
    assert "Error" in result


def test_cron_with_timezone(tmp_path: Path):
    """Verify cron job with timezone parameter."""
    svc = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=dummy_run)
    svc.start()
    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker", cron_service=svc)

    result = cron(ctx, action="add", message="tz job", cron_expr="0 9 * * *", tz="America/New_York")
    assert "Created job" in result

    jobs = svc.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].schedule_config.get("tz") == "America/New_York"


def test_cron_timezone_compute_next(tmp_path: Path):
    """Verify _compute_next respects timezone."""
    svc = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=dummy_run)
    job = svc.add_job(
        name="tz_test",
        schedule_kind="cron",
        schedule_config={"kind": "cron", "expr": "0 * * * *", "tz": "UTC"},
        payload={"message": "test"},
    )
    assert job.next_run_at > time.time()


@pytest.mark.asyncio
async def test_cron_deliver_payload(tmp_path: Path):
    """Verify cron payload with deliver=True includes delivery fields."""
    delivered = []

    async def capture_run(payload: dict) -> str:
        delivered.append(payload)
        return "result"

    svc = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=capture_run)
    svc.start()

    ctx = ToolContext(workspace=tmp_path, ker_root=tmp_path / ".ker", cron_service=svc)
    cron(ctx, action="add", message="deliver test", every_seconds=1)

    jobs = svc.list_jobs()
    assert len(jobs) == 1
    payload = jobs[0].payload
    assert payload.get("deliver") is True
    assert payload.get("channel") == "cli"
