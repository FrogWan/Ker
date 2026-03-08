import pytest
from ker.llm.anthropic_provider import AnthropicProvider
from ker.llm.azure_openai import AzureOpenAIProvider
from ker.llm.github_copilot import GitHubCopilotProvider


def test_anthropic_provider_no_key():
    provider = AnthropicProvider(api_key="")
    assert provider._client is None


@pytest.mark.asyncio
async def test_anthropic_provider_missing_key():
    provider = AnthropicProvider(api_key="")
    with pytest.raises(RuntimeError, match="Missing ANTHROPIC_API_KEY"):
        await provider.create_message("model", "system", [], None, 100)


@pytest.mark.asyncio
async def test_azure_not_implemented():
    provider = AzureOpenAIProvider(api_key="key", endpoint="https://example.com")
    with pytest.raises(NotImplementedError):
        await provider.create_message("model", "system", [], None, 100)


@pytest.mark.asyncio
async def test_github_copilot_not_implemented():
    provider = GitHubCopilotProvider(token="token")
    with pytest.raises(NotImplementedError):
        await provider.create_message("model", "system", [], None, 100)
