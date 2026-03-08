# Ker

Ker is a CLI-first, extensible agent runtime that implements a full agent stack: loop, tools, sessions, routing, intelligence, heartbeat/cron, delivery reliability, and lane-based concurrency.

## Features

- Stable agent loop with tool-use chaining.
- Tool registry and handlers: `exec`, `bash`, `read_file`, `write_file`, `edit_file`, `list_dir`, `skill`, `read_memory`, `read_error_log`, `web_search`, `web_fetch`, `cron`, `message`, `spawn`, `mcp` with background subagent support.
- JSONL session persistence and context compaction.
- Channel abstraction with CLI channel enabled by default, plus KerWeb bridge channel.
- Binding-table routing and multi-agent configs.
- Layered system prompt assembly from workspace bootstrap files.
- Memory search and auto-recall.
- Heartbeat runner and cron scheduler (off by default).
- Write-ahead delivery queue with retries and backoff.
- Named-lane concurrency with generation-based reset safety.

## Architecture

| Module | Purpose |
|---|---|
| `agent/` | Runtime, agent turn loop, provider integration, system prompt assembly, session key generation |
| `channels/` | Channel abstraction, CLI channel, command dispatch |
| `tools/` | Tool schemas, dispatch, domain handlers (exec/fs/memory/web/automation) |
| `session/` | JSONL session persistence and context compaction guard |
| `routing/` | Multi-agent configs and binding-table routing |
| `memory/` | Daily memory logs, similarity search, bootstrap file loading, skills discovery |
| `concurrency/` | Named-lane queues and generation-based reset safety |
| `delivery/` | Write-ahead outbound queue, retries, background runner |
| `scheduler/` | Heartbeat runner and cron service |

## Runtime Behavior

1. Resolve target agent and session key from inbound message context.
2. Load session history and append current user message.
3. Recall relevant memory snippets for prompt context.
4. Build full system prompt from bootstrap files, active skills, and agent intro.
5. Run the model/tool chain with context-overflow compaction and persist assistant output blocks.
6. Persist daily memory and queue delivery messages with channel-aware chunking.
7. Poll cron, heartbeat, and subagent outputs from the background loop.

## Prerequisites

- Python 3.11+
- `uv` (recommended) or any compatible Python environment manager.
- `ANTHROPIC_API_KEY` in environment or `.env`.

## Install

```bash
uv sync
```

## Run

```bash
uv run ker
```

### Start the Agent Gateway

The gateway is the long-running process that connects channels, tools, and the agent loop.

```bash
# With uv
uv run ker gateway

# Without uv (using the project venv)
.venv/Scripts/python -c "import sys; sys.argv=['ker','gateway']; from ker.main import main; main()"

# Or directly via the entry point
python -m ker.main gateway
```

To run in the background (Windows):

```powershell
Start-Process -NoNewWindow -FilePath .venv\Scripts\python.exe -ArgumentList '-c', "import sys; sys.argv=['ker','gateway']; from ker.main import main; main()"
```

## Environment

- `ANTHROPIC_API_KEY` (required for model calls)
- `MODEL_ID` (default: `claude-sonnet-4-20250514`)
- `MAX_TOKENS` (default: `8096`)
- `DELIVERY_ENABLED=1` to auto-run delivery background runner
- `HEARTBEAT_ENABLED=1` to auto-run heartbeat
- `CRON_ENABLED=1` to auto-run cron scheduler
- `KERWEB_ENABLED=1` to enable KerWeb channel polling
- `KERWEB_BASE_URL` KerWeb base URL (default: `http://127.0.0.1:3000`)
- `KERWEB_API_KEY` KerWeb registered user API key
- `KERWEB_POLL_INTERVAL_SEC` KerWeb poll interval in seconds (default: `1.0`)

Runtime state is stored in project-local `.ker/`.

Bootstrap defaults ship with Ker and load automatically.

Optional bootstrap overrides are read from `.ker/templates/` (for example: `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `AGENTS.md`). Ker does not create these files on every run.

## Reliability and Scheduling

- Delivery retries use backoff schedule `5s -> 25s -> 120s -> 600s` with max 5 retries.
- Heartbeat and cron services can be enabled independently by environment flags.

## CLI Commands

- Core: `/help`, `/exit`
- Sessions/context: `/sessions`, `/new <name>`, `/switch <name>`, `/context`, `/compact`
- Prompt/memory: `/prompt`, `/bootstrap`, `/search <query>`, `/skills`
- Memory+errors via tools: `read_memory`, `read_error_log`
- Routing/agents: `/agents`, `/bindings`, `/route <channel> <peer>`, `/switch-agent <id|off>`
- Heartbeat/cron: `/heartbeat`, `/trigger`, `/cron`, `/cron-run <job_id>`
- Delivery: `/queue`, `/failed`, `/stats`
- Concurrency: `/lanes`, `/enqueue <lane> <text>`, `/concurrency <lane> <n>`, `/generation`, `/reset`
## Tests

```bash
uv run pytest -q
```

Fallback without `uv`:

```bash
python -m pytest -q
```

## Extending Channels

Implement `ker.channels.base.Channel` and register it in runtime setup. The agent core consumes normalized `InboundMessage`, so new channels do not require loop changes.


