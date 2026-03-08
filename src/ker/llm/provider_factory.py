from __future__ import annotations

from ker.config import Settings
from ker.llm.base import LLMProvider
from ker.logger import get_logger

log = get_logger("provider_factory")


def create_provider(settings: Settings) -> LLMProvider:
    """Create an LLM provider based on settings.llm_provider."""
    provider_name = settings.llm_provider.lower()

    if provider_name == "anthropic":
        from ker.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=settings.anthropic_api_key)

    if provider_name in ("azure", "azure_openai"):
        from ker.llm.azure_openai import AzureOpenAIProvider
        return AzureOpenAIProvider(
            api_key=settings.azure_openai_key,
            endpoint=settings.azure_openai_endpoint,
        )

    if provider_name in ("github_copilot", "copilot"):
        from ker.llm.github_copilot import GitHubCopilotProvider
        return GitHubCopilotProvider(token=settings.github_copilot_token)

    log.warning("Unknown LLM provider '%s', falling back to Anthropic", provider_name)
    from ker.llm.anthropic_provider import AnthropicProvider
    return AnthropicProvider(api_key=settings.anthropic_api_key)
