---
name: claude
description: "Use Claude Code to implement coding tasks. Start Ker capture first, then run Claude Code autonomously with JSON output redirected to a task-specific workspace log for easier inspection."
---

# Claude Code Agent

Use Claude Code when you want Anthropic's coding agent to implement changes directly in the repository. Prefer autonomous, machine-readable runs with a workspace log whose filename is derived from the conversation session that triggered the run.

## When to Use

- Implementing a feature, fix, or refactor in a codebase
- Generating tests, docs, or boilerplate
- Exploring and modifying unfamiliar code
- Running an alternative coding agent workflow to compare with Codex

## Quick Start

Run Claude Code on a task in the current workspace:

```powershell
Set-Location C:\path\to\project
$task = "Implement a REST endpoint for user registration"
$sessionLogStem = "teams-alice-20260306-153045"  # Match the active Ker conversation session log stem.
$logDir = ".ker\logs\agents"
$logName = "claude-session-$sessionLogStem.jsonl"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
claude --print --output-format stream-json $task > (Join-Path $logDir $logName)
```

Use the same session stem that the triggering conversation uses, for example `teams-alice-20260306-153045`, so the redirected Claude log can be correlated directly with the source conversation.

## Required Invocation Pattern

For unattended coding work, use this form:

```powershell
claude --print --output-format stream-json "task description" > .\path\to\claude-session-<session-log-stem>.jsonl
```

Guidelines:

- Prefer non-interactive output using `--print`.
- Prefer structured output using `--output-format stream-json` when available.
- Always redirect stdout to a workspace-local `.jsonl` file.
- Derive the log name from the current conversation session log stem or Ker `session_id`, not just the task text.
- Prefer names like `claude-session-<session-log-stem>.jsonl` or `claude-session-<session-id>.jsonl`.
- Prefer storing logs under `.ker\logs\agents\` or another task-local folder inside the repository.

Ker's `capture_agent_conversation(agent="claude", ...)` watches Claude Code's native session files under `~/.claude/projects/<encoded-working-dir>/`. The redirected workspace JSONL log is still useful because it gives you a stable, session-linked artifact inside the repo for debugging, auditing, and manual inspection.

## Session-Based Naming

Claude Code is launched from an existing Ker conversation session, so the redirected agent log should inherit that session identity.

Recommended pattern:

```text
.ker/logs/agents/claude-session-<session-log-stem>.jsonl
```

Examples:

- `claude-session-teams-alice-20260306-153045.jsonl`
- `claude-session-cli-local-42f3d8c1.jsonl`

If you already know the Ker `session_id`, use that directly. If you are working from a saved conversation log file, use its stem unchanged.

## Common Patterns

### Single task
```powershell
$task = "Add input validation to the signup form"
$sessionId = "teams-alice-20260306-153045"
claude --print --output-format stream-json $task > ".\.ker\logs\agents\claude-session-$sessionId.jsonl"
```

### Scoped to a directory
```powershell
Set-Location C:\path\to\project\backend
$task = "Add rate limiting middleware to the Express server"
$sessionId = "teams-alice-20260306-153045"
claude --print --output-format stream-json $task > ".\.ker\logs\agents\claude-session-$sessionId.jsonl"
```

### With verification in the task
```powershell
$task = "Fix the failing test in test_auth.py, then run pytest to verify"
$sessionId = "teams-alice-20260306-153045"
claude --print --output-format stream-json $task > ".\.ker\logs\agents\claude-session-$sessionId.jsonl"
```

## Parallel Tasks with tmux

For multiple independent coding tasks, use tmux to run Claude Code agents in parallel (see tmux skill for details):

```bash
SOCKET="${TMPDIR:-/tmp}/claude-tasks.sock"

# Create worktrees if working in the same repo
git worktree add /tmp/task1 -b fix/task1
git worktree add /tmp/task2 -b feat/task2

# Launch parallel agents
tmux -S "$SOCKET" new-session -d -s task1
tmux -S "$SOCKET" new-session -d -s task2

tmux -S "$SOCKET" send-keys -t task1 "cd /tmp/task1 && export SESSION_LOG_STEM=teams-alice-20260306-153045 && mkdir -p .ker/logs/agents && claude --print --output-format stream-json 'Fix the null pointer in parser.go' > .ker/logs/agents/claude-session-${SESSION_LOG_STEM}.jsonl" Enter
tmux -S "$SOCKET" send-keys -t task2 "cd /tmp/task2 && export SESSION_LOG_STEM=teams-alice-20260306-153045 && mkdir -p .ker/logs/agents && claude --print --output-format stream-json 'Add pagination to the list endpoint' > .ker/logs/agents/claude-session-${SESSION_LOG_STEM}.jsonl" Enter

# Monitor progress
tmux -S "$SOCKET" capture-pane -p -t task1 -S -200
tmux -S "$SOCKET" capture-pane -p -t task2 -S -200
```

## Best Practices

- **Be specific**: Include file names, function names, or module paths when known.
- **Provide context**: Mention the language, framework, or conventions to follow.
- **Create the log directory first**: Ensure `.ker/logs/agents/` exists before redirecting output.
- **Use session-based log names**: Prefer `claude-session-<session-log-stem>.jsonl` so the log maps back to the conversation that launched it.
- **Use worktrees** for parallel tasks on the same repo to avoid branch conflicts.
- **Check results**: After Claude Code completes, review the changes with `git diff` and run tests.

## Detecting Completion

When running via tmux, check if Claude Code has finished by looking for the shell prompt:

```bash
if tmux -S "$SOCKET" capture-pane -p -t task1 -S -3 | grep -qE '[\$❯#]'; then
  echo "task1: DONE"
fi
```

## Cleanup

After parallel tasks, clean up worktrees:

```bash
git worktree remove /tmp/task1
git worktree remove /tmp/task2
```

## Conversation Capture

Before running a Claude Code task, start a conversation capture so the full session is recorded and indexed into Ker memory:

```
capture_agent_conversation(
  agent="claude",
  working_dir="/abs/path/to/project",
  label="short task description"
)
```

Then run Claude Code with a matching task label and log name, for example:

```powershell
$task = "Fix session timeout handling and run pytest tests/test_sessions.py"
$sessionId = "teams-alice-20260306-153045"
claude --print --output-format stream-json $task > ".\.ker\logs\agents\claude-session-$sessionId.jsonl"
```

The background watcher detects the new native Claude Code session file once the run finishes, parses it via dataclaw, and saves the structured conversation to `.ker/memory/agent_conversations/<session-id>.json`. The redirected workspace log is separate from Ker capture, but keeping its filename aligned with the triggering Ker session id makes later review much easier.