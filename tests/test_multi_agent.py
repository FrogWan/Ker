import json
import pytest
from pathlib import Path
from ker.agent.agent_config import AgentConfig


def test_agent_config_defaults():
    """Verify AgentConfig defaults."""
    cfg = AgentConfig(name="test")
    assert cfg.enabled is True
    assert cfg.model_id is None
    assert cfg.max_tokens is None
    assert cfg.tools is None
    assert cfg.skills is None


def test_agent_config_load_missing_file(tmp_path: Path):
    """Verify loading config when file doesn't exist returns defaults."""
    agent_dir = tmp_path / "agents" / "test"
    agent_dir.mkdir(parents=True)
    cfg = AgentConfig.load(agent_dir)
    assert cfg.name == "test"
    assert cfg.enabled is True


def test_agent_config_load_from_file(tmp_path: Path):
    """Verify loading config from config.json."""
    agent_dir = tmp_path / "agents" / "custom"
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.json").write_text(json.dumps({
        "enabled": True,
        "model_id": "claude-haiku-4-5-20251001",
        "max_tokens": 4096,
        "tools": ["read_file", "write_file", "exec"],
        "skills": ["coding"],
    }), encoding="utf-8")

    cfg = AgentConfig.load(agent_dir)
    assert cfg.name == "custom"
    assert cfg.model_id == "claude-haiku-4-5-20251001"
    assert cfg.max_tokens == 4096
    assert cfg.tools == ["read_file", "write_file", "exec"]
    assert cfg.skills == ["coding"]


def test_agent_config_load_disabled(tmp_path: Path):
    """Verify disabled agent config."""
    agent_dir = tmp_path / "agents" / "disabled_agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.json").write_text(json.dumps({
        "enabled": False,
    }), encoding="utf-8")

    cfg = AgentConfig.load(agent_dir)
    assert cfg.enabled is False


def test_agent_config_load_all(tmp_path: Path):
    """Verify loading all agent configs from agents directory."""
    agents_dir = tmp_path / "agents"
    (agents_dir / "a").mkdir(parents=True)
    (agents_dir / "b").mkdir(parents=True)
    (agents_dir / "b" / "config.json").write_text(
        json.dumps({"model_id": "custom-model"}), encoding="utf-8"
    )

    configs = AgentConfig.load_all(agents_dir)
    assert "a" in configs
    assert "b" in configs
    assert configs["a"].model_id is None
    assert configs["b"].model_id == "custom-model"


def test_agent_config_invalid_json(tmp_path: Path):
    """Verify graceful handling of invalid JSON."""
    agent_dir = tmp_path / "agents" / "bad"
    agent_dir.mkdir(parents=True)
    (agent_dir / "config.json").write_text("not json", encoding="utf-8")

    cfg = AgentConfig.load(agent_dir)
    assert cfg.name == "bad"
    assert cfg.enabled is True  # Falls back to defaults


def test_provider_factory():
    """Verify provider factory creates correct provider types."""
    from ker.llm.provider_factory import create_provider
    from ker.config import Settings

    settings = Settings(
        workspace=Path("."),
        ker_root=Path(".ker"),
        model_id="test",
        anthropic_api_key="test-key",
        max_tokens=1000,
        llm_provider="anthropic",
        azure_openai_key="",
        azure_openai_endpoint="",
        github_copilot_token="",
        heartbeat_enabled=False,
        cron_enabled=False,
        delivery_enabled=False,
        kerweb_enabled=False,
        kerweb_base_url="",
        kerweb_api_key="",
        kerweb_poll_interval_sec=1.0,
        log_retention_days=30,
        debug_rebuild_snapshot_enabled=False,
        mcp_servers={},
        memory_consolidation_window=50,
        memory_max_facts=200,
        chat_history_max_entries=500,
        error_log_max_entries=1000,
    )

    from ker.llm.anthropic_provider import AnthropicProvider
    provider = create_provider(settings)
    assert isinstance(provider, AnthropicProvider)


def test_provider_factory_azure():
    """Verify provider factory creates Azure provider."""
    from ker.llm.provider_factory import create_provider
    from ker.config import Settings
    from ker.llm.azure_openai import AzureOpenAIProvider

    settings = Settings(
        workspace=Path("."),
        ker_root=Path(".ker"),
        model_id="test",
        anthropic_api_key="",
        max_tokens=1000,
        llm_provider="azure",
        azure_openai_key="key",
        azure_openai_endpoint="https://test.openai.azure.com",
        github_copilot_token="",
        heartbeat_enabled=False,
        cron_enabled=False,
        delivery_enabled=False,
        kerweb_enabled=False,
        kerweb_base_url="",
        kerweb_api_key="",
        kerweb_poll_interval_sec=1.0,
        log_retention_days=30,
        debug_rebuild_snapshot_enabled=False,
        mcp_servers={},
        memory_consolidation_window=50,
        memory_max_facts=200,
        chat_history_max_entries=500,
        error_log_max_entries=1000,
    )

    provider = create_provider(settings)
    assert isinstance(provider, AzureOpenAIProvider)
