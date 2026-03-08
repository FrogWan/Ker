from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class _NoOpAnonymizer:
    """No-op replacement for the removed Anonymizer class."""
    def path(self, p: str) -> str:
        return p
    def text(self, t: str) -> str:
        return t

Anonymizer = _NoOpAnonymizer


def _redact_text(text: str) -> tuple[str, int]:
    return text, 0

_CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
_CODEX_ARCHIVED_DIR = Path.home() / ".codex" / "archived_sessions"
_UNKNOWN_CWD = "<unknown-cwd>"


def parse_session(
    filepath: Path,
    target_cwd: str,
    anonymizer: object | None = None,
) -> dict | None:
    if anonymizer is None:
        anonymizer = _NoOpAnonymizer()

    try:
        entries = list(_iter_jsonl(filepath))
    except OSError:
        return None

    state = _ParseState(
        metadata={
            "session_id": filepath.stem,
            "cwd": None,
            "git_branch": None,
            "model": None,
            "model_provider": None,
            "start_time": None,
            "end_time": None,
        }
    )
    state.tool_result_map = _build_tool_result_map(entries, anonymizer)

    ts: str | None = None
    for entry in entries:
        ts = _normalize_ts(entry.get("timestamp"))
        etype = entry.get("type")

        if etype == "session_meta":
            _handle_session_meta(state, entry, anonymizer)
        elif etype == "turn_context":
            _handle_turn_context(state, entry, anonymizer)
        elif etype == "response_item":
            _handle_response_item(state, entry, anonymizer)
        elif etype == "event_msg":
            payload = entry.get("payload", {})
            etype2 = payload.get("type")
            if etype2 == "token_count":
                _handle_token_count(state, payload)
            elif etype2 == "agent_reasoning":
                _handle_agent_reasoning(state, payload, anonymizer)
            elif etype2 == "user_message":
                _handle_user_message(state, payload, ts, anonymizer)
            elif etype2 == "agent_message":
                _handle_agent_message(state, payload, ts, anonymizer)

    state.stats["input_tokens"] = state.max_input_tokens
    state.stats["output_tokens"] = state.max_output_tokens

    session_norm = _normalize_cwd(state.raw_cwd)
    target_norm = _normalize_cwd(target_cwd)
    if session_norm != target_norm:
        _log_codex_mismatch(
            filepath,
            target_cwd=target_cwd,
            target_norm=target_norm,
            session_cwd=state.raw_cwd,
            session_norm=session_norm,
            reason="cwd_mismatch",
        )
        return None

    _flush_pending(state, ts)

    if state.metadata["model"] is None:
        provider = state.metadata.get("model_provider")
        state.metadata["model"] = (
            f"{provider}-codex" if isinstance(provider, str) and provider.strip()
            else "codex-unknown"
        )

    if not state.messages:
        return None

    return _make_result(state.metadata, state.messages, state.stats)


def session_files() -> list[Path]:
    files: list[Path] = []
    if _CODEX_SESSIONS_DIR.exists():
        files.extend(sorted(_CODEX_SESSIONS_DIR.rglob("*.jsonl")))
    if _CODEX_ARCHIVED_DIR.exists():
        files.extend(sorted(_CODEX_ARCHIVED_DIR.glob("*.jsonl")))
    return files


@dataclasses.dataclass
class _ParseState:
    metadata: dict[str, Any]
    messages: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    stats: dict[str, int] = dataclasses.field(default_factory=lambda: {
        "user_messages": 0,
        "assistant_messages": 0,
        "tool_uses": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    })
    pending_tool_uses: list[dict] = dataclasses.field(default_factory=list)
    pending_thinking: list[str] = dataclasses.field(default_factory=list)
    _seen_thinking: set[str] = dataclasses.field(default_factory=set)
    raw_cwd: str = _UNKNOWN_CWD
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    tool_result_map: dict[str, dict] = dataclasses.field(default_factory=dict)


def _handle_session_meta(state: _ParseState, entry: dict, anonymizer: Anonymizer) -> None:
    payload = entry.get("payload", {})
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        state.raw_cwd = cwd
        if state.metadata["cwd"] is None:
            state.metadata["cwd"] = anonymizer.path(cwd)
    if state.metadata["model_provider"] is None:
        state.metadata["model_provider"] = payload.get("model_provider")
    git = payload.get("git", {})
    if isinstance(git, dict) and state.metadata["git_branch"] is None:
        state.metadata["git_branch"] = git.get("branch")
    sid = payload.get("id")
    if sid:
        state.metadata["session_id"] = sid


def _handle_turn_context(state: _ParseState, entry: dict, anonymizer: Anonymizer) -> None:
    payload = entry.get("payload", {})
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        state.raw_cwd = cwd
        if state.metadata["cwd"] is None:
            state.metadata["cwd"] = anonymizer.path(cwd)
    if state.metadata["model"] is None:
        model = payload.get("model")
        if isinstance(model, str) and model.strip():
            state.metadata["model"] = model


