from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ker.agent.context.session import sanitize_session_name

if TYPE_CHECKING:
    from ker.gateway.gateway import Gateway


def format_ts(ts: float) -> str:
    if ts <= 0:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def dispatch_command(gw: Gateway, text: str) -> bool:
    return _handle_exact(gw, text) or _handle_prefix(gw, text)


def _handle_exact(gw: Gateway, text: str) -> bool:
    handlers = {
        "/help": _cmd_help,
        "/agents": _cmd_agents,
        "/sessions": _cmd_sessions,
        "/context": _cmd_context,
        "/compact": _cmd_compact,
        "/prompt": _cmd_prompt,
        "/skills": _cmd_skills,
        "/heartbeat": _cmd_heartbeat,
        "/trigger": _cmd_trigger,
        "/cron": _cmd_cron,
        "/longtask": _cmd_longtask,
    }
    handler = handlers.get(text)
    if handler is None:
        return False
    handler(gw, text)
    return True


def _handle_prefix(gw: Gateway, text: str) -> bool:
    prefixes = [
        ("/switch-agent ", _cmd_switch_agent),
        ("/new ", _cmd_new),
        ("/switch ", _cmd_switch),
        ("/rename ", _cmd_rename),
        ("/search ", _cmd_search),
        ("/cron-run ", _cmd_cron_run),
        ("/longtask ", _cmd_longtask_detail),
    ]
    for prefix, handler in prefixes:
        if text.startswith(prefix):
            handler(gw, text)
            return True
    return False


def _cmd_help(gw: Gateway, text: str) -> None:
    print("Commands:")
    print("  /help /exit")
    print("  /agents /switch-agent <name|off>")
    print("  /sessions /new <name> /switch <name> /rename <name> /context /compact")
    print("  /prompt /skills /search <query>")
    print("  /heartbeat /trigger /cron /cron-run <job_id>")
    print("  /longtask [task_id]")


def _cmd_agents(gw: Gateway, text: str) -> None:
    for name in gw.agents:
        marker = " (active)" if name == (gw.force_agent or "ker") else ""
        print(f"- {name}{marker}")


def _cmd_switch_agent(gw: Gateway, text: str) -> None:
    name = text.split(maxsplit=1)[1].strip()
    gw.force_agent = None if name == "off" else name
    print(f"force_agent={gw.force_agent}")


def _cmd_sessions(gw: Gateway, text: str) -> None:
    print(f"current={gw.current_session}")


def _cmd_new(gw: Gateway, text: str) -> None:
    raw = text.split(maxsplit=1)[1].strip()
    clean = sanitize_session_name(raw)
    if clean != raw:
        print(f"warning: session name sanitized: '{raw}' -> '{clean}'")
    gw.current_session = clean
    print(f"session={gw.current_session}")


def _cmd_switch(gw: Gateway, text: str) -> None:
    raw = text.split(maxsplit=1)[1].strip()
    clean = sanitize_session_name(raw)
    if clean != raw:
        print(f"warning: session name sanitized: '{raw}' -> '{clean}'")
    gw.current_session = clean
    print(f"session={gw.current_session}")


def _cmd_rename(gw: Gateway, text: str) -> None:
    raw = text.split(maxsplit=1)[1].strip()
    new_name = sanitize_session_name(raw)
    if new_name != raw:
        print(f"warning: session name sanitized: '{raw}' -> '{new_name}'")
    old_name = gw.current_session
    if old_name == new_name:
        print(f"session already named '{new_name}'")
        return
    # Rename session files for the current agent
    agent_name = gw.force_agent or "ker"
    session_dir = gw.settings.ker_root / "agents" / agent_name / "session"
    if session_dir.exists():
        for f in session_dir.iterdir():
            if f.stem.endswith(f"_{old_name}"):
                new_stem = f.stem[: -len(old_name)] + new_name
                f.rename(session_dir / (new_stem + f.suffix))
    gw.current_session = new_name
    print(f"session renamed: {old_name} -> {new_name}")


