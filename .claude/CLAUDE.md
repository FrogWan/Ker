# Ker Operational Instructions (Claude/Codex)

## Purpose

This document helps coding agents work safely and effectively in Ker.

## Environment Setup

To start the Ker agent gateway, you need:

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure `.env`

Create a `.env` file in the project root with one of the provider configs:

**GitHub Copilot (recommended):**
```env
LLM_PROVIDER=github_copilot
MODEL_ID=gpt-5.3-codex
```
Then run `uv run ker github_copilot login` to authenticate via OAuth device flow.

**Anthropic (Claude):**
```env
LLM_PROVIDER=anthropic
MODEL_ID=claude-opus-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

**Optional:** Add `KERWEB_API_KEY=...` to connect to the KerWeb frontend.

### 3. Start

```bash
uv run ker              # CLI mode (interactive terminal)
uv run ker gateway      # Gateway mode (KerWeb + cron + heartbeat)
```

Gateway mode auto-connects to KerWeb via WebSocket and enables all background services.

### Key defaults

| Setting | Default |
|---|---|
| `MODEL_ID` | `claude-opus-4-6` |
| `LLM_PROVIDER` | `anthropic` |
| `KERWEB_ENABLED` | `1` |
| `KERWEB_BASE_URL` | `https://kerweb-app.azurewebsites.net` |
| `CRON_ENABLED` | `1` |
| `HEARTBEAT_ENABLED` | `1` |

Settings load from: `.ker/config.json` → `.env` → defaults (see `src/ker/config.py`).

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
2. Read related context using `read_memory` tool.
3. Patch minimal code path.
4. Add/adjust tests.
5. Run tests before finishing.

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

## Hardcoded Limits

A catalog of every numeric limit, timeout, cap, and threshold lives in [`docs/HARDCODED_LIMITS.md`](../docs/HARDCODED_LIMITS.md).

**Rule:** When you add or change any hardcoded numeric limit (token cap, iteration max, timeout, truncation length, retry count, polling interval, threshold, etc.), you **must** update `docs/HARDCODED_LIMITS.md` in the same commit.

## Cron-driven Changes

Ker supports cron jobs via the `cron` tool.
You can schedule periodic engineering tasks by setting `action=add` with `every_seconds`, `cron_expr`, or `at`.

Always keep scheduled code tasks explicit and idempotent.
