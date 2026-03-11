from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os

from dotenv import load_dotenv

BUILTIN_MCP_SERVERS: dict[str, dict] = {
    "chrome_devtools": {
        "command": "npx",
        "args": [
            "-y", "chrome-devtools-mcp@latest",
            "--executable-path=C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        ],
        "builtin": True,
    },
    "computer_use": {
        "command": "uvx",
        "args": ["windows-mcp"],
        "builtin": True,
        "tool_timeout": 30,
    },
}


@dataclass
class Settings:
    workspace: Path
    ker_root: Path
    model_id: str
    anthropic_api_key: str
    max_tokens: int
    llm_provider: str
    azure_openai_key: str
    azure_openai_endpoint: str
    github_copilot_token: str
    heartbeat_enabled: bool
    cron_enabled: bool
    delivery_enabled: bool
    kerweb_enabled: bool
    kerweb_base_url: str
    kerweb_api_key: str
    kerweb_poll_interval_sec: float
    log_retention_days: int
    debug_rebuild_snapshot_enabled: bool
    mcp_servers: dict
    memory_consolidation_window: int


def _merge_mcp_servers(user_config: dict) -> dict:
    """Merge built-in MCP servers with user config.

    User config takes precedence. Set ``{"enabled": false}`` to disable a
    built-in server.
    """
    merged = dict(BUILTIN_MCP_SERVERS)
    merged.update(user_config)
    return {k: v for k, v in merged.items() if v.get("enabled", True) is not False}


def load_settings() -> Settings:
    load_dotenv()
    workspace = Path.cwd().resolve()
    ker_root = workspace / ".ker"

    # config.json takes precedence over .env
    config: dict = {}
    config_path = ker_root / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    def get(key: str, env_key: str, default: str) -> str:
        return config.get(key, os.getenv(env_key, default))

    return Settings(
        workspace=workspace,
        ker_root=ker_root,
        model_id=get("model_id", "MODEL_ID", "claude-opus-4-6"),
        anthropic_api_key=get("anthropic_api_key", "ANTHROPIC_API_KEY", ""),
        max_tokens=int(get("max_tokens", "MAX_TOKENS", "8096")),
        llm_provider=get("llm_provider", "LLM_PROVIDER", "anthropic"),
        azure_openai_key=get("azure_openai_key", "AZURE_OPENAI_KEY", ""),
        azure_openai_endpoint=get("azure_openai_endpoint", "AZURE_OPENAI_ENDPOINT", ""),
        github_copilot_token=get("github_copilot_token", "GITHUB_COPILOT_TOKEN", ""),
        heartbeat_enabled=get("heartbeat_enabled", "HEARTBEAT_ENABLED", "1") == "1",
        cron_enabled=get("cron_enabled", "CRON_ENABLED", "1") == "1",
        delivery_enabled=get("delivery_enabled", "DELIVERY_ENABLED", "0") == "1",
        kerweb_enabled=get("kerweb_enabled", "KERWEB_ENABLED", "1") == "1",
        kerweb_base_url=get("kerweb_base_url", "KERWEB_BASE_URL", "https://kerweb-app.azurewebsites.net"),
        kerweb_api_key=get("kerweb_api_key", "KERWEB_API_KEY", ""),
        kerweb_poll_interval_sec=float(get("kerweb_poll_interval_sec", "KERWEB_POLL_INTERVAL_SEC", "1.0")),
        log_retention_days=int(get("log_retention_days", "LOG_RETENTION_DAYS", "30")),
        debug_rebuild_snapshot_enabled=get("debug_rebuild_snapshot_enabled", "DEBUG_REBUILD_SNAPSHOT_ENABLED", "1") == "1",
        mcp_servers=_merge_mcp_servers(config.get("mcp_servers", {})),
        memory_consolidation_window=int(get("memory_consolidation_window", "MEMORY_CONSOLIDATION_WINDOW", "50")),
    )
