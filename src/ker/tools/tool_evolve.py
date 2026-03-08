from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from ker.tools.tool_base import ToolContext

EVOLUTION_DIR = "memory/evolution"
CONFIG_FILE = "config.json"
LOG_FILE = "log.jsonl"
JOB_NAME = "self-evolve"

DEFAULT_CONFIG = {
    "enabled": True,
    "cron_expr": "0 3 * * *",
    "job_name": JOB_NAME,
}


def _evo_dir(ctx: ToolContext) -> Path:
    return ctx.ker_root / EVOLUTION_DIR


def _config_path(ctx: ToolContext) -> Path:
    return _evo_dir(ctx) / CONFIG_FILE


def _log_path(ctx: ToolContext) -> Path:
    return _evo_dir(ctx) / LOG_FILE


def _read_config(ctx: ToolContext) -> dict:
    p = _config_path(ctx)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def _write_config(ctx: ToolContext, cfg: dict) -> None:
    p = _config_path(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_log(ctx: ToolContext, limit: int = 10) -> list[dict]:
    p = _log_path(ctx)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries[-limit:]


def _evolve_prompt(ctx: ToolContext) -> str:
    template_path = Path(__file__).resolve().parents[1] / "memory" / "templates" / "EVOLVE.md"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return "Run a self-evolution cycle: read error logs and memory, find one improvement, edit AGENT.md or MEMORY.md, and log the result to .ker/memory/evolution/log.jsonl."


def _status(ctx: ToolContext) -> str:
    cfg = _read_config(ctx)
    entries = _read_log(ctx)

    # Check if cron job exists
    job_exists = False
    if ctx.cron_service is not None:
        for j in ctx.cron_service.list_jobs(include_disabled=True):
            if j.name == JOB_NAME:
                job_exists = True
                break

    lines = [
        "## Self-Evolution Status",
        f"- Enabled: {cfg.get('enabled', True)}",
        f"- Schedule: {cfg.get('cron_expr', '0 3 * * *')}",
        f"- Cron job registered: {job_exists}",
        f"- Total cycles: {len(entries)}",
    ]

    if entries:
        last = entries[-1]
        lines.append(f"- Last run: {last.get('date', 'unknown')}")
        lines.append(f"  - Action: {last.get('action', 'unknown')}")
        lines.append(f"  - Axis: {last.get('axis', 'unknown')}")
        changed = last.get("changed")
        lines.append(f"  - Changed: {changed or 'none (skipped)'}")
    else:
        lines.append("- No evolution cycles have run yet.")

    return "\n".join(lines)


def _history(ctx: ToolContext, limit: int = 10) -> str:
    entries = _read_log(ctx, limit=limit)
    if not entries:
        return "No evolution history yet."

    lines = [f"## Evolution History (last {len(entries)} entries)"]
    for e in entries:
        changed = e.get("changed") or "none"
        lines.append(
            f"- **{e.get('date', '?')}** [{e.get('axis', '?')}] "
            f"changed={changed} — {e.get('action', '?')}"
        )
    return "\n".join(lines)


def _trigger(ctx: ToolContext) -> str:
    if ctx.subagent_manager is None:
        return "Error: subagent manager not configured — cannot trigger evolution cycle."

    prompt = _evolve_prompt(ctx)
    loop = asyncio.get_event_loop()
    future = asyncio.run_coroutine_threadsafe(
        ctx.subagent_manager.spawn(
            task=prompt,
            label="self-evolve",
            channel=ctx.current_channel,
            user=ctx.current_user,
            session_key=f"{ctx.agent_name}_{ctx.session_name}",
        ),
        loop,
    )
    return future.result(timeout=5)


def _config(ctx: ToolContext, cron_expr: str | None = None, enabled: bool | None = None) -> str:
    cfg = _read_config(ctx)

    if cron_expr is None and enabled is None:
        return f"Current evolution config:\n```json\n{json.dumps(cfg, indent=2)}\n```"

    if cron_expr is not None:
        cfg["cron_expr"] = cron_expr
    if enabled is not None:
        cfg["enabled"] = enabled

    _write_config(ctx, cfg)

    # Update cron job to match new config
    if ctx.cron_service is not None:
        # Remove existing job
        for j in ctx.cron_service.list_jobs(include_disabled=True):
            if j.name == JOB_NAME:
                ctx.cron_service.remove_job(j.id)
                break

        # Re-create if enabled
        if cfg.get("enabled", True):
            prompt = _evolve_prompt(ctx)
            ctx.cron_service.add_job(
                name=JOB_NAME,
                schedule_kind="cron",
                schedule_config={"kind": "cron", "expr": cfg["cron_expr"]},
                payload={
                    "kind": "agent_turn",
                    "message": prompt,
                    "deliver": False,
                },
            )

    return f"Evolution config updated:\n```json\n{json.dumps(cfg, indent=2)}\n```"


def self_evolve(
    ctx: ToolContext,
    action: str,
    limit: int = 10,
    cron_expr: str | None = None,
    enabled: bool | None = None,
) -> str:
    if action == "status":
        return _status(ctx)
    if action == "history":
        return _history(ctx, limit=limit)
    if action == "trigger":
        return _trigger(ctx)
    if action == "config":
        return _config(ctx, cron_expr=cron_expr, enabled=enabled)
    return f"Unknown action: {action}. Valid actions: status, history, trigger, config."
