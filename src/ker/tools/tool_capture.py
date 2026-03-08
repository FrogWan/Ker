from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from ker.tools.tool_base import ToolContext
from ker.logger import get_logger

log = get_logger("capture")

_POLL_INTERVAL = 1.0


def capture_agent_conversation(
    ctx: ToolContext,
    agent: str,
    working_dir: str,
    label: str | None = None,
    timeout_seconds: int = 3600,
    store_to_memory: bool = True,
) -> str:
    from ker.capture import find_agent_session_files, parse_session

    capture_id = uuid.uuid4().hex[:8]
    display = label or f"{agent}:{Path(working_dir).name}"
    existing = set(find_agent_session_files(agent, working_dir))

    log.info("Capture %s started for %s in %s", capture_id, agent, working_dir)

    t = threading.Thread(
        target=_capture_worker,
        args=(ctx, capture_id, agent, working_dir, existing, label, timeout_seconds, store_to_memory),
        daemon=True,
        name=f"capture-{capture_id}",
    )
    t.start()

    return (
        f"Conversation capture [{display}] started (id: {capture_id}). "
        f"Watching for new {agent} session in '{working_dir}'. "
        f"Timeout: {timeout_seconds}s."
    )


def _capture_worker(
    ctx: ToolContext,
    capture_id: str,
    agent: str,
    working_dir: str,
    existing: set[Path],
    label: str | None,
    timeout_seconds: int,
    store_to_memory: bool,
) -> None:
    from ker.capture import find_agent_session_files, parse_session

    deadline = time.time() + timeout_seconds
    tried: set[Path] = set()

    while time.time() < deadline:
        current = set(find_agent_session_files(agent, working_dir))
        candidates = sorted(current - existing - tried, key=lambda p: p.stat().st_mtime)

        for new_file in candidates:
            tried.add(new_file)
            file_deadline = min(deadline, time.time() + 30)
            if not _wait_stable(new_file, stable_seconds=3, deadline=file_deadline):
                continue

            parsed = parse_session(agent, new_file, working_dir=working_dir)
            if parsed is None:
                continue

            _store(ctx, capture_id, parsed, label, agent, working_dir, new_file, store_to_memory)
            return

        time.sleep(_POLL_INTERVAL)

    log.warning("Capture %s timed out", capture_id)


def _wait_stable(path: Path, stable_seconds: float, deadline: float) -> bool:
    last_size = -1
    stable_since: float | None = None
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            time.sleep(_POLL_INTERVAL)
            continue
        if size != last_size:
            last_size = size
            stable_since = time.time()
        elif stable_since is not None and (time.time() - stable_since) >= stable_seconds:
            return True
        time.sleep(_POLL_INTERVAL)
    return False


def _store(
    ctx: ToolContext,
    capture_id: str,
    parsed: dict,
    label: str | None,
    agent: str,
    working_dir: str,
    session_file: Path,
    store_to_memory: bool,
) -> None:
    out_dir = ctx.ker_root / "memory" / "agent_conversations"
    out_dir.mkdir(parents=True, exist_ok=True)

    session_id = parsed.get("session_id", capture_id)
    out_path = out_dir / f"{session_id}.jsonl"

    rows: list[dict] = []
    for msg in parsed.get("messages", []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "user":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                rows.append({"type": "user", "content": content, "ts": time.time()})
        elif role == "assistant":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                rows.append({"type": "assistant", "content": [{"type": "text", "text": content}], "ts": time.time()})

    if rows:
        out_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        log.info("Capture %s stored %d rows to %s", capture_id, len(rows), out_path)

    if store_to_memory and ctx.memory_store is not None:
        msgs = len(parsed.get("messages", []))
        model = parsed.get("model") or "unknown"
        project = Path(working_dir).name
        ctx.memory_store.add_daily(
            f"[agent_conversation] capture_id={capture_id} label={label!r} "
            f"agent={agent} project={project} model={model} "
            f"messages={msgs} session_id={session_id}"
        )
