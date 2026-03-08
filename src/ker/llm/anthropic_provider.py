from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from ker.llm.base import LLMProvider
from ker.types import ProviderBlock, ProviderResponse


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key) if api_key else None

    async def create_message(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ProviderResponse:
        if self._client is None:
            raise RuntimeError("Missing ANTHROPIC_API_KEY")
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        response = await self._client.messages.create(**kwargs)
        blocks: list[ProviderBlock] = []
        for b in response.content:
            btype = getattr(b, "type", "text")
            if btype == "text":
                blocks.append(ProviderBlock(type="text", text=getattr(b, "text", "")))
            elif btype == "tool_use":
                blocks.append(
                    ProviderBlock(
                        type="tool_use",
                        id=getattr(b, "id", ""),
                        name=getattr(b, "name", ""),
                        input=getattr(b, "input", {}) or {},
                    )
                )
        return ProviderResponse(stop_reason=response.stop_reason, content=blocks)
