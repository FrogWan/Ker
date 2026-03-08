# Ker Operational Instructions (Claude/Codex)

## Purpose

This document helps coding agents work safely and effectively in Ker.

## Read First

- Gateway (central orchestrator): `src/ker/gateway/gateway.py`
- Agent loop (async model+tool): `src/ker/agent/agent_loop.py`
- Tool registry + schemas: `src/ker/tools/tool_registry.py`
- Individual tools: `src/ker/tools/tool_*.py`
- Memory + error logs: `src/ker/agent/context/memory.py`
- Session store: `src/ker/agent/context/session.py`
- System prompt builder: `src/ker/agent/context/prompt_builder.py`
- Scheduler: `src/ker/scheduler/cron.py`
- LLM providers: `src/ker/llm/`
- Entry point: `src/ker/main.py`

## Architecture

- Async/await throughout (no threading except tool_exec subprocess calls)
- Gateway pattern: channels feed inbound queue, gateway routes to agent loop
- Agent discovery: `.ker/agents/` folders (each subfolder = one agent)
- Session paths: `.ker/agents/{name}/session/{channel}_{user}_{session}.jsonl`
- Chat history: `.ker/agents/{name}/chatHistory/chatHistory.jsonl`
- LLM abstracted via `LLMProvider` (Anthropic, Azure OpenAI, GitHub Copilot)

## Mandatory Workflow

1. Reproduce or inspect issue.
2. Read error history using `read_error_log` tool.
3. Read related context using `read_memory` tool.
4. Patch minimal code path.
5. Add/adjust tests.
6. Run tests before finishing.

## Memory and Error Logging

- Daily memory: `.ker/memory/daily/*.jsonl`
- Error log: `.ker/memory/ERROR_LOG.jsonl`
- Logs: `.ker/logs/yyyy-mm-dd.log`

Log all runtime exceptions with enough context for later self-healing.

## Feature Work

When adding new functionality:

- Add tool schema in `tool_registry.py` TOOLS list.
- Add handler in a `tool_*.py` file.
- Register handler in `ToolRegistry._register_all()`.
- Add tests and docs.

## Cron-driven Changes

Ker supports cron jobs via the `cron` tool.
You can schedule periodic engineering tasks by setting `action=add` with `every_seconds`, `cron_expr`, or `at`.

Always keep scheduled code tasks explicit and idempotent.
