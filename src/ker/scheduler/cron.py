from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

from ker.logger import get_logger

log = get_logger("cron")


@dataclass
class CronJob:
    id: str
    name: str
    enabled: bool
    schedule_kind: str
    schedule_config: dict
    payload: dict
    consecutive_errors: int = 0
    next_run_at: float = 0.0
    last_run_at: float = 0.0
    last_error: str = ""
    delete_after_run: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class CronService:
    def __init__(
        self,
        workspace: Path,
        ker_root: Path,
        run_payload: Callable[[dict], Awaitable[str]],
    ) -> None:
        self.workspace = workspace
        self.ker_root = ker_root
        self.run_payload = run_payload
        self.enabled = False
        self.jobs: dict[str, CronJob] = {}

    @property
    def cron_path(self) -> Path:
        return self.workspace / "CRON.json"

    @property
    def store_path(self) -> Path:
        return self.ker_root / "cron" / "jobs.json"

    @property
    def log_path(self) -> Path:
        return self.ker_root / "cron" / "job_log.json"

    def load_jobs(self) -> None:
        self.jobs.clear()

        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            for item in data.get("jobs", []):
                job = CronJob(
                    id=item["id"],
                    name=item.get("name", item["id"]),
                    enabled=bool(item.get("enabled", True)),
                    schedule_kind=item.get("schedule_kind", "every"),
                    schedule_config=item.get("schedule_config", {}),
                    payload=item.get("payload", {}),
                    consecutive_errors=int(item.get("consecutive_errors", 0)),
                    next_run_at=float(item.get("next_run_at", 0.0)),
                    last_run_at=float(item.get("last_run_at", 0.0)),
                    last_error=str(item.get("last_error", "")),
                    delete_after_run=bool(item.get("delete_after_run", False)),
                    created_at=float(item.get("created_at", time.time())),
                    updated_at=float(item.get("updated_at", time.time())),
                )
                self.jobs[job.id] = job
            return

        if self.cron_path.exists():
            try:
                data = json.loads(self.cron_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            for item in data.get("jobs", []):
                sched = item.get("schedule", {})
                job = CronJob(
                    id=item["id"],
                    name=item.get("name", item["id"]),
                    enabled=bool(item.get("enabled", True)),
                    schedule_kind=sched.get("kind", "every"),
                    schedule_config=sched,
                    payload=item.get("payload", {}),
                    delete_after_run=bool(item.get("delete_after_run", False)),
                )
                job.next_run_at = self._compute_next(job, time.time())
                self.jobs[job.id] = job
            self._save_jobs()

    def _save_jobs(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        serial = {
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule_kind": j.schedule_kind,
                    "schedule_config": j.schedule_config,
                    "payload": j.payload,
                    "consecutive_errors": j.consecutive_errors,
                    "next_run_at": j.next_run_at,
                    "last_run_at": j.last_run_at,
                    "last_error": j.last_error,
                    "delete_after_run": j.delete_after_run,
                    "created_at": j.created_at,
                    "updated_at": j.updated_at,
                }
                for j in self.jobs.values()
            ]
        }
        self.store_path.write_text(json.dumps(serial, ensure_ascii=False, indent=2), encoding="utf-8")

    def start(self) -> None:
        self.enabled = True
        self.load_jobs()

    def stop(self) -> None:
        self.enabled = False

    def list_jobs(self, include_disabled: bool = True) -> list[CronJob]:
        jobs = list(self.jobs.values())
        if not include_disabled:
            jobs = [j for j in jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.next_run_at or float("inf"))

    def add_job(
        self,
        name: str,
        schedule_kind: str,
        schedule_config: dict,
        payload: dict,
        delete_after_run: bool = False,
    ) -> CronJob:
        now = time.time()
        job = CronJob(
            id=uuid.uuid4().hex[:8],
            name=name,
            enabled=True,
            schedule_kind=schedule_kind,
            schedule_config=dict(schedule_config),
            payload=dict(payload),
            delete_after_run=delete_after_run,
            created_at=now,
            updated_at=now,
        )
        job.next_run_at = self._compute_next(job, now)
        self.jobs[job.id] = job
        self._save_jobs()
        return job

    def remove_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        del self.jobs[job_id]
        self._save_jobs()
        return True

    def run_now(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Unknown cron job: {job_id}")
        asyncio.create_task(self._execute_job(job))

    async def tick(self) -> None:
        if not self.enabled:
            return
        now = time.time()
        for job in list(self.jobs.values()):
            if not job.enabled:
                continue
            if job.next_run_at <= 0:
                continue
            if now >= job.next_run_at:
                asyncio.create_task(self._execute_job(job))
                if job.schedule_kind == "at":
                    if job.delete_after_run:
                        self.jobs.pop(job.id, None)
                    else:
                        job.enabled = False
                        job.next_run_at = 0.0
                else:
                    job.next_run_at = self._compute_next(job, now)
        self._save_jobs()

    async def _execute_job(self, job: CronJob) -> None:
        status = "ok"
        err = ""
        try:
            await self.run_payload(job.payload)
            job.consecutive_errors = 0
        except Exception as exc:
            status = "error"
            err = str(exc)
            job.consecutive_errors += 1
            if job.consecutive_errors >= 5:
                job.enabled = False
            log.error("Cron job %s failed: %s", job.id, exc)
        job.last_run_at = time.time()
        job.last_error = err
        job.updated_at = time.time()
        self._log_run(job.id, status, err)
        self._save_jobs()

    def _log_run(self, job_id: str, status: str, error: str) -> None:
        p = self.ker_root / "cron" / "job_log.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"ts": time.time(), "job_id": job_id, "status": status, "error": error}, ensure_ascii=False)
                + "\n"
            )

    def _compute_next(self, job: CronJob, now: float) -> float:
        cfg = job.schedule_config
        kind = job.schedule_kind
        if kind == "at":
            at = cfg.get("at")
            if isinstance(at, str):
                dt = datetime.fromisoformat(at)
                ts = dt.timestamp()
            else:
                ts = float(cfg.get("at_ts", 0.0))
            return ts if ts > now else 0.0
        if kind == "every":
            every = int(cfg.get("every_seconds", 3600))
            if every <= 0:
                return 0.0
            anchor = int(cfg.get("anchor", 0))
            if now <= anchor:
                return float(anchor)
            steps = int((now - anchor) / every) + 1
            return float(anchor + steps * every)
        if kind == "cron":
            expr = cfg.get("expr", "0 * * * *")
            tz_str = cfg.get("tz")
            tz = ZoneInfo(tz_str) if tz_str else None
            base_dt = datetime.fromtimestamp(now, tz=tz)
            return croniter(expr, base_dt).get_next(datetime).timestamp()
        return now + 3600
