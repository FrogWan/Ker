from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path

from ker.agent.agent_config import AgentConfig
from ker.agent.agent_loop import AgentLoop, TurnResult
from ker.agent.context.chat_history import ChatHistory
from ker.agent.context.context_guard import ContextGuard
from ker.agent.context.memory import MemoryStore
from ker.agent.context.prompt_builder import PromptBuilder
from ker.agent.context.working_memory import WorkingMemoryManager
from ker.agent.context.session import (
    SESSION_NAME_ALLOWED_CHARS_DESC,
    SESSION_NAME_MAX_LENGTH,
    SESSION_NAME_PATTERN,
    SessionStore,
    sanitize_session_name,
)
from ker.agent.context.skills import SkillsManager
from ker.agent.subagent import SubagentManager
from ker.channels.base import AsyncChannel
from ker.config import Settings
from ker.gateway.commands import dispatch_command
from ker.llm.base import LLMProvider
from ker.llm.provider_factory import create_provider
from ker.logger import get_logger
from ker.scheduler.cron import CronService
from ker.scheduler.heartbeat import HeartbeatRunner
from ker.tools.tool_base import ToolContext
from ker.tools.tool_registry import ToolRegistry
from ker.types import InboundMessage, OutboundMessage

log = get_logger("gateway")


class _ExitRequested(Exception):
    """Sentinel raised when /exit is received during a running turn."""


class Gateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ker_root.mkdir(parents=True, exist_ok=True)

        self.inbound_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self.channels: dict[str, AsyncChannel] = {}
        self.agents: list[str] = []
        self.agent_configs: dict[str, AgentConfig] = {}

        # Core services
        self.session_store = SessionStore(settings.ker_root)
        self.chat_history = ChatHistory(settings.ker_root)
        self.memory_store = MemoryStore(settings.workspace, settings.ker_root)
        self.prompt_builder = PromptBuilder(settings.ker_root)

        builtin_skills = Path(__file__).resolve().parents[1] / "skills"
        skill_roots = [settings.workspace / ".skills", builtin_skills, Path.home() / ".codex" / "skills"]
        self.skills_manager = SkillsManager(skill_roots, workspace=settings.workspace, ker_root=settings.ker_root)

        self.context_guard = ContextGuard()
        self.working_memory = WorkingMemoryManager(settings.ker_root)

        # LLM provider
        self.provider: LLMProvider = create_provider(settings)

        # Subagent manager
        self.subagents = SubagentManager(run_prompt=self._run_internal_prompt)

        # Cron service (must be created before ToolContext so it can be wired in)
        self.cron = CronService(
            workspace=settings.workspace,
            ker_root=settings.ker_root,
            run_payload=self._run_cron_payload,
        )

        # Tool registry
        self.tool_ctx = ToolContext(
            workspace=settings.workspace,
            ker_root=settings.ker_root,
            memory_store=self.memory_store,
            working_memory=self.working_memory,
            skills_manager=self.skills_manager,
            subagent_manager=self.subagents,
            cron_service=self.cron,
            outbound_queue=self.outbound_queue,
        )
        self.tool_registry = ToolRegistry(self.tool_ctx)
        self._mcp_stack = AsyncExitStack()

        # Heartbeat
        self.heartbeat = HeartbeatRunner(
            ker_root=settings.ker_root,
            run_once=self._run_internal_prompt,
        )

        # Agent loop
        self.agent_loop = AgentLoop(
            provider=self.provider,
            session_store=self.session_store,
            chat_history=self.chat_history,
            memory_store=self.memory_store,
            prompt_builder=self.prompt_builder,
            skills_manager=self.skills_manager,
            context_guard=self.context_guard,
            tool_schemas=self.tool_registry.schemas,
            tool_execute=self.tool_registry.execute,
            model_id=settings.model_id,
            max_tokens=settings.max_tokens,
            ker_root=settings.ker_root,
            working_memory=self.working_memory,
            consolidation_interval=settings.memory_consolidation_window,
        )

        # Current session state
        self.current_session = "default"
        self.force_agent: str | None = None

        # Stop support: track the running turn task so /stop can cancel it
        self._current_turn_task: asyncio.Task | None = None
        self._current_turn_inbound: InboundMessage | None = None

    def register_channel(self, channel: AsyncChannel) -> None:
        self.channels[channel.name] = channel

    def discover_agents(self) -> list[str]:
        agents_dir = self.settings.ker_root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        # Ensure default agent exists
        default_dir = agents_dir / "ker"
        if not default_dir.exists():
            default_dir.mkdir(parents=True, exist_ok=True)
            (default_dir / "AGENT.md").write_text(
                "# Ker\n\n"
                "Default agent. Direct, pragmatic, and engineering-focused.\n\n"
                "## Approach\n"
                "- Read before writing. Understand context before changing it.\n"
                "- State intent before acting. Explain what you'll do, then do it.\n"
                "- Prefer small, targeted changes over sweeping rewrites.\n"
                "- Verify your work. Re-read files after editing when correctness matters.\n"
                "- If something fails, analyze before retrying — don't loop on the same error.\n\n"
                "## Communication\n"
                "- Be concise but complete. Lead with the answer, then explain.\n"
                "- Admit uncertainty explicitly rather than guessing confidently.\n"
                "- Use code examples over prose when demonstrating.\n"
                "- Summarize tool output — don't dump raw results unless asked.\n\n"
                "## Workspace\n"
                "- State is stored under `.ker/` in the project root.\n"
                "- Daily memory captures context across sessions.\n"
                "- Use `read_memory` for history and context.\n"
                "- Skills encode specialized workflows — scan them before starting tasks.\n",
                encoding="utf-8",
            )

        # Load per-agent configs
        self.agent_configs = AgentConfig.load_all(agents_dir)

        # Build active agents list (skip disabled)
        all_names = sorted(d.name for d in agents_dir.iterdir() if d.is_dir())
        self.agents = [
            name for name in all_names
            if self.agent_configs.get(name, AgentConfig(name=name)).enabled
        ]

        # Ensure every agent directory has an IDENTITY.md
        for name in self.agents:
            identity_file = agents_dir / name / "IDENTITY.md"
            if not identity_file.exists():
                identity_file.write_text(
                    "# Identity\n\nDefine the agent's personality and communication style.\n",
                    encoding="utf-8",
                )

        log.info("Discovered agents: %s", self.agents)
        return self.agents

    def list_sessions(self, agent_name: str) -> list[str]:
        """Return unique session names for an agent by scanning session files."""
        session_dir = self.settings.ker_root / "agents" / agent_name / "session"
        if not session_dir.exists():
            return ["default"]
        names: set[str] = set()
        for f in session_dir.iterdir():
            if f.suffix == ".jsonl":
                # session files are named: {channel}_{user}_{session_name}.jsonl
                parts = f.stem.split("_", 2)
                if len(parts) >= 3:
                    names.add(parts[2])
        return sorted(names) if names else ["default"]

    def _resolve_agent(self, inbound: InboundMessage) -> str:
        if self.force_agent:
            return self.force_agent
        agent_hint = (inbound.raw or {}).get("agent", "")
        if agent_hint and agent_hint in self.agents:
            return agent_hint
        return "ker"

    def _build_session_id(self, inbound: InboundMessage) -> str:
        channel = inbound.channel or "cli"
        user = inbound.user or "cli-user"
        session = sanitize_session_name(inbound.session_name or self.current_session)
        return f"{channel}_{user}_{session}"

    def _build_agents_info(self) -> dict:
        """Build the agents-info payload for frontends."""
        return {
            "agents": self.agents,
            "sessions": {name: self.list_sessions(name) for name in self.agents},
            "currentAgent": self.force_agent or "ker",
            "currentSession": self.current_session,
            "sessionValidation": {
                "maxLength": SESSION_NAME_MAX_LENGTH,
                "pattern": SESSION_NAME_PATTERN,
                "allowedChars": SESSION_NAME_ALLOWED_CHARS_DESC,
            },
        }

    async def _run_internal_prompt(self, prompt: str) -> str:
        inbound = InboundMessage(
            text=prompt, sender_id="system", channel="cli", user="system", session_name="internal"
        )
        agent_name = self._resolve_agent(inbound)
        session_id = self._build_session_id(inbound)
        self.tool_ctx.agent_name = agent_name
        self.tool_ctx.session_name = session_id
        self.tool_ctx.current_channel = "cli"
        self.tool_ctx.current_user = "system"
        agent_config = self.agent_configs.get(agent_name)
        result = await self.agent_loop.run_turn(inbound, agent_name, session_id, agent_config=agent_config)
        return result.text

    async def _run_cron_payload(self, payload: dict) -> str:
        message = str(payload.get("message", ""))
        result = await self._run_internal_prompt(message)

        # Deliver result to specified channel/user if requested
        if payload.get("deliver"):
            channel = payload.get("channel", "cli")
            user = payload.get("to", "system")
            await self.outbound_queue.put(
                OutboundMessage(text=result, channel=channel, user=user)
            )

        return result

    async def _inbound_processor(self) -> None:
        while True:
            inbound = await self.inbound_queue.get()
            try:
                text = inbound.text.strip()
                log.info(
                    "Received message: channel=%s user=%s text=%s",
                    inbound.channel, inbound.user, text[:80],
                )
                if text in ("/exit", "quit", "exit"):
                    log.info("Exit command received")
                    break

                # Handle slash commands
                if text.startswith("/"):
                    import io
                    from contextlib import redirect_stdout

                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        handled = dispatch_command(self, text)
                    output = buf.getvalue().strip()
                    if handled:
                        if output:
                            await self.outbound_queue.put(
                                OutboundMessage(
                                    text=output,
                                    channel=inbound.channel,
                                    user=inbound.user or "cli-user",
                                    session_name=inbound.session_name,
                                )
                            )
                        # Push updated agents-info after session-changing commands
                        if text.startswith(("/new ", "/switch ", "/rename ", "/switch-agent ")):
                            agents_info = self._build_agents_info()
                            for ch in self.channels.values():
                                try:
                                    await ch.push_agents_info(agents_info)
                                except Exception:
                                    pass
                        continue

                # Set context for tool execution
                agent_name = self._resolve_agent(inbound)
                session_id = self._build_session_id(inbound)
                self.tool_ctx.agent_name = agent_name
                self.tool_ctx.session_name = session_id
                self.tool_ctx.current_channel = inbound.channel
                self.tool_ctx.current_user = inbound.user or "cli-user"

                # Update channel agent/session context (use user-facing session
                # name, not the internal session_id, so KerWeb SSE routing matches)
                for ch in self.channels.values():
                    if hasattr(ch, "current_agent"):
                        ch.current_agent = agent_name
                        ch.current_session = inbound.session_name or self.current_session

                # Broadcast job start
                job_text = f"Processing: {text[:60]}"
                for ch in self.channels.values():
                    await ch.update_job(inbound.user or "cli-user", job_text)
                    await ch.clear_tool_logs()

                # Thinking callback for channels that support it
                async def thinking_cb(status: str) -> None:
                    for ch in self.channels.values():
                        await ch.thinking(status)
                        # Track tool-log events from thinking status
                        if status.startswith("Running tool: "):
                            tool_name = status[len("Running tool: "):]
                            await ch.append_tool_log(tool_name, "running")
                        elif status.startswith("Tool complete: "):
                            tool_name = status[len("Tool complete: "):]
                            await ch.append_tool_log(tool_name, "done")

                log.info("Starting turn: agent=%s session=%s", agent_name, session_id)
                agent_config = self.agent_configs.get(agent_name)
                self._current_turn_inbound = inbound
                self._current_turn_task = asyncio.create_task(
                    self.agent_loop.run_turn(
                        inbound, agent_name, session_id,
                        thinking_callback=lambda s: asyncio.ensure_future(thinking_cb(s)),
                        agent_config=agent_config,
                    )
                )
                await self._await_turn_or_command()
            except _ExitRequested:
                log.info("Exit requested during running turn")
                break
            except Exception as exc:
                log.error(
                    "Turn failed: channel=%s user=%s agent=%s error=%s",
                    inbound.channel, inbound.user,
                    getattr(self, '_last_agent', '?'), exc,
                )
                self.memory_store.add_error(
                    source="gateway",
                    message=str(exc),
                    context={"text": inbound.text[:100], "channel": inbound.channel, "user": inbound.user},
                )
                await self.outbound_queue.put(
                    OutboundMessage(
                        text=f"Error: {exc}",
                        channel=inbound.channel,
                        user=inbound.user or "cli-user",
                    )
                )

    async def _await_turn_or_command(self) -> None:
        """Wait for the current turn task, but also listen for queue items
        (like /stop or /exit) so the user can interrupt a running turn."""
        task = self._current_turn_task
        assert task is not None
        inbound = self._current_turn_inbound
        assert inbound is not None

        pending_get: asyncio.Task | None = None
        try:
            while not task.done():
                if pending_get is None:
                    pending_get = asyncio.create_task(self.inbound_queue.get())
                done, _ = await asyncio.wait(
                    {task, pending_get}, return_when=asyncio.FIRST_COMPLETED
                )
                if pending_get in done:
                    new_msg: InboundMessage = pending_get.result()
                    pending_get = None
                    new_text = new_msg.text.strip()

                    if new_text == "/stop":
                        await self._handle_stop(new_msg)
                        return
                    elif new_text in ("/exit", "quit", "exit"):
                        await self._handle_stop(new_msg)
                        raise _ExitRequested()
                    elif new_text.startswith("/"):
                        # Dispatch read-only commands while turn runs
                        import io
                        from contextlib import redirect_stdout

                        buf = io.StringIO()
                        with redirect_stdout(buf):
                            handled = dispatch_command(self, new_text)
                        output = buf.getvalue().strip()
                        if handled and output:
                            await self.outbound_queue.put(
                                OutboundMessage(
                                    text=output,
                                    channel=new_msg.channel,
                                    user=new_msg.user or "cli-user",
                                    session_name=new_msg.session_name,
                                )
                            )
                    else:
                        await self.outbound_queue.put(
                            OutboundMessage(
                                text="Agent is busy. Use /stop to cancel.",
                                channel=new_msg.channel,
                                user=new_msg.user or "cli-user",
                                session_name=new_msg.session_name,
                            )
                        )
        finally:
            if pending_get is not None and not pending_get.done():
                pending_get.cancel()
            self._current_turn_task = None
            self._current_turn_inbound = None

        # Turn completed normally — process the result
        result = task.result()
        log.info(
            "Turn completed: agent=%s text_len=%d",
            result.agent_name, len(result.text),
        )

        # Broadcast job idle
        for ch in self.channels.values():
            await ch.update_job(inbound.user or "cli-user", None)

        await self.outbound_queue.put(
            OutboundMessage(
                text=result.text,
                channel=inbound.channel,
                user=inbound.user or "cli-user",
                session_name=inbound.session_name,
            )
        )

    async def _handle_stop(self, stop_msg: InboundMessage) -> None:
        """Cancel the current turn task and notify the user."""
        task = self._current_turn_task
        if task is None or task.done():
            return
        log.info("Stop requested: cancelling current turn")
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        # Clear job status
        if self._current_turn_inbound:
            for ch in self.channels.values():
                await ch.update_job(self._current_turn_inbound.user or "cli-user", None)
        # Notify user
        await self.outbound_queue.put(
            OutboundMessage(
                text="Agent stopped.",
                channel=stop_msg.channel,
                user=stop_msg.user or "cli-user",
                session_name=stop_msg.session_name,
            )
        )

    async def _outbound_processor(self) -> None:
        while True:
            outbound = await self.outbound_queue.get()
            channel = self.channels.get(outbound.channel)
            media_kw = {"media": outbound.media} if outbound.media else {}
            if channel:
                await channel.send(outbound.user, outbound.text, **media_kw)
            else:
                # Fallback: send to all channels
                for ch in self.channels.values():
                    await ch.send(outbound.user, outbound.text, **media_kw)

    async def _cron_ticker(self) -> None:
        if not self.settings.cron_enabled:
            return
        self.cron.start()
        while True:
            await self.cron.tick()
            await asyncio.sleep(1)

    async def _heartbeat_ticker(self) -> None:
        if not self.settings.heartbeat_enabled:
            return
        self.heartbeat.start()
        while True:
            outputs = await self.heartbeat.run_tick()
            for text in outputs:
                await self.outbound_queue.put(
                    OutboundMessage(text=f"[heartbeat] {text}", channel="cli", user="system")
                )
            await asyncio.sleep(1)

    async def _telemetry_publisher(self) -> None:
        while True:
            await asyncio.sleep(10)
            telemetry = {
                "heartbeat": {
                    "enabled": self.settings.heartbeat_enabled,
                    "running": self.heartbeat.running,
                    "interval": self.heartbeat.interval,
                    "last_run_at": self.heartbeat.last_run_at,
                },
                "cron": {
                    "job_count": len(self.cron.jobs),
                },
                "subagents": {
                    "running": self.subagents.get_running_count(),
                },
            }
            for ch in self.channels.values():
                try:
                    await ch.publish_telemetry("system", telemetry)
                except Exception:
                    pass

            # Publish agents-info for multi-agent/session management
            agents_info = self._build_agents_info()
            for ch in self.channels.values():
                try:
                    await ch.push_agents_info(agents_info)
                except Exception:
                    pass

    async def _subagent_poller(self) -> None:
        while True:
            results = self.subagents.poll_results()
            for result in results:
                status_text = "completed" if result.status == "ok" else "failed"
                await self.outbound_queue.put(
                    OutboundMessage(
                        text=f"[Subagent '{result.label}' {status_text}] {result.result}",
                        channel=result.channel,
                        user=result.user,
                    )
                )
            await asyncio.sleep(1)

    def _ensure_evolution_cron(self) -> None:
        """Create the self-evolve cron job if enabled and not already registered."""
        from ker.tools.tool_evolve import (
            DEFAULT_CONFIG,
            JOB_NAME,
            _config_path,
            _evolve_prompt,
            _read_config,
            _write_config,
        )

        # Ensure config exists
        cfg_path = _config_path(self.tool_ctx)
        if not cfg_path.exists():
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            _write_config(self.tool_ctx, dict(DEFAULT_CONFIG))

        cfg = _read_config(self.tool_ctx)
        if not cfg.get("enabled", True):
            return

        # Check if job already exists
        for j in self.cron.list_jobs(include_disabled=True):
            if j.name == JOB_NAME:
                return

        prompt = _evolve_prompt(self.tool_ctx)
        self.cron.add_job(
            name=JOB_NAME,
            schedule_kind="cron",
            schedule_config={"kind": "cron", "expr": cfg.get("cron_expr", "0 3 * * *")},
            payload={
                "kind": "agent_turn",
                "message": prompt,
                "deliver": False,
            },
        )
        log.info("Self-evolution cron job created (schedule: %s)", cfg.get("cron_expr"))

    async def run(self) -> None:
        self.discover_agents()

        # Ensure HEARTBEAT.md template exists so heartbeat can run
        heartbeat_path = self.settings.ker_root / "templates" / "HEARTBEAT.md"
        if not heartbeat_path.exists():
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            heartbeat_path.write_text(
                "# Heartbeat Tasks\n\n"
                "Checked periodically by Ker. Add tasks you want the agent to work on.\n\n"
                "## Active Tasks\n<!-- Add periodic tasks below -->\n\n"
                "## Completed\n<!-- Move completed tasks here -->\n",
                encoding="utf-8",
            )

        # Run memory consolidation on startup
        try:
            await self.memory_store.auto_consolidate()
        except Exception as exc:
            log.warning("Startup consolidation failed: %s", exc)

        # Bootstrap self-evolution cron job
        self._ensure_evolution_cron()

        # Connect MCP servers (dynamically registers tools)
        if self.settings.mcp_servers:
            from ker.tools.tool_mcp import connect_mcp_servers

            await connect_mcp_servers(
                self.settings.mcp_servers, self.tool_registry, self._mcp_stack
            )
            # Update agent loop schemas to include dynamically registered MCP tools
            self.agent_loop.tool_schemas = self.tool_registry.schemas

        # Push initial agents-info immediately so frontends don't wait for
        # the first telemetry tick (10 s delay).
        agents_info = self._build_agents_info()
        for ch in self.channels.values():
            try:
                await ch.push_agents_info(agents_info)
            except Exception:
                pass

        # Start channel listeners
        listeners = []
        for channel in self.channels.values():
            listeners.append(asyncio.create_task(channel.listen(self.inbound_queue)))

        # Start background processors
        tasks = [
            asyncio.create_task(self._outbound_processor()),
            asyncio.create_task(self._cron_ticker()),
            asyncio.create_task(self._heartbeat_ticker()),
            asyncio.create_task(self._subagent_poller()),
            asyncio.create_task(self._telemetry_publisher()),
            *listeners,
        ]

        try:
            await self._inbound_processor()
        finally:
            for t in tasks:
                t.cancel()
            self.cron.stop()
            await self._mcp_stack.aclose()
            log.info("Gateway shutdown complete")