def _cmd_context(gw: Gateway, text: str) -> None:
    agent_name = gw.force_agent or "ker"
    session_id = f"cli_cli-user_{gw.current_session}"
    messages = gw.session_store.load_messages(agent_name, session_id)
    used = max(1, len(str(messages)) // 4)
    cap = 180_000
    pct = min(100.0, (used / cap) * 100)
    print(f"Context usage: ~{used} / {cap} tokens ({pct:.2f}%)")


def _cmd_compact(gw: Gateway, text: str) -> None:
    agent_name = gw.force_agent or "ker"
    session_id = f"cli_cli-user_{gw.current_session}"
    messages = gw.session_store.load_messages(agent_name, session_id)
    compacted = gw.context_guard.compact_history(messages)
    gw.session_store.replace_messages(agent_name, session_id, compacted)
    print(f"Compacted session, removed {len(messages) - len(compacted)} message entries")


def _cmd_prompt(gw: Gateway, text: str) -> None:
    agent_name = gw.force_agent or "ker"
    prompt = gw.prompt_builder.build(agent_name=agent_name, model_id=gw.settings.model_id, channel="cli")
    print(prompt)


def _cmd_skills(gw: Gateway, text: str) -> None:
    agent_name = gw.force_agent or "ker"
    print(gw.skills_manager.render_skills_summary_xml(agent_name=agent_name) or "No skills found")


def _cmd_search(gw: Gateway, text: str) -> None:
    query = text.split(maxsplit=1)[1].strip()
    hits = gw.memory_store.search_memory(query, top_k=5)
    for hit in hits:
        print(f"- {hit.path} score={hit.score:.3f} {hit.snippet}")
    if not hits:
        print("No memory hits")


def _cmd_heartbeat(gw: Gateway, text: str) -> None:
    st = gw.heartbeat.status()
    print(f"enabled={st.enabled} running={st.running} last={format_ts(st.last_run_at)} interval={st.interval}s")


def _cmd_trigger(gw: Gateway, text: str) -> None:
    gw.heartbeat.trigger()
    print("heartbeat queued")


def _cmd_cron(gw: Gateway, text: str) -> None:
    gw.cron.load_jobs()
    jobs = gw.cron.list_jobs(include_disabled=True)
    if not jobs:
        print("no jobs")
    for job in jobs:
        print(f"- {job.id} enabled={job.enabled} next={format_ts(job.next_run_at)} errors={job.consecutive_errors}")


def _cmd_cron_run(gw: Gateway, text: str) -> None:
    job_id = text.split(maxsplit=1)[1].strip()
    gw.cron.load_jobs()
    gw.cron.run_now(job_id)
    print(f"queued job {job_id}")


def _cmd_longtask(gw: Gateway, text: str) -> None:
    tasks = gw.longtask_board.list_tasks()
    if not tasks:
        print("no long tasks")
        return
    for t in tasks:
        done = sum(1 for s in t.subtasks if s.status == "done")
        total = len(t.subtasks)
        active = "active" if gw.longtask_orchestrator.is_task_active(t.id) else "idle"
        print(f"- {t.id}  {t.status:<10} {done}/{total} done  [{active}]  {t.title}")


def _cmd_longtask_detail(gw: Gateway, text: str) -> None:
    task_id = text.split(maxsplit=1)[1].strip()
    task = gw.longtask_board.get_task(task_id)
    if task is None:
        print(f"task {task_id} not found")
        return
    active_workers = gw.longtask_workers.get_active_workers(task_id)
    print(f"Task: {task.title} ({task.id})")
    print(f"Status: {task.status}  Workers: {len(active_workers)}/{task.max_workers}  Agent: {task.worker_agent}")
    print(f"Created: {format_ts(task.created_at)}  Updated: {format_ts(task.updated_at)}")
    print()
    for st in task.subtasks:
        blocked = f" blocked_by={st.blocked_by}" if st.blocked_by else ""
        owner = f" [{st.owner}]" if st.owner else ""
        print(f"  {st.id}  {st.status:<8}{owner}{blocked}  {st.subject}")
