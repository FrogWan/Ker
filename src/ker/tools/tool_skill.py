from __future__ import annotations

from ker.tools.tool_base import ToolContext


def skill(ctx: ToolContext, action: str, name: str = "", include_unavailable: bool = False, content: str = "") -> str:
    if ctx.skills_manager is None:
        return "Error: skills manager not configured"
    agent_name = ctx.agent_name
    if action == "list":
        skills = ctx.skills_manager.discover(filter_unavailable=not include_unavailable, agent_name=agent_name)
        if not skills:
            return "No skills found"
        lines = []
        for s in skills:
            suffix = "" if s.available else f" (unavailable: {s.requires})"
            lines.append(f"- {s.name}: {s.description} [{s.source}] -> {s.path}{suffix}")
        return "\n".join(lines)
    if action == "show":
        return ctx.skills_manager.render_skills_summary_xml(agent_name=agent_name) or "No skills summary"
    if action == "read":
        if not name:
            return "Error: name is required for action=read"
        loaded = ctx.skills_manager.load_skill(name, agent_name=agent_name)
        if not loaded:
            return f"Error: skill not found: {name}"
        return loaded
    if action == "install":
        if not name:
            return "Error: name is required for action=install"
        if not content:
            return "Error: content is required for action=install"
        try:
            path = ctx.skills_manager.install_skill(name=name, content=content, agent_name=agent_name)
            return f"Skill '{name}' installed at {path}"
        except ValueError as exc:
            return f"Error: {exc}"
    return f"Error: unknown skill action: {action}"
