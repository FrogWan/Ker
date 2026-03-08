from __future__ import annotations

import time

from ker.tools.tool_base import ToolContext


def cron(
    ctx: ToolContext,
    action: str,
    message: str = "",
    every_seconds: int | None = None,
    cron_expr: str | None = None,
    at: str | None = None,
    job_id: str | None = None,
    tz: str | None = None,
) -> str:
    if ctx.cron_service is None:
        return "Error: cron service not configured"
    if action == "list":
        jobs = ctx.cron_service.list_jobs(include_disabled=True)
        if not jobs:
            return "No scheduled jobs."
        return "Scheduled jobs:\n" + "\n".join([f"- {j.name} (id: {j.id}, {j.schedule_kind})" for j in jobs])
    if action == "remove":
        if not job_id:
            return "Error: job_id is required for remove"
        return f"Removed job {job_id}" if ctx.cron_service.remove_job(job_id) else f"Job {job_id} not found"
    if action == "add":
        if not message:
            return "Error: message is required for add"
        payload = {
            "kind": "agent_turn",
            "message": message,
            "deliver": True,
            "channel": ctx.current_channel,
            "to": ctx.current_user,
        }
        if every_seconds:
            job = ctx.cron_service.add_job(
                name=message[:30],
                schedule_kind="every",
                schedule_config={"kind": "every", "every_seconds": every_seconds, "anchor": int(time.time())},
                payload=payload,
            )
            return f"Created job '{job.name}' (id: {job.id})"
        if cron_expr:
            sched_cfg: dict = {"kind": "cron", "expr": cron_expr}
            if tz:
                sched_cfg["tz"] = tz
            job = ctx.cron_service.add_job(
                name=message[:30],
                schedule_kind="cron",
                schedule_config=sched_cfg,
                payload=payload,
            )
            return f"Created job '{job.name}' (id: {job.id})"
        if at:
            job = ctx.cron_service.add_job(
                name=message[:30],
                schedule_kind="at",
                schedule_config={"kind": "at", "at": at},
                payload=payload,
                delete_after_run=True,
            )
            return f"Created job '{job.name}' (id: {job.id})"
        return "Error: either every_seconds, cron_expr, or at is required"
    return f"Unknown action: {action}"
