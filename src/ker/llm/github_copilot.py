from __future__ import annotations

from typing import Any

from ker.llm.base import LLMProvider
from ker.types import ProviderResponse


class GitHubCopilotProvider(LLMProvider):
    def __init__(self, token: str) -> None:
        self.token = token

    async def create_message(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ProviderResponse:
        # TODO: Implement GitHub Copilot provider
        raise NotImplementedError("GitHub Copilot provider not yet implemented")


def oauth_login() -> str:
    """Run GitHub Copilot OAuth device flow and return the token."""
    # TODO: Implement OAuth device flow
    raise NotImplementedError("GitHub Copilot OAuth login not yet implemented")
