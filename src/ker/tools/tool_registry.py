from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ker.tools.tool_base import ToolContext

TOOLS: list[dict[str, Any]] = [
    {"name": "exec", "description": "Execute a shell command with safety guard.", "input_schema": {"type": "object", "properties": {"command": {"type": "string", "minLength": 1}, "timeout": {"type": "integer", "minimum": 1, "maximum": 300}, "working_dir": {"type": "string"}}, "required": ["command"]}},
    {"name": "bash", "description": "Alias for exec.", "input_schema": {"type": "object", "properties": {"command": {"type": "string", "minLength": 1}, "timeout": {"type": "integer", "minimum": 1, "maximum": 300}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents from workspace.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file contents under workspace.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace old text with new text in a file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}, "old_text": {"type": "string", "minLength": 1}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "list_dir", "description": "List directory contents in workspace.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "minLength": 1}}, "required": ["path"]}},
    {"name": "skill", "description": "Manage and inspect skills. Actions: list, show, read, install.", "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "show", "read", "install"]}, "name": {"type": "string"}, "include_unavailable": {"type": "boolean"}, "content": {"type": "string", "description": "SKILL.md content for action=install"}}, "required": ["action"]}},
    {"name": "read_memory", "description": "Search short-term memory: recent conversations, daily logs, and session context. Long-term memory (MEMORY.md) is already in your system prompt — no need to search for it.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 20}, "source": {"type": "string", "enum": ["all", "session", "chat_history", "daily"], "description": "Filter which sources to search (default: all)"}}, "required": []}},
    {"name": "write_memory", "description": "Save an important fact to long-term memory. Use for user preferences, project facts, and patterns worth remembering across sessions.", "input_schema": {"type": "object", "properties": {"fact": {"type": "string", "minLength": 5}, "category": {"type": "string", "enum": ["user", "project", "preferences", "patterns", "general"]}, "action": {"type": "string", "enum": ["add", "remove"]}}, "required": ["fact"]}},
{"name": "web_search", "description": "Search the web via Brave API.", "input_schema": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1}, "count": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}},
    {"name": "web_fetch", "description": "Fetch URL and extract readable content.", "input_schema": {"type": "object", "properties": {"url": {"type": "string", "minLength": 1}, "extractMode": {"type": "string", "enum": ["markdown", "text"]}, "maxChars": {"type": "integer", "minimum": 100}}, "required": ["url"]}},
    {"name": "cron", "description": "Manage cron jobs (add/list/remove).", "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["add", "list", "remove"]}, "message": {"type": "string"}, "every_seconds": {"type": "integer", "minimum": 1}, "cron_expr": {"type": "string"}, "at": {"type": "string"}, "job_id": {"type": "string"}, "tz": {"type": "string", "description": "IANA timezone for cron expressions (e.g. America/New_York)"}}, "required": ["action"]}},
    {"name": "message", "description": "Send a direct message to channel peer (CLI sim).", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}, "channel": {"type": "string"}, "chat_id": {"type": "string"}}, "required": ["content"]}},
    {"name": "spawn", "description": "Spawn background subtask.", "input_schema": {"type": "object", "properties": {"task": {"type": "string"}, "label": {"type": "string"}}, "required": ["task"]}},
    {"name": "capture_agent_conversation", "description": "Start a background watcher that captures and records the conversation from an external coding agent session (claude or codex) once it finishes.", "input_schema": {"type": "object", "properties": {"agent": {"type": "string", "enum": ["claude", "codex"]}, "working_dir": {"type": "string"}, "label": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 7200}, "store_to_memory": {"type": "boolean"}}, "required": ["agent", "working_dir"]}},
    {"name": "self_evolve", "description": "Manage Ker's self-evolution: view status, review history, trigger manual cycle, configure schedule.", "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["status", "history", "trigger", "config"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "cron_expr": {"type": "string"}, "enabled": {"type": "boolean"}}, "required": ["action"]}},
    {"name": "long_task", "description": "Run a long-running coding task via Claude CLI with iterative review. Actions: start, status, cancel, list.", "input_schema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["start", "status", "cancel", "list"]}, "task_name": {"type": "string", "description": "Task identifier (used as folder name)"}, "workspace": {"type": "string", "description": "Absolute path to workspace folder. Required for start."}, "description": {"type": "string", "description": "Full task description. Required for start."}, "max_iterations": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["action"]}},
    {"name": "fallback", "description": "Delegate a request to Claude Code or Codex CLI. Runs in background and notifies user when done.", "input_schema": {"type": "object", "properties": {"request": {"type": "string", "minLength": 1}, "task_name": {"type": "string"}, "timeout": {"type": "integer", "minimum": 30, "maximum": 7200}, "prefer": {"type": "string", "enum": ["claude", "codex"]}}, "required": ["request"]}},
]


class ToolRegistry:
    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx
        self._handlers: dict[str, Callable[..., str]] = {}
        self._dynamic_schemas: dict[str, dict[str, Any]] = {}
        self._register_all()

    def _register_all(self) -> None:
        from ker.tools.tool_exec import exec_command, bash
        from ker.tools.tool_filesystem import read_file, write_file, edit_file, list_dir
        from ker.tools.tool_memory import read_memory, write_memory
        from ker.tools.tool_web import web_search, web_fetch
        from ker.tools.tool_cron import cron
        from ker.tools.tool_message import message
        from ker.tools.tool_spawn import spawn
        from ker.tools.tool_skill import skill
        from ker.tools.tool_capture import capture_agent_conversation
        from ker.tools.tool_evolve import self_evolve
        from ker.tools.tool_longtask import long_task
        from ker.tools.tool_fallback import fallback

        ctx = self.ctx
        self._handlers = {
            "exec": lambda command, timeout=60, working_dir=None: exec_command(ctx, command=command, timeout=timeout, working_dir=working_dir),
            "bash": lambda command, timeout=30: bash(ctx, command=command, timeout=timeout),
            "read_file": lambda path: read_file(ctx, path=path),
            "write_file": lambda path, content: write_file(ctx, path=path, content=content),
            "edit_file": lambda path, old_text, new_text: edit_file(ctx, path=path, old_text=old_text, new_text=new_text),
            "list_dir": lambda path: list_dir(ctx, path=path),
            "skill": lambda action, name="", include_unavailable=False, content="": skill(ctx, action=action, name=name, include_unavailable=include_unavailable, content=content),
            "read_memory": lambda query="", top_k=5, source="all": read_memory(ctx, query=query, top_k=top_k, source=source),
            "write_memory": lambda fact, category="general", action="add": write_memory(ctx, fact=fact, category=category, action=action),
            "web_search": lambda query, count=5: web_search(ctx, query=query, count=count),
            "web_fetch": lambda url, extractMode="markdown", maxChars=50000: web_fetch(ctx, url=url, extractMode=extractMode, maxChars=maxChars),
            "cron": lambda action, message="", every_seconds=None, cron_expr=None, at=None, job_id=None, tz=None: cron(ctx, action=action, message=message, every_seconds=every_seconds, cron_expr=cron_expr, at=at, job_id=job_id, tz=tz),
            "message": lambda content, channel=None, chat_id=None: message(ctx, content=content, channel=channel, chat_id=chat_id),
            "spawn": lambda task, label=None: spawn(ctx, task=task, label=label),
            "capture_agent_conversation": lambda agent, working_dir, label=None, timeout_seconds=3600, store_to_memory=True: capture_agent_conversation(ctx, agent=agent, working_dir=working_dir, label=label, timeout_seconds=timeout_seconds, store_to_memory=store_to_memory),
            "self_evolve": lambda action, limit=10, cron_expr=None, enabled=None: self_evolve(ctx, action=action, limit=limit, cron_expr=cron_expr, enabled=enabled),
            "long_task": lambda action, task_name=None, workspace=None, description=None, max_iterations=3: long_task(ctx, action=action, task_name=task_name, workspace=workspace, description=description, max_iterations=max_iterations),
            "fallback": lambda request, task_name=None, timeout=7200, prefer=None: fallback(ctx, request=request, task_name=task_name, timeout=timeout, prefer=prefer),
        }

    def register(self, name: str, schema: dict[str, Any], handler: Callable[..., Any]) -> None:
        """Register a tool at runtime (e.g. MCP tools)."""
        self._dynamic_schemas[name] = schema
        self._handlers[name] = handler

    def unregister(self, name: str) -> None:
        """Remove a dynamically registered tool."""
        self._dynamic_schemas.pop(name, None)
        self._handlers.pop(name, None)

    async def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        hint = "\n\n[Analyze the error above and try a different approach.]"
        handler = self._handlers.get(name)
        if handler is None:
            available = ", ".join(sorted(self._handlers.keys()))
            return f"Error: Unknown tool '{name}'. Available: {available}{hint}"
        try:
            result = handler(**tool_input)
            # Dynamic handlers (e.g. MCP) are async; static handlers are sync
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except TypeError as exc:
            return f"Error: Invalid arguments for {name}: {exc}{hint}"
        except Exception as exc:
            return f"Error: {name} failed: {exc}{hint}"

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return TOOLS + list(self._dynamic_schemas.values())
