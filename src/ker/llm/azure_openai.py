from __future__ import annotations

from typing import Any

from ker.llm.base import LLMProvider
from ker.types import ProviderResponse


class AzureOpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, endpoint: str) -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    async def create_message(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ProviderResponse:
        # TODO: Implement Azure OpenAI provider
        raise NotImplementedError("Azure OpenAI provider not yet implemented")
