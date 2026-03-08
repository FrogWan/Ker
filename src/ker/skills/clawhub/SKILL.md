---
name: clawhub
description: Search and install agent skills from ClawHub, the public skill registry.
homepage: https://clawhub.ai
metadata: {"ker":{"emoji":"🦞"}}
---

# ClawHub

Public skill registry for AI agents. Search by natural language (vector search).

## When to use

Use this skill when the user asks any of:
- "find a skill for …"
- "search for skills"
- "install a skill"
- "what skills are available?"
- "update my skills"

## Search

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## Install

1. Download the skill to a temporary directory:

```bash
npx --yes clawhub@latest install <slug> --workdir /tmp/clawhub-staging
```

2. Read the downloaded SKILL.md:

```
read_file path=/tmp/clawhub-staging/.skills/<slug>/SKILL.md
```

3. Install via the skill tool so it is stored in the correct agent-specific directory:

```
skill action=install name=<slug> content=<contents of SKILL.md>
```

Replace `<slug>` with the skill name from search results.

## Update

To update a skill, repeat the install steps above — the new content overwrites the existing skill.

## List installed

Use `skill action=list` to see all installed skills including agent-specific ones.

## Notes

- Requires Node.js (`npx` comes with it).
- No API key needed for search and install.
- Login (`npx --yes clawhub@latest login`) is only required for publishing.
- Always use `skill(action="install")` to persist skills — do NOT write directly to paths with `~` as it does not expand correctly on Windows.
- After install, the skill is immediately discoverable in the current agent's skill list.