def _handle_response_item(state: _ParseState, entry: dict, anonymizer: Anonymizer) -> None:
    payload = entry.get("payload", {})
    itype = payload.get("type")

    if itype == "function_call":
        args = _parse_args(payload.get("arguments"))
        state.pending_tool_uses.append({
            "tool": payload.get("name"),
            "input": _parse_tool_input(payload.get("name"), args, anonymizer),
            "tool_use_id": payload.get("call_id"),
            "_call_id": payload.get("call_id"),
        })

    elif itype == "custom_tool_call":
        raw_input = payload.get("input", "")
        if isinstance(raw_input, str):
            inp = {"patch": anonymizer.text(raw_input)}
        elif isinstance(raw_input, dict):
            inp = _parse_tool_input(payload.get("name"), raw_input, anonymizer)
        else:
            inp = {"raw": anonymizer.text(str(raw_input))}
        state.pending_tool_uses.append({
            "tool": payload.get("name"),
            "input": inp,
            "tool_use_id": payload.get("call_id"),
            "_call_id": payload.get("call_id"),
        })

    elif itype == "reasoning":
        for summary in payload.get("summary", []):
            if not isinstance(summary, dict):
                continue
            text = anonymizer.text(summary.get("text", "").strip())
            if text and text not in state._seen_thinking:
                state._seen_thinking.add(text)
                state.pending_thinking.append(text)


def _handle_token_count(state: _ParseState, payload: dict) -> None:
    info = payload.get("info", {})
    if not isinstance(info, dict):
        return
    usage = info.get("total_token_usage", {})
    if not isinstance(usage, dict):
        return
    inp = _safe_int(usage.get("input_tokens")) + _safe_int(usage.get("cached_input_tokens"))
    out = _safe_int(usage.get("output_tokens"))
    state.max_input_tokens = max(state.max_input_tokens, inp)
    state.max_output_tokens = max(state.max_output_tokens, out)


def _handle_agent_reasoning(state: _ParseState, payload: dict, anonymizer: Anonymizer) -> None:
    text = anonymizer.text(payload.get("text", "").strip())
    if text and text not in state._seen_thinking:
        state._seen_thinking.add(text)
        state.pending_thinking.append(text)


def _handle_user_message(
    state: _ParseState, payload: dict, ts: str | None, anonymizer: Anonymizer
) -> None:
    _flush_pending(state, ts)
    content = payload.get("message")
    if isinstance(content, str) and content.strip():
        state.messages.append({
            "role": "user",
            "content": anonymizer.text(content.strip()),
            "timestamp": ts,
        })
        state.stats["user_messages"] += 1
        _update_time_bounds(state.metadata, ts)


def _handle_agent_message(
    state: _ParseState, payload: dict, ts: str | None, anonymizer: Anonymizer
) -> None:
    content = payload.get("message")
    msg: dict[str, Any] = {"role": "assistant"}
    if isinstance(content, str) and content.strip():
        msg["content"] = anonymizer.text(content.strip())
    if state.pending_thinking:
        msg["thinking"] = "\n\n".join(state.pending_thinking)
    if state.pending_tool_uses:
        msg["tool_uses"] = _resolve_tool_uses(state)

    if len(msg) > 1:
        msg["timestamp"] = ts
        state.messages.append(msg)
        state.stats["assistant_messages"] += 1
        state.stats["tool_uses"] += len(msg.get("tool_uses", []))
        _update_time_bounds(state.metadata, ts)

    state.pending_tool_uses.clear()
    state.pending_thinking.clear()
    state._seen_thinking.clear()


def _flush_pending(state: _ParseState, ts: str | None) -> None:
    if not state.pending_tool_uses and not state.pending_thinking:
        return
    msg: dict[str, Any] = {"role": "assistant", "timestamp": ts}
    if state.pending_thinking:
        msg["thinking"] = "\n\n".join(state.pending_thinking)
    if state.pending_tool_uses:
        msg["tool_uses"] = _resolve_tool_uses(state)
    state.messages.append(msg)
    state.stats["assistant_messages"] += 1
    state.stats["tool_uses"] += len(msg.get("tool_uses", []))
    _update_time_bounds(state.metadata, ts)
    state.pending_tool_uses.clear()
    state.pending_thinking.clear()
    state._seen_thinking.clear()


def _resolve_tool_uses(state: _ParseState) -> list[dict]:
    resolved = []
    for tu in state.pending_tool_uses:
        call_id = tu.pop("_call_id", None)
        if call_id and call_id in state.tool_result_map:
            r = state.tool_result_map[call_id]
            tu["output"] = r["output"]
            tu["status"] = r["status"]
            if r.get("timestamp"):
                tu["output_timestamp"] = r["timestamp"]
        resolved.append(tu)
    return resolved


