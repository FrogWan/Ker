# Hardcoded Limits Reference

All hardcoded numeric limits, thresholds, and caps in the Ker codebase.

> **Rule:** When adding or changing any hardcoded limit, update this document.
> See [CLAUDE.md](../.claude/CLAUDE.md) § "Hardcoded Limits" for the enforcement rule.

## Token Limits

| Value | File | Line | Description |
|-------|------|------|-------------|
| 16384 | `src/ker/config.py` | 85 | Default `max_tokens` for LLM responses |

## Loop / Iteration Limits

| Value | File | Line | Description |
|-------|------|------|-------------|
| 120 | `src/ker/agent/agent_loop.py` | 46 | Max tool iterations per turn |
| 50 | `src/ker/tools/tool_longtask.py` | 31 | Default max iterations for `long_task` |
| 50 | `src/ker/tools/tool_registry.py` | 26 | Schema max for `long_task` `max_iterations` |
| 3 | `src/ker/llm/github_copilot.py` | 153 | API key refresh retry attempts |
| 60 | `src/ker/llm/github_copilot.py` | 184 | OAuth device flow polling iterations (5 min max) |
| 3 | `src/ker/longtask/orchestrator.py` | 18 | Max supervisor respawns |
| 2 | `src/ker/agent/context/context_guard.py` | 74 | Context guard max retries on overflow |

## String / Text Length Limits

| Value | File | Line | Description |
|-------|------|------|-------------|
| 64 | `src/ker/agent/context/session.py` | 14 | Session name max length |
| 12,000 | `src/ker/agent/context/context_guard.py` | 11 | Tool result truncation limit (chars) |
| 30,000 | `src/ker/tools/tool_exec.py` | 116 | Command output truncation |
| 30,000 | `src/ker/tools/tool_fallback.py` | 19 | Fallback notification max output |
| 20,000 | `src/ker/agent/context/prompt_builder.py` | 28 | Per-file prompt cap |
| 300,000 | `src/ker/agent/context/prompt_builder.py` | 28 | Total prompt builder cap |
| 100,000 | `src/ker/tools/tool_web.py` | 34 | Web fetch max chars |
| 2,000 | `src/ker/tools/tool_longtask.py` | 460, 464 | Review feedback / reviewer output tail |
| 500 | `src/ker/tools/tool_longtask.py` | 285 | Feedback truncation |
| 1,000 | `src/ker/longtask/orchestrator.py` | 187, 189 | Result / error preview length |
| 2,000 | `src/ker/longtask/orchestrator.py` | 254 | Synthesis result max length |
| 500 | `src/ker/agent/context/memory.py` | 286, 349 | Memory hit snippet max length |

## Timeout Limits (seconds)

| Value | File | Line | Description |
|-------|------|------|-------------|
| 600 | `src/ker/agent/agent_loop.py` | 47 | Turn timeout (10 min) |
| 300 | `src/ker/tools/tool_exec.py` | 16 | Exec command hard cap (5 min) |
| 60 | `src/ker/tools/tool_exec.py` | 52 | `exec_command` default timeout |
| 30 | `src/ker/tools/tool_exec.py` | 120 | `bash` default timeout |
| 7,200 | `src/ker/tools/tool_fallback.py` | 18 | Fallback tool timeout (2 hr) |
| 7,200 | `src/ker/tools/tool_longtask.py` | 19 | Long task iteration timeout (2 hr) |
| 3,600 | `src/ker/tools/tool_capture.py` | 23 | Capture agent conversation timeout (1 hr) |
| 30 | `src/ker/tools/tool_mcp.py` | 22, 89 | MCP tool default timeout |
| 300 | `src/ker/llm/github_copilot.py` | 567 | Copilot HTTP client timeout (5 min) |
| 30 | `src/ker/llm/github_copilot.py` | 155, 174, 194 | GitHub API request timeouts |
| 300 | `src/ker/skills/openai-image-gen/scripts/gen.py` | 202 | Image generation request timeout (5 min) |
| 10 | `src/ker/channels/kerweb.py` | 41 | KerWeb HTTP client timeout |
| 5–10 | various `wait_for` calls | — | Process kill / wait timeouts |

## Size / Count Limits

| Value | File | Line | Description |
|-------|------|------|-------------|
| 10 | `src/ker/tools/tool_registry.py` | 19 | Web search max result count |
| 100 | `src/ker/tools/tool_registry.py` | 20 | Web fetch `maxChars` minimum |
| 10 | `src/ker/tools/tool_reply.py` | 13 | `reply_user` max file attachments |
| 10 MB | `src/ker/tools/tool_reply.py` | 14 | `reply_user` max base64-encoded image size |
| 20 | `src/ker/tools/tool_registry.py` | 17 | `read_memory` `top_k` maximum |
| 50 | `src/ker/tools/tool_registry.py` | 25 | `self_evolve` history limit maximum |
| 5 | `src/ker/agent/context/session.py` | 239 | Recent media messages kept |
| 6 | `src/ker/tools/tool_longtask.py` | 143 | Long task history entries shown |
| 8 | `src/ker/agent/context/context_guard.py` | 30 | Min messages before compaction |

## Retry / Backoff

| Value | File | Line | Description |
|-------|------|------|-------------|
| 5 | `src/ker/gateway/delivery.py` | 16 | Max delivery retries |
| [5s, 25s, 120s, 600s] | `src/ker/gateway/delivery.py` | 15 | Backoff schedule |

## Polling / Heartbeat Intervals

| Value | File | Line | Description |
|-------|------|------|-------------|
| 1.0s | `src/ker/channels/kerweb.py` | 24 | KerWeb poll interval |
| 1.0s | `src/ker/config.py` | 96 | KerWeb poll interval (config default) |
| 0.05s | `src/ker/channels/base.py` | 45 | Base channel poll sleep |
| 5s | `src/ker/longtask/orchestrator.py` | 16 | Task monitor poll interval |
| 60s | `src/ker/scheduler/heartbeat.py` | 29 | Heartbeat default interval |
| 5s | `src/ker/llm/github_copilot.py` | 185 | OAuth polling sleep |

## Thresholds / Ratios

| Value | File | Line | Description |
|-------|------|------|-------------|
| 0.70 | `src/ker/agent/context/memory.py` | 24 | Memory dedup similarity threshold |
| 70% / 20% | `src/ker/agent/context/prompt_builder.py` | 40–41 | Smart truncate head / tail split |
| 20% (min 4) | `src/ker/agent/context/context_guard.py` | 32 | History compaction keep ratio |
| 50% (min 2) | `src/ker/agent/context/context_guard.py` | 33 | History compaction compress ratio |
| 30s | `src/ker/longtask/orchestrator.py` | 17 | Notification cooldown between milestones |
| 50 | `src/ker/config.py` | 100 | Memory consolidation window |

## Gateway Sleep Intervals

| Value | File | Line | Description |
|-------|------|------|-------------|
| 1s | `src/ker/gateway/gateway.py` | 373, 385 | Main loop sleep |
| 10s | `src/ker/gateway/gateway.py` | 389 | Delivery queue check interval |
| 1s | `src/ker/gateway/gateway.py` | 430 | Background task sleep |
