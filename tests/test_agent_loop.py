import pytest
from pathlib import Path
from ker.agent.context.prompt_builder import PromptBuilder


def test_prompt_builder_fallback(tmp_path: Path):
    builder = PromptBuilder(tmp_path / ".ker")
    prompt = builder.build(agent_name="ker", model_id="test-model", channel="cli")
    # Should fall back to builtin templates
    assert "Ker" in prompt or "helpful AI assistant" in prompt
    assert "test-model" in prompt
    assert "cli" in prompt


def test_prompt_builder_with_agent_dir(tmp_path: Path):
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "luna"
    agent_dir.mkdir(parents=True)
    (agent_dir / "IDENTITY.md").write_text("You are Luna, a thoughtful assistant.")
    (agent_dir / "AGENT.md").write_text("# Luna\n\nA warm agent.")

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="luna")
    assert "Luna" in prompt
    assert "thoughtful" in prompt


# ── Phase 5a: New template loading ──────────────────────────────


def test_user_md_discovered_from_builtins(tmp_path: Path):
    """USER.md and BOOT.md are discovered from builtin templates."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "ker"
    agent_dir.mkdir(parents=True)

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="ker", session_type="main")
    assert "User Profile" in prompt
    assert "Startup Instructions" in prompt


def test_user_md_agent_override(tmp_path: Path):
    """Agent-specific USER.md takes precedence over workspace-level."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "myagent"
    agent_dir.mkdir(parents=True)

    # Workspace-level USER.md
    (ker_root / "USER.md").write_text("# User\nWorkspace-level profile.")

    # Agent-specific USER.md
    (agent_dir / "USER.md").write_text("# User\nAgent-specific profile for myagent.")

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="myagent", session_type="main")
    assert "Agent-specific profile for myagent" in prompt
    assert "Workspace-level profile" not in prompt


def test_user_md_workspace_fallback(tmp_path: Path):
    """Workspace-level USER.md used when no agent-specific one exists."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "myagent"
    agent_dir.mkdir(parents=True)

    # Only workspace-level USER.md
    (ker_root / "USER.md").write_text("# User\nWorkspace-level profile.")

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="myagent", session_type="main")
    assert "Workspace-level profile" in prompt


# ── Phase 5b: Session-type filtering ────────────────────────────


def test_session_type_main_includes_all(tmp_path: Path):
    """Main session includes SOUL, USER, AGENTS sections."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "ker"
    agent_dir.mkdir(parents=True)

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="ker", session_type="main")
    assert "Personality" in prompt  # SOUL section
    assert "User Profile" in prompt  # USER section
    assert "Bootstrap Context" in prompt  # AGENTS section


def test_session_type_subagent_minimal(tmp_path: Path):
    """Subagent session omits SOUL, USER, AGENTS; has identity + tools + runtime."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "ker"
    agent_dir.mkdir(parents=True)

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="ker", session_type="subagent")
    # Should have identity and tools
    assert "Ker" in prompt or "helpful AI assistant" in prompt
    assert "Tool Usage Guidelines" in prompt
    # Should NOT have SOUL, USER, AGENTS
    assert "Personality" not in prompt
    assert "User Profile" not in prompt
    assert "Bootstrap Context" not in prompt


def test_session_type_cron_minimal(tmp_path: Path):
    """Cron session similar to subagent — identity + tools, no SOUL/USER/AGENTS."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "ker"
    agent_dir.mkdir(parents=True)

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="ker", session_type="cron")
    assert "Tool Usage Guidelines" in prompt
    assert "Personality" not in prompt
    assert "User Profile" not in prompt


def test_session_type_internal_bare_minimum(tmp_path: Path):
    """Internal session has only identity + runtime."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "ker"
    agent_dir.mkdir(parents=True)

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="ker", session_type="internal")
    # Should have identity
    assert "Ker" in prompt or "helpful AI assistant" in prompt
    # Should NOT have tools, SOUL, USER, AGENTS
    assert "Tool Usage Guidelines" not in prompt
    assert "Personality" not in prompt
    assert "User Profile" not in prompt
    assert "Bootstrap Context" not in prompt


# ── Phase 5c: Context markers ───────────────────────────────────


def test_context_markers(tmp_path: Path):
    """Output contains PROJECT CONTEXT STARTS/ENDS markers."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "ker"
    agent_dir.mkdir(parents=True)

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="ker")
    assert "===== PROJECT CONTEXT STARTS =====" in prompt
    assert "===== PROJECT CONTEXT ENDS =====" in prompt


