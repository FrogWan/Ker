# Tool Usage Notes

Tool signatures are provided automatically by function calling. This file covers
usage guidelines and environment-specific notes — not tool definitions.

## General Principles

- State what you intend to do before calling a tool.
- Never claim a result before receiving it.
- If a tool fails, read the error, analyze, and retry with a different approach.
- Re-read modified files when correctness matters.

## bash

- Commands execute in the workspace directory.
- Use bounded timeouts. Long-running commands should be explicit about it.
- Validate output before acting on it.
- Never run destructive commands (rm -rf, DROP TABLE, etc.) without confirming first.

## File Tools (read_file / write_file / edit_file / list_dir)

- Stay within workspace paths.
- Always read before write — understand what's there before changing it.
- For edits, ensure exact match on the old content before replacing.
- Prefer small, targeted edits over full rewrites.
- **Scratch / temporary code**: Always write scratch scripts and temporary code to
  `.ker/tmp_code/` (e.g., `.ker/tmp_code/read_outlook.py`). Never place generated
  scripts in the project root — that pollutes the repository. Files written to the
  project root outside of `src/`, `tests/`, or other project directories will be
  automatically redirected to `.ker/tmp_code/`.

## Memory Tools

- Use `write_memory` to save important facts (user preferences, project info, recurring patterns) to long-term memory. These are always available in your context.
- Use `read_memory` to search recent conversations and session context. Use when recalling what was discussed recently or finding past decisions.
- Long-term memory (MEMORY.md) is automatically loaded every turn — no need to search it.

## Skill Tool

- Scan available skills before starting a task — a specialized workflow may exist.
- Read one SKILL.md at a time. Don't bulk-load skills.
- Follow skill instructions when they apply; they encode domain knowledge.

## Cron vs Heartbeat

- **Heartbeat**: Batched checks with conversational context. Good for periodic reviews,
  workspace monitoring, and tasks that benefit from agent memory.
- **Cron**: Exact timing, isolated execution. Good for scheduled jobs that should run
  independently (backups, reports, deployments).

## Self-Evolution (self_evolve)

- Ker runs a daily self-evolution cycle (default: 3 AM) that reads error logs, memory,
  and chat history, identifies one improvement, and makes a small additive edit to
  AGENT.md or MEMORY.md.
- Use `self_evolve(action="status")` to check schedule, cycle count, and last action.
- Use `self_evolve(action="history", limit=10)` to review past evolution entries.
- Use `self_evolve(action="trigger")` to manually run a cycle (spawns a subagent).
- Use `self_evolve(action="config")` to view config; pass `cron_expr` or `enabled` to update.
- Evolution log lives at `.ker/memory/evolution/log.jsonl`.
- Changes are always additive (1-5 lines) and conservative — the cycle skips if no clear pattern.

## Computer Use (MCP: computer_use)

- Built-in MCP server (Windows-MCP) providing desktop control via `mcp_computer_use_*` tools.
- Uses native Windows UI Automation — returns labeled interactive elements.
- Key tools: Snapshot, Click, Type, Shortcut, Scroll, App, PowerShell, FileSystem, Clipboard.
- **Always Snapshot first** — use element `label` IDs for reliable targeting.
- Read the `computer-use` skill for detailed workflow patterns.

## Your Environment

<!-- Fill in project-specific details below -->
- SSH hosts:
- Build commands:
- Project paths:
- Custom tooling:
