from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import shutil


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str
    available: bool = True
    requires: str = ""


class SkillsManager:
    def __init__(self, roots: list[Path], workspace: Path | None = None, ker_root: Path | None = None) -> None:
        self.roots = roots
        self.workspace = workspace
        self.ker_root = ker_root

    def discover(self, filter_unavailable: bool = False, agent_name: str = "") -> list[Skill]:
        found: dict[str, Skill] = {}
        # Include agent-specific skills directory
        search_roots = list(self.roots)
        if self.ker_root and agent_name:
            agent_skills = self.ker_root / "agents" / agent_name / "skills"
            if agent_skills.exists():
                search_roots.insert(0, agent_skills)

        for root in search_roots:
            if not root.exists():
                continue
            source = "workspace" if self.workspace and root == (self.workspace / ".skills") else "builtin"
            if self.ker_root and root.is_relative_to(self.ker_root):
                source = "agent"
            for p in root.rglob("SKILL.md"):
                text = p.read_text(encoding="utf-8", errors="ignore")
                name = self._extract_name(text) or p.parent.name
                description = self._extract_description(text)
                meta = self._extract_meta(text)
                available, missing = self._check_requirements(meta)
                if filter_unavailable and not available:
                    continue
                if name not in found:
                    found[name] = Skill(name=name, description=description, path=p, source=source, available=available, requires=missing)
        return sorted(found.values(), key=lambda s: s.name)

    def load_skill(self, name: str, agent_name: str = "") -> str | None:
        for s in self.discover(filter_unavailable=False, agent_name=agent_name):
            if s.name == name:
                return self._strip_frontmatter(s.path.read_text(encoding="utf-8", errors="ignore"))
        return None

    def install_skill(self, name: str, content: str, agent_name: str) -> Path:
        if not agent_name:
            raise ValueError("agent_name is required to install a skill")
        if not self.ker_root:
            raise ValueError("ker_root is required to install a skill")
        skill_dir = self.ker_root / "agents" / agent_name / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        target = skill_dir / "SKILL.md"
        target.write_text(content, encoding="utf-8")
        return target

    def get_always_skills(self, agent_name: str = "") -> list[str]:
        out = []
        for s in self.discover(filter_unavailable=True, agent_name=agent_name):
            text = s.path.read_text(encoding="utf-8", errors="ignore")
            meta = self._extract_meta(text)
            if bool(meta.get("always")):
                out.append(s.name)
        return out

    def render_skills_summary_xml(self, agent_name: str = "") -> str:
        skills = self.discover(filter_unavailable=False, agent_name=agent_name)
        if not skills:
            return ""

        def esc(v: str) -> str:
            return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in skills:
            lines.append(f'  <skill available="{str(s.available).lower()}">')
            lines.append(f"    <name>{esc(s.name)}</name>")
            lines.append(f"    <description>{esc(s.description)}</description>")
            lines.append(f"    <location>{esc(str(s.path))}</location>")
            if s.requires:
                lines.append(f"    <requires>{esc(s.requires)}</requires>")
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    def _extract_name(self, text: str) -> str:
        m = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
        return m.group(1).strip().strip("\"'") if m else ""

    def _extract_description(self, text: str) -> str:
        m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip().strip("\"'")
        for line in self._strip_frontmatter(text).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:120]
        return ""

    def _strip_frontmatter(self, text: str) -> str:
        if text.startswith("---"):
            m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
            if m:
                return text[m.end() :].strip()
        return text

    def _extract_meta(self, text: str) -> dict:
        if not text.startswith("---"):
            return {}
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            return {}
        data = {}
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip().strip("\"'")
        raw = data.get("metadata", "")
        if raw:
            try:
                obj = json.loads(raw)
                nested = obj.get("ker", obj.get("openclaw", {})) if isinstance(obj, dict) else {}
                if isinstance(nested, dict):
                    data.update(nested)
            except json.JSONDecodeError:
                pass
        return data

    def _check_requirements(self, meta: dict) -> tuple[bool, str]:
        requires = meta.get("requires", {})
        bins = requires.get("bins", []) if isinstance(requires, dict) else []
        envs = requires.get("env", []) if isinstance(requires, dict) else []
        missing = []
        for b in bins:
            if not shutil.which(str(b)):
                missing.append(f"CLI: {b}")
        for e in envs:
            if not os.environ.get(str(e)):
                missing.append(f"ENV: {e}")
        return (len(missing) == 0, ", ".join(missing))


def render_skills_block(skills: list[Skill], summary_xml: str = "") -> str:
    if not skills and not summary_xml:
        return ""
    lines = [
        "## Skills (mandatory)",
        "",
        "Before replying: scan available skill descriptions.",
        "- If exactly one skill clearly applies: read its SKILL.md via `skill` tool, then follow it.",
        "- If multiple could apply: choose the most specific one, then read and follow.",
        "- If none clearly apply: do not read any SKILL.md.",
        "Never read more than one skill up front; select first, then read.",
        "",
    ]
    if skills:
        lines.append("### Active skills (auto-loaded)")
        for s in skills:
            lines.append(f"- {s.name}: {s.description}")
        lines.append("")
    if summary_xml:
        lines.append("### Discoverable skills")
        lines.append(summary_xml)
    return "\n".join(lines)
