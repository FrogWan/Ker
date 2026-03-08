from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ker.types import ProviderResponse


class LLMProvider(ABC):
    @abstractmethod
    async def create_message(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ProviderResponse:
        raise NotImplementedError
