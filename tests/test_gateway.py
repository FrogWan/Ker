import io
from contextlib import redirect_stdout
from pathlib import Path

from ker.config import Settings
from ker.gateway.commands import dispatch_command
from ker.gateway.gateway import Gateway
from ker.types import InboundMessage


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace=tmp_path,
        ker_root=tmp_path / ".ker",
        model_id="test-model",
        anthropic_api_key="",
        max_tokens=1024,
        llm_provider="anthropic",
        azure_openai_key="",
        azure_openai_endpoint="",
        github_copilot_token="",
        heartbeat_enabled=False,
        cron_enabled=False,
        delivery_enabled=False,
        kerweb_enabled=False,
        kerweb_base_url="http://localhost:3000",
        kerweb_api_key="",
        kerweb_poll_interval_sec=1.0,
        log_retention_days=30,
        debug_rebuild_snapshot_enabled=False,
        mcp_servers={},
        memory_consolidation_window=50,
    )


def test_gateway_discover_agents(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    agents = gw.discover_agents()
    assert "ker" in agents
    assert (tmp_path / ".ker" / "agents" / "ker" / "AGENT.md").exists()
    assert (tmp_path / ".ker" / "agents" / "ker" / "IDENTITY.md").exists()


def test_gateway_custom_agent(tmp_path: Path):
    settings = _make_settings(tmp_path)
    (tmp_path / ".ker" / "agents" / "luna").mkdir(parents=True)
    (tmp_path / ".ker" / "agents" / "luna" / "AGENT.md").write_text("# Luna\n")

    gw = Gateway(settings)
    agents = gw.discover_agents()
    assert "ker" in agents
    assert "luna" in agents
    # IDENTITY.md should be created for custom agents too
    assert (tmp_path / ".ker" / "agents" / "luna" / "IDENTITY.md").exists()


def test_gateway_identity_not_overwritten(tmp_path: Path):
    """discover_agents must not overwrite an existing IDENTITY.md."""
    settings = _make_settings(tmp_path)
    (tmp_path / ".ker" / "agents" / "ker").mkdir(parents=True)
    identity = tmp_path / ".ker" / "agents" / "ker" / "IDENTITY.md"
    identity.write_text("# Custom Identity\n", encoding="utf-8")

    gw = Gateway(settings)
    gw.discover_agents()
    assert identity.read_text(encoding="utf-8") == "# Custom Identity\n"


def test_gateway_session_id(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    inbound = InboundMessage(text="test", sender_id="user1", channel="cli", user="user1", session_name="main")
    session_id = gw._build_session_id(inbound)
    assert session_id == "cli_user1_main"


def test_build_session_id_sanitizes_bad_name(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    inbound = InboundMessage(text="test", sender_id="u", channel="cli", user="u", session_name="my/bad:name")
    session_id = gw._build_session_id(inbound)
    assert session_id == "cli_u_my-bad-name"


def _run_command(gw: Gateway, text: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        dispatch_command(gw, text)
    return buf.getvalue()


def test_cmd_new_bad_chars(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    gw.discover_agents()
    output = _run_command(gw, "/new my/bad:name")
    assert "warning" in output
    assert "my-bad-name" in output
    assert gw.current_session == "my-bad-name"


def test_cmd_new_clean_name(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    gw.discover_agents()
    output = _run_command(gw, "/new clean-name")
    assert "warning" not in output
    assert gw.current_session == "clean-name"


def test_cmd_switch_with_spaces(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    gw.discover_agents()
    output = _run_command(gw, "/switch my session")
    assert "warning" in output
    assert gw.current_session == "my-session"


def test_cmd_rename_bad_chars(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    gw.discover_agents()
    gw.current_session = "old"
    output = _run_command(gw, "/rename new<>name")
    assert "warning" in output
    assert gw.current_session == "new-name"
    assert "old -> new-name" in output


def test_build_agents_info_has_session_validation(tmp_path: Path):
    settings = _make_settings(tmp_path)
    gw = Gateway(settings)
    gw.discover_agents()
    info = gw._build_agents_info()
    assert "sessionValidation" in info
    assert info["sessionValidation"]["maxLength"] == 64
    assert "pattern" in info["sessionValidation"]
    assert "allowedChars" in info["sessionValidation"]
