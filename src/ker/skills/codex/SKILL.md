````skill
---
name: codex
description: "Use OpenAI Codex to implement coding tasks. Spawn Codex via `codex exec --dangerously-bypass-approvals-and-sandbox --json` so the run is autonomous and the JSONL log can be captured alongside Ker's agent conversation capture."
---

# Codex Coding Agent

Use the `codex` CLI to delegate coding tasks to OpenAI Codex. Prefer `codex exec --dangerously-bypass-approvals-and-sandbox --json` and redirect the JSONL output into a workspace log file whose name is derived from the current conversation session log name.

## When to Use

- Implementing a feature, fix, or refactor in a codebase
- Generating boilerplate, tests, or documentation
- Exploring and modifying unfamiliar code
- Parallelizing multiple independent coding tasks

## Quick Start

Run Codex on a task in the current workspace:
```powershell
Set-Location C:\path\to\project
$task = "Implement a REST endpoint for user registration"
$sessionLogStem = "teams-alice-20260306-153045"  # Match the active Ker conversation session log stem.
$logDir = ".ker\logs\agents"
$logName = "codex-session-$sessionLogStem.jsonl"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
codex exec --dangerously-bypass-approvals-and-sandbox --json $task > (Join-Path $logDir $logName)
```

Use the same session stem that the triggering conversation uses, for example `teams-alice-20260306-153045`, so the redirected Codex log can be correlated directly with the source conversation.

## Required Invocation Pattern

For unattended coding work, use this form:

```powershell
codex exec --dangerously-bypass-approvals-and-sandbox --json "task description" > .\path\to\codex-session-<session-log-stem>.jsonl
```

Guidelines:

- Always use `exec`.
- Always include `--dangerously-bypass-approvals-and-sandbox` for fully autonomous runs.
- Always include `--json` so Codex emits machine-readable events.
- Always redirect stdout to a workspace-local `.jsonl` file.
- Derive the log name from the current conversation session log stem or Ker `session_id`, not just the task text.
- Prefer names like `codex-session-<session-log-stem>.jsonl` or `codex-session-<session-id>.jsonl`.
- Prefer storing logs under `.ker\logs\agents\` or another task-local folder inside the repository.

Ker's `capture_agent_conversation(agent="codex", ...)` still watches Codex's native session files under `~/.codex/sessions`. The extra redirected JSONL log is still useful because it gives you a stable, session-linked artifact inside the repo for debugging, auditing, and manual inspection.

## Session-Based Naming

Codex and Claude are both launched from an existing Ker conversation session, so the redirected agent log should inherit that session identity.

Recommended pattern:

```text
.ker/logs/agents/codex-session-<session-log-stem>.jsonl
```

Examples:

- `codex-session-teams-alice-20260306-153045.jsonl`
- `codex-session-cli-local-42f3d8c1.jsonl`

If you already know the Ker `session_id`, use that directly. If you are working from a saved conversation log file, use its stem unchanged.

## Common Patterns

### Single task
```powershell
$task = "Add input validation to the signup form"
$sessionId = "teams-alice-20260306-153045"
codex exec --dangerously-bypass-approvals-and-sandbox --json $task > ".\.ker\logs\agents\codex-session-$sessionId.jsonl"
```

### Scoped to a directory
```powershell
Set-Location C:\path\to\project\backend
$task = "Add rate limiting middleware to the Express server"
$sessionId = "teams-alice-20260306-153045"
codex exec --dangerously-bypass-approvals-and-sandbox --json $task > ".\.ker\logs\agents\codex-session-$sessionId.jsonl"
```

### With a specific model
```powershell
$task = "Write unit tests for utils.py"
$sessionId = "teams-alice-20260306-153045"
codex exec --model o4-mini --dangerously-bypass-approvals-and-sandbox --json $task > ".\.ker\logs\agents\codex-session-$sessionId.jsonl"
```

## Parallel Tasks with tmux

For multiple independent coding tasks, use tmux to run Codex agents in parallel (see tmux skill for details):

```bash
SOCKET="${TMPDIR:-/tmp}/codex-tasks.sock"

# Create worktrees if working in the same repo
git worktree add /tmp/task1 -b fix/task1
git worktree add /tmp/task2 -b feat/task2

# Launch parallel agents
tmux -S "$SOCKET" new-session -d -s task1
tmux -S "$SOCKET" new-session -d -s task2

tmux -S "$SOCKET" send-keys -t task1 "cd /tmp/task1 && export SESSION_LOG_STEM=teams-alice-20260306-153045 && mkdir -p .ker/logs/agents && codex exec --dangerously-bypass-approvals-and-sandbox --json 'Fix the null pointer in parser.go' > .ker/logs/agents/codex-session-${SESSION_LOG_STEM}.jsonl" Enter
tmux -S "$SOCKET" send-keys -t task2 "cd /tmp/task2 && export SESSION_LOG_STEM=teams-alice-20260306-153045 && mkdir -p .ker/logs/agents && codex exec --dangerously-bypass-approvals-and-sandbox --json 'Add pagination to the list endpoint' > .ker/logs/agents/codex-session-${SESSION_LOG_STEM}.jsonl" Enter

# Monitor progress
tmux -S "$SOCKET" capture-pane -p -t task1 -S -200
tmux -S "$SOCKET" capture-pane -p -t task2 -S -200
```

## Best Practices

- **Be specific**: Include file names, function names, or module paths when known.
- **Provide context**: Mention the language, framework, or conventions to follow.
- **Create the log directory first**: Ensure `.ker/logs/agents/` exists before redirecting output.
- **Use session-based log names**: Prefer `codex-session-<session-log-stem>.jsonl` so the log maps back to the conversation that launched it.
- **Use worktrees** for parallel tasks on the same repo to avoid branch conflicts.
- **Check results**: After Codex completes, review the changes with `git diff` and run tests.
- **Tell Codex to verify**: If the project has tests, include verification in the task:
  ```powershell
  $sessionId = "teams-alice-20260306-153045"
  codex exec --dangerously-bypass-approvals-and-sandbox --json "Fix the failing test in test_auth.py, then run pytest to verify" > ".\.ker\logs\agents\codex-session-$sessionId.jsonl"
  ```

## Detecting Completion

When running via tmux, check if Codex has finished by looking for the shell prompt:
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

Before running a Codex task, start a conversation capture so the full session is recorded and indexed into Ker memory:

```
capture_agent_conversation(
  agent="codex",
  working_dir="/abs/path/to/project",
  label="short task description"
)
```

Then run Codex with a matching task label and log name, for example:

```powershell
$task = "Fix session timeout handling and run pytest tests/test_sessions.py"
$sessionId = "teams-alice-20260306-153045"
codex exec --dangerously-bypass-approvals-and-sandbox --json $task > ".\.ker\logs\agents\codex-session-$sessionId.jsonl"
```

The background watcher detects the new native Codex session file once the run finishes, parses it via dataclaw, and saves the structured conversation to `.ker/memory/agent_conversations/<session-id>.json`. The redirected workspace log is separate from Ker capture, but keeping its filename aligned with the triggering Ker session id makes later review much easier.

````