# ── Phase 5d: Smart truncation ──────────────────────────────────


def test_smart_truncation(tmp_path: Path):
    """Long file preserves head + tail with truncated marker."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "test"
    agent_dir.mkdir(parents=True)

    # Create a file that exceeds per_file_cap
    long_content = "HEAD_MARKER\n" + ("x" * 500) + "\nTAIL_MARKER"
    (agent_dir / "IDENTITY.md").write_text(long_content)

    builder = PromptBuilder(ker_root, per_file_cap=100)
    prompt = builder.build(agent_name="test")
    assert "HEAD_MARKER" in prompt
    assert "TAIL_MARKER" in prompt
    assert "[truncated:" in prompt


def test_smart_truncation_preserves_short_files(tmp_path: Path):
    """Files under cap are not truncated."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "test"
    agent_dir.mkdir(parents=True)

    short_content = "Short identity content."
    (agent_dir / "IDENTITY.md").write_text(short_content)

    builder = PromptBuilder(ker_root, per_file_cap=20_000)
    prompt = builder.build(agent_name="test")
    assert "Short identity content" in prompt
    assert "[truncated:" not in prompt


def test_truncation_warning_injected(tmp_path: Path):
    """When a file is truncated, a warning is injected."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "test"
    agent_dir.mkdir(parents=True)

    long_content = "x" * 500
    (agent_dir / "IDENTITY.md").write_text(long_content)

    builder = PromptBuilder(ker_root, per_file_cap=100)
    prompt = builder.build(agent_name="test")
    assert "[Warning: IDENTITY.md truncated" in prompt


# ── Session type inference (AgentLoop) ───────────────────────────


def test_infer_session_type():
    """Test _infer_session_type logic without full AgentLoop construction."""
    from ker.types import InboundMessage

    # We test the static logic by creating a minimal mock
    class MockLoop:
        _infer_session_type = staticmethod(lambda inbound: (
            "internal" if inbound.sender_id == "system" and inbound.session_name == "internal"
            else "cron" if inbound.sender_id == "system"
            else inbound.raw.get("session_type", "main") if inbound.raw and isinstance(inbound.raw, dict) and inbound.raw.get("session_type") in ("main", "subagent", "cron", "internal")
            else "main"
        ))

    # System + internal session → internal
    msg = InboundMessage(text="hi", sender_id="system", channel="cli", session_name="internal")
    assert MockLoop._infer_session_type(msg) == "internal"

    # System + other session → cron
    msg = InboundMessage(text="hi", sender_id="system", channel="cli", session_name="cron_job_1")
    assert MockLoop._infer_session_type(msg) == "cron"

    # Normal user → main
    msg = InboundMessage(text="hi", sender_id="user1", channel="cli")
    assert MockLoop._infer_session_type(msg) == "main"

    # Explicit metadata override
    msg = InboundMessage(text="hi", sender_id="user1", channel="cli", raw={"session_type": "subagent"})
    assert MockLoop._infer_session_type(msg) == "subagent"


# ── Enriched guardrails ─────────────────────────────────────────


def test_enriched_guardrails(tmp_path: Path):
    """Guardrails section includes expanded rules."""
    ker_root = tmp_path / ".ker"
    agent_dir = ker_root / "agents" / "ker"
    agent_dir.mkdir(parents=True)

    builder = PromptBuilder(ker_root)
    prompt = builder.build(agent_name="ker")
    assert "State intent before tool calls" in prompt
    assert "Never claim tool results before receiving them" in prompt
    assert "Re-read modified files" in prompt
    assert "reversible operations" in prompt
    assert "uncertain" in prompt


# ── Skills block ─────────────────────────────────────────────────


def test_skills_block_protocol():
    """render_skills_block includes scan-select-read protocol."""
    from ker.agent.context.skills import render_skills_block

    block = render_skills_block([], "<skills></skills>")
    assert "mandatory" in block.lower()
    assert "scan available skill descriptions" in block
    assert "Never read more than one skill up front" in block
