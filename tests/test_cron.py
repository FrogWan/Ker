import asyncio
import pytest
from pathlib import Path
from ker.scheduler.cron import CronService


async def dummy_run(payload: dict) -> str:
    return "ok"


def test_cron_add_list_remove(tmp_path: Path):
    cron = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=dummy_run)
    cron.start()

    job = cron.add_job(
        name="test_job",
        schedule_kind="every",
        schedule_config={"kind": "every", "every_seconds": 60, "anchor": 0},
        payload={"message": "test"},
    )
    assert job.id
    assert len(cron.list_jobs()) == 1

    removed = cron.remove_job(job.id)
    assert removed
    assert len(cron.list_jobs()) == 0


def test_cron_persistence(tmp_path: Path):
    cron1 = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=dummy_run)
    cron1.start()
    cron1.add_job(
        name="persistent",
        schedule_kind="every",
        schedule_config={"kind": "every", "every_seconds": 120},
        payload={"message": "hello"},
    )

    cron2 = CronService(workspace=tmp_path, ker_root=tmp_path / ".ker", run_payload=dummy_run)
    cron2.load_jobs()
    assert len(cron2.list_jobs()) == 1
    assert cron2.list_jobs()[0].name == "persistent"
