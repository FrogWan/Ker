from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pathlib import Path

from ker.agent.agent_config import AgentConfig
from ker.agent.context.chat_history import ChatHistory
from ker.agent.context.context_guard import ContextGuard
from ker.agent.context.memory import MemoryStore
from ker.agent.context.prompt_builder import PromptBuilder
from ker.agent.context.session import SessionStore
from ker.agent.context.skills import SkillsManager, render_skills_block
from ker.llm.base import LLMProvider
from ker.logger import get_logger
from ker.media import load_media_base64
from ker.types import InboundMessage, ProviderResponse

log = get_logger("agent_loop")


@dataclass
class TurnResult:
    text: str
    agent_name: str
    session_id: str


class AgentLoop:
    def __init__(
        self,
        provider: LLMProvider,
        session_store: SessionStore,
        chat_history: ChatHistory,
        memory_store: MemoryStore,
        prompt_builder: PromptBuilder,
        skills_manager: SkillsManager,
        context_guard: ContextGuard,
        tool_schemas: list[dict[str, Any]],
        tool_execute: Callable[[str, dict[str, Any]], Awaitable[str]],
        model_id: str,
        max_tokens: int,
        max_tool_iterations: int = 120,
        turn_timeout: float = 600.0,
        ker_root: Path | None = None,
    ) -> None:
        self.provider = provider
        self.session_store = session_store
        self.ker_root = ker_root
        self.chat_history = chat_history
        self.memory_store = memory_store
        self.prompt_builder = prompt_builder
        self.skills_manager = skills_manager
        self.context_guard = context_guard
        self.tool_schemas = tool_schemas
        self.tool_execute = tool_execute
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.max_tool_iterations = max_tool_iterations
        self.turn_timeout = turn_timeout

    def _infer_session_type(self, inbound: InboundMessage) -> str:
        """Infer session type from inbound message metadata."""
        # Explicit metadata override
        if inbound.raw and isinstance(inbound.raw, dict):
            explicit = inbound.raw.get("session_type", "")
            if explicit in ("main", "subagent", "cron", "internal"):
                return explicit

        # System-originated messages
        if inbound.sender_id == "system":
            if inbound.session_name == "internal":
                return "internal"
            return "cron"

        return "main"

    async def run_turn(
        self,
        inbound: InboundMessage,
        agent_name: str,
        session_id: str,
        thinking_callback: Callable[[str], Any] | None = None,
        agent_config: AgentConfig | None = None,
    ) -> TurnResult:
        import time as _time
        _turn_start = _time.monotonic()
        log.info(
            "run_turn START: agent=%s session=%s channel=%s text=%s",
            agent_name, session_id, inbound.channel, (inbound.text or "")[:80],
        )

        # Load session history
        messages = self.session_store.load_messages(agent_name, session_id)
        log.info("Loaded %d session messages", len(messages))

        # Build user message — with image content blocks if media attached
        if inbound.media and self.ker_root:
            content_blocks = []
            if inbound.text:
                content_blocks.append({"type": "text", "text": inbound.text})
            for m in inbound.media:
                b64 = load_media_base64(self.ker_root, m)
                if b64:
                    content_blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": m["media_type"], "data": b64},
                    })
            user_content = content_blocks if content_blocks else (inbound.text or "(image failed to load)")
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": inbound.text})

        self.session_store.append_user(agent_name, session_id, inbound.text, media=inbound.media or None)

        # Per-agent model override
        model_id = self.model_id
        max_tokens = self.max_tokens
        if agent_config:
            if agent_config.model_id:
                model_id = agent_config.model_id
            if agent_config.max_tokens:
                max_tokens = agent_config.max_tokens

        # Per-agent tool filtering
        tool_schemas = self.tool_schemas
        if agent_config and agent_config.tools is not None:
            allowed = set(agent_config.tools)
            tool_schemas = [s for s in self.tool_schemas if s.get("name") in allowed]

        # Infer session type
        session_type = self._infer_session_type(inbound)

        # Build system prompt
        memory_context = self._auto_recall(inbound.text, agent_name)
        always_names = self.skills_manager.get_always_skills(agent_name=agent_name)
        active = [s for s in self.skills_manager.discover(filter_unavailable=True, agent_name=agent_name) if s.name in always_names]
        summary_xml = self.skills_manager.render_skills_summary_xml(agent_name=agent_name)
        skills_block = render_skills_block(active, summary_xml)

        system_prompt = self.prompt_builder.build(
            agent_name=agent_name,
            skills_block=skills_block,
            memory_context=memory_context,
            model_id=model_id,
            channel=inbound.channel,
            session_name=inbound.session_name,
            session_type=session_type,
        )
        log.info(
            "System prompt built: len=%d tools=%d model=%s",
            len(system_prompt), len(tool_schemas), model_id,
        )

        # Run model loop — turn_timeout covers the ENTIRE loop (LLM + tools)
        try:
            if thinking_callback:
                thinking_callback("Preparing context and system prompt")

            original_count = len(messages)
            try:
                response, updated_messages = await asyncio.wait_for(
                    self._run_model_loop(
                        system_prompt, messages, tool_schemas, thinking_callback,
                        model_id=model_id, max_tokens=max_tokens,
                    ),
                    timeout=self.turn_timeout,
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"Turn timed out after {self.turn_timeout:.0f}s (LLM + tool execution)"
                )
            text = self._extract_text(response)

            # Store ALL new messages from the model loop (intermediate
            # tool_use/tool_result exchanges + final assistant response)
            for new_msg in updated_messages[original_count:]:
                role = new_msg["role"]
                content = new_msg["content"]
                if role == "assistant" and isinstance(content, list):
                    self.session_store.append_assistant(agent_name, session_id, content)
                elif role == "user" and isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            self.session_store.append_tool_result(
                                agent_name, session_id,
                                block["tool_use_id"], block["content"],
                            )

            # Append to chat history (user + assistant text only)
            self.chat_history.append(agent_name, "user", inbound.text)
            if text:
                self.chat_history.append(agent_name, "assistant", text)

            if inbound.sender_id != "system":
                self.memory_store.add_daily(f"{inbound.sender_id}: {inbound.text}")

            _elapsed = _time.monotonic() - _turn_start
            log.info(
                "run_turn DONE: agent=%s elapsed=%.1fs response_len=%d",
                agent_name, _elapsed, len(text or ""),
            )
            return TurnResult(text=text or "(no text response)", agent_name=agent_name, session_id=session_id)
        except Exception as exc:
            _elapsed = _time.monotonic() - _turn_start
            log.error(
                "run_turn FAILED: agent=%s session=%s channel=%s elapsed=%.1fs error=%s",
                agent_name, session_id, inbound.channel, _elapsed, exc,
            )
            self.memory_store.add_error(
                source="agent_loop",
                message=str(exc),
                context={
                    "agent_name": agent_name,
                    "session_id": session_id,
                    "channel": inbound.channel,
                },
            )
            raise

    async def _run_model_loop(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        thinking_callback: Callable[[str], Any] | None = None,
        model_id: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[ProviderResponse, list[dict]]:
        effective_model = model_id or self.model_id
        effective_max_tokens = max_tokens or self.max_tokens
        current_messages = list(messages)
        for iteration in range(self.max_tool_iterations):
            log.info(
                "Model loop iteration %d: messages=%d",
                iteration + 1, len(current_messages),
            )
            if thinking_callback:
                thinking_callback(f"Model iteration {iteration + 1}")

            log.info(
                "Calling LLM API: model=%s messages=%d tools=%d max_tokens=%d",
                effective_model, len(current_messages), len(tools), effective_max_tokens,
            )
            response = await self.context_guard.guard_call(
                lambda guarded_messages: self.provider.create_message(
                    model=effective_model,
                    system=system,
                    messages=guarded_messages,
                    tools=tools,
                    max_tokens=effective_max_tokens,
                ),
                current_messages,
            )

            block_types = [b.type for b in response.content]
            log.info(
                "LLM response: stop_reason=%s blocks=%d types=%s",
                response.stop_reason, len(response.content), block_types,
            )

            assistant_blocks = []
            for block in response.content:
                if block.type == "text":
                    assistant_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_blocks.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )
            current_messages.append({"role": "assistant", "content": assistant_blocks})

            if response.stop_reason == "end_turn":
                return response, current_messages

            if response.stop_reason == "tool_use":
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    tool_detail = ""
                    if isinstance(block.input, dict):
                        if block.name == "bash" and "command" in block.input:
                            tool_detail = " cmd=%s" % repr(block.input["command"][:200])
                        elif block.name == "read_file" and "path" in block.input:
                            tool_detail = " path=%s" % block.input["path"]
                        elif block.name == "write_file" and "path" in block.input:
                            tool_detail = " path=%s" % block.input["path"]
                        elif block.name == "web_search" and "query" in block.input:
                            tool_detail = " query=%s" % repr(block.input["query"][:100])
                    log.info("Executing tool: %s keys=%s%s", block.name, list(block.input.keys()) if isinstance(block.input, dict) else "?", tool_detail)
                    if thinking_callback:
                        thinking_callback(f"Running tool: {block.name}")
                    result = await self.tool_execute(block.name, block.input)
                    log.info("Tool done: %s result_len=%d", block.name, len(result) if isinstance(result, str) else 0)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
                current_messages.append({"role": "user", "content": results})
                continue

            return response, current_messages

        log.error("Tool-use loop exceeded %d iterations", self.max_tool_iterations)
        raise RuntimeError("Tool-use loop exceeded max iterations")

    def _extract_text(self, response: ProviderResponse) -> str:
        return "".join([b.text for b in response.content if b.type == "text"]).strip()

    def _auto_recall(self, user_message: str, agent_name: str = "") -> str:
        hits = self.memory_store.search_short_term(user_message, agent_name=agent_name, top_k=3)
        if not hits:
            return ""
        lines = [f"- [{h.path}] {h.snippet}" for h in hits]
        return "\n".join(lines)