def _build_tool_result_map(entries: list[dict], anonymizer: Anonymizer) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        p = entry.get("payload", {})
        ptype = p.get("type")
        call_id = p.get("call_id")
        if not call_id:
            continue

        if ptype == "function_call_output":
            raw = p.get("output", "")
            out: dict = {}
            output_lines: list[str] = []
            in_output = False
            for line in raw.splitlines():
                if line.startswith("Exit code: "):
                    try:
                        out["exit_code"] = int(line[len("Exit code: "):].strip())
                    except ValueError:
                        out["exit_code"] = line[len("Exit code: "):].strip()
                elif line.startswith("Wall time: "):
                    out["wall_time"] = line[len("Wall time: "):].strip()
                elif line == "Output:":
                    in_output = True
                elif in_output:
                    output_lines.append(line)
            if output_lines:
                out["output"] = anonymizer.text("\n".join(output_lines).strip())
            result[call_id] = {
                "output": out,
                "status": "success",
                "timestamp": _normalize_ts(entry.get("timestamp")),
            }

        elif ptype == "custom_tool_call_output":
            raw = p.get("output", "")
            out = {}
            try:
                parsed = json.loads(raw)
                text = parsed.get("output", "")
                if text:
                    out["output"] = anonymizer.text(str(text))
                meta = parsed.get("metadata", {})
                if "exit_code" in meta:
                    out["exit_code"] = meta["exit_code"]
                if "duration_seconds" in meta:
                    out["duration_seconds"] = meta["duration_seconds"]
            except (json.JSONDecodeError, AttributeError):
                if raw:
                    out["output"] = anonymizer.text(raw)
            result[call_id] = {
                "output": out,
                "status": "success",
                "timestamp": _normalize_ts(entry.get("timestamp")),
            }

    return result


def _parse_tool_input(tool_name: str | None, input_data: Any, anonymizer: Anonymizer) -> dict:
    if not isinstance(input_data, dict):
        return {"raw": anonymizer.text(str(input_data))}

    name = (tool_name or "").lower()

    if name == "exec_command":
        cmd, _ = _redact_text(input_data.get("cmd", ""))
        return {"cmd": anonymizer.text(cmd)}
    if name == "shell_command":
        cmd, _ = _redact_text(input_data.get("command", ""))
        return {
            "command": anonymizer.text(cmd),
            "workdir": anonymizer.path(input_data.get("workdir", "")),
        }
    if name == "write_stdin":
        return {
            "session_id": input_data.get("session_id"),
            "chars": anonymizer.text(input_data.get("chars", "")),
            "yield_time_ms": input_data.get("yield_time_ms"),
            "max_output_tokens": input_data.get("max_output_tokens"),
        }
    if name == "update_plan":
        plan = input_data.get("plan", [])
        return {
            "explanation": anonymizer.text(input_data.get("explanation", "")),
            "plan": [anonymizer.text(str(p)) if isinstance(p, str) else p for p in plan],
        }
    if name in ("read", "edit"):
        return {"file_path": anonymizer.path(input_data.get("file_path", ""))}
    if name == "write":
        return {
            "file_path": anonymizer.path(input_data.get("file_path", "")),
            "content": anonymizer.text(input_data.get("content", "")),
        }
    if name == "bash":
        cmd, _ = _redact_text(input_data.get("command", ""))
        return {"command": anonymizer.text(cmd)}

    return {k: anonymizer.text(str(v)) if isinstance(v, str) else v for k, v in input_data.items()}


def _iter_jsonl(filepath: Path):
    with filepath.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _parse_args(arguments: Any) -> Any:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    return arguments


def _normalize_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    return None


def _update_time_bounds(metadata: dict, ts: str | None) -> None:
    if ts is None:
        return
    if metadata["start_time"] is None:
        metadata["start_time"] = ts
    metadata["end_time"] = ts


def _safe_int(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _make_result(metadata: dict, messages: list, stats: dict) -> dict:
    return {
        "session_id": metadata["session_id"],
        "model": metadata["model"],
        "git_branch": metadata["git_branch"],
        "start_time": metadata["start_time"],
        "end_time": metadata["end_time"],
        "messages": messages,
        "stats": stats,
    }


def _normalize_cwd(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value == _UNKNOWN_CWD:
        return ""
    norm = os.path.normpath(value.strip())
    if not os.path.isabs(norm):
        norm = os.path.abspath(norm)
    norm = os.path.normcase(norm)
    return norm.rstrip("\\/")


def _log_codex_mismatch(
    filepath: Path,
    target_cwd: str,
    target_norm: str,
    session_cwd: str,
    session_norm: str,
    reason: str,
) -> None:
    try:
        from ker.logs import append_jsonl_log

        append_jsonl_log(
            state_root=Path.cwd() / ".ker",
            log_name="capture_events",
            record={
                "ts": datetime.now(tz=timezone.utc).timestamp(),
                "level": "warning",
                "source": "codex_parser",
                "event": "codex_session_skipped",
                "message": "Codex session skipped due to cwd mismatch",
                "context": {
                    "session_file": str(filepath),
                    "reason": reason,
                    "target_cwd": target_cwd,
                    "target_cwd_normalized": target_norm,
                    "session_cwd": session_cwd,
                    "session_cwd_normalized": session_norm,
                },
            },
        )
    except Exception:
        return
