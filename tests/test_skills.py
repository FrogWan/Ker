from __future__ import annotations

import pytest
from pathlib import Path

from ker.agent.context.skills import SkillsManager
from ker.tools.tool_base import ToolContext
from ker.tools.tool_skill import skill as skill_tool


@pytest.fixture
def tmp_ker(tmp_path: Path) -> Path:
    """Create a minimal .ker directory structure."""
    ker = tmp_path / ".ker"
    ker.mkdir()
    return ker


@pytest.fixture
def builtin_skills(tmp_path: Path) -> Path:
    """Create a builtin skills directory with one skill."""
    skills = tmp_path / "builtin_skills"
    skills.mkdir()
    demo = skills / "demo-skill"
    demo.mkdir()
    (demo / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo skill\n---\n# Demo\nHello",
        encoding="utf-8",
    )
    return skills


@pytest.fixture
def manager(tmp_ker: Path, builtin_skills: Path) -> SkillsManager:
    return SkillsManager(roots=[builtin_skills], ker_root=tmp_ker)


class TestInstallSkill:
    def test_install_skill(self, manager: SkillsManager) -> None:
        content = "---\nname: my-skill\ndescription: Test skill\n---\n# My Skill\nBody"
        path = manager.install_skill(name="my-skill", content=content, agent_name="ker")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == content
        expected = manager.ker_root / "agents" / "ker" / "skills" / "my-skill" / "SKILL.md"
        assert path == expected

    def test_install_skill_requires_agent_name(self, manager: SkillsManager) -> None:
        with pytest.raises(ValueError, match="agent_name"):
            manager.install_skill(name="x", content="y", agent_name="")

    def test_install_skill_requires_ker_root(self, builtin_skills: Path) -> None:
        mgr = SkillsManager(roots=[builtin_skills], ker_root=None)
        with pytest.raises(ValueError, match="ker_root"):
            mgr.install_skill(name="x", content="y", agent_name="ker")


class TestDiscoverAgentSkills:
    def test_discover_finds_agent_skills(self, manager: SkillsManager) -> None:
        content = "---\nname: agent-skill\ndescription: Agent specific\n---\n# Agent Skill"
        manager.install_skill(name="agent-skill", content=content, agent_name="test-agent")

        skills = manager.discover(agent_name="test-agent")
        names = [s.name for s in skills]
        assert "agent-skill" in names
        assert "demo-skill" in names

    def test_discover_without_agent_name_misses_agent_skills(self, manager: SkillsManager) -> None:
        content = "---\nname: hidden-skill\ndescription: Hidden\n---\n# Hidden"
        manager.install_skill(name="hidden-skill", content=content, agent_name="test-agent")

        skills = manager.discover(agent_name="")
        names = [s.name for s in skills]
        assert "hidden-skill" not in names
        assert "demo-skill" in names

    def test_agent_skill_source_is_agent(self, manager: SkillsManager) -> None:
        content = "---\nname: src-skill\ndescription: Source test\n---\n# Src"
        manager.install_skill(name="src-skill", content=content, agent_name="ker")

        skills = manager.discover(agent_name="ker")
        agent_skill = next(s for s in skills if s.name == "src-skill")
        assert agent_skill.source == "agent"


class TestLoadSkillWithAgentName:
    def test_load_skill_with_agent_name(self, manager: SkillsManager) -> None:
        content = "---\nname: loadable\ndescription: Loadable\n---\n# Loadable\nBody text"
        manager.install_skill(name="loadable", content=content, agent_name="ker")

        result = manager.load_skill("loadable", agent_name="ker")
        assert result is not None
        assert "Body text" in result

    def test_load_skill_without_agent_name_misses_agent_skill(self, manager: SkillsManager) -> None:
        content = "---\nname: invisible\ndescription: Invisible\n---\n# Invisible"
        manager.install_skill(name="invisible", content=content, agent_name="ker")

        result = manager.load_skill("invisible", agent_name="")
        assert result is None


class TestSkillToolInstallAction:
    def test_skill_tool_install_action(self, tmp_ker: Path, builtin_skills: Path) -> None:
        mgr = SkillsManager(roots=[builtin_skills], ker_root=tmp_ker)
        ctx = ToolContext(workspace=tmp_ker.parent, ker_root=tmp_ker, skills_manager=mgr, agent_name="ker")

        content = "---\nname: tool-skill\ndescription: Tool test\n---\n# Tool Skill"
        result = skill_tool(ctx, action="install", name="tool-skill", content=content)
        assert "installed" in result.lower()

        expected = tmp_ker / "agents" / "ker" / "skills" / "tool-skill" / "SKILL.md"
        assert expected.exists()
        assert expected.read_text(encoding="utf-8") == content

    def test_skill_tool_install_missing_name(self, tmp_ker: Path, builtin_skills: Path) -> None:
        mgr = SkillsManager(roots=[builtin_skills], ker_root=tmp_ker)
        ctx = ToolContext(workspace=tmp_ker.parent, ker_root=tmp_ker, skills_manager=mgr, agent_name="ker")

        result = skill_tool(ctx, action="install", name="", content="x")
        assert "error" in result.lower()

    def test_skill_tool_install_missing_content(self, tmp_ker: Path, builtin_skills: Path) -> None:
        mgr = SkillsManager(roots=[builtin_skills], ker_root=tmp_ker)
        ctx = ToolContext(workspace=tmp_ker.parent, ker_root=tmp_ker, skills_manager=mgr, agent_name="ker")

        result = skill_tool(ctx, action="install", name="x", content="")
        assert "error" in result.lower()

    def test_skill_tool_list_shows_installed(self, tmp_ker: Path, builtin_skills: Path) -> None:
        mgr = SkillsManager(roots=[builtin_skills], ker_root=tmp_ker)
        ctx = ToolContext(workspace=tmp_ker.parent, ker_root=tmp_ker, skills_manager=mgr, agent_name="ker")

        content = "---\nname: listed-skill\ndescription: Listed\n---\n# Listed"
        skill_tool(ctx, action="install", name="listed-skill", content=content)

        result = skill_tool(ctx, action="list")
        assert "listed-skill" in result

    def test_skill_tool_read_installed(self, tmp_ker: Path, builtin_skills: Path) -> None:
        mgr = SkillsManager(roots=[builtin_skills], ker_root=tmp_ker)
        ctx = ToolContext(workspace=tmp_ker.parent, ker_root=tmp_ker, skills_manager=mgr, agent_name="ker")

        content = "---\nname: readable\ndescription: Readable\n---\n# Readable\nThe body"
        skill_tool(ctx, action="install", name="readable", content=content)

        result = skill_tool(ctx, action="read", name="readable")
        assert "The body" in result
