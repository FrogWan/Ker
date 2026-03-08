# Self-Evolution Cycle

You are running a daily self-evolution cycle. Your goal: find ONE small improvement to make Ker better based on operational evidence.

## Steps

### 1. Gather Evidence

Use tools to collect data:

- `read_error_log` (limit=50) — recent runtime errors
- `read_file` on recent daily memory files in `.ker/memory/daily/`
- `read_file` on `.ker/agents/ker/AGENT.md` — current behavioral guidelines
- `read_file` on `.ker/agents/ker/MEMORY.md` (if it exists) — persistent memory

Skim for patterns: recurring errors, repeated user friction, missed optimizations.

### 2. Analyze

Identify the **single most impactful pattern** across three axes:

- **Technical** — Recurring errors, tool misuse, failed commands
- **Cognitive** — Reasoning gaps, missed context, poor prioritization
- **Existential** — Identity drift, unclear purpose, inconsistent voice

If no clear pattern emerges, skip to step 4 with `"changed": null`.

### 3. Act (if warranted)

Make **exactly ONE** additive edit (1-5 lines) to either:
- `.ker/agents/ker/AGENT.md` — behavioral guidelines
- `.ker/agents/ker/MEMORY.md` — persistent memory/patterns

Rules:
- **Additive only** — append or insert, never delete existing content
- **1-5 lines** — small, justified, specific
- **Evidence-based** — cite the pattern that motivated the change
- **Conservative** — when in doubt, skip

Use `edit_file` to make the change.

### 4. Log

Append ONE JSON line to `.ker/memory/evolution/log.jsonl` using `write_file`.

Format (single line, no pretty-printing):
```json
{"ts": <unix_timestamp>, "date": "<YYYY-MM-DD>", "changed": "<file_path_or_null>", "reason": "<what_pattern_you_found>", "action": "<what_you_did_or_skipped>", "axis": "<technical|cognitive|existential>"}
```

If you skipped (no change warranted), set `"changed": null` and `"action": "No change warranted — <brief reason>"`.

## Constraints

- Do NOT make more than one change per cycle.
- Do NOT remove or rewrite existing content — only add.
- Do NOT modify code files — only `.md` files under `.ker/agents/`.
- If the evidence is ambiguous, log "no change" and stop. Conservative is correct.
