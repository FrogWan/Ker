from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ker.logger import get_logger

log = get_logger("agent_config")


@dataclass
class AgentConfig:
    name: str
    enabled: bool = True
    model_id: str | None = None
    max_tokens: int | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None

    @classmethod
    def load(cls, agent_dir: Path) -> AgentConfig:
        """Load agent config from .ker/agents/{name}/config.json."""
        name = agent_dir.name
        config_path = agent_dir / "config.json"
        if not config_path.exists():
            return cls(name=name)
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return cls(
                name=name,
                enabled=bool(data.get("enabled", True)),
                model_id=data.get("model_id"),
                max_tokens=data.get("max_tokens"),
                tools=data.get("tools"),
                skills=data.get("skills"),
            )
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load config for agent '%s': %s", name, exc)
            return cls(name=name)

    @classmethod
    def load_all(cls, agents_dir: Path) -> dict[str, AgentConfig]:
        """Load configs for all agent directories."""
        configs: dict[str, AgentConfig] = {}
        if not agents_dir.exists():
            return configs
        for d in agents_dir.iterdir():
            if d.is_dir():
                cfg = cls.load(d)
                configs[cfg.name] = cfg
        return configs
