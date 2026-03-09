import json

import pytest
from ker.llm.anthropic_provider import AnthropicProvider
from ker.llm.azure_openai import AzureOpenAIProvider
from ker.llm.github_copilot import (
    GitHubCopilotProvider,
    _convert_messages_chat,
    _convert_messages_responses,
    _convert_tools_chat,
    _convert_tools_responses,
    _is_responses_model,
    _parse_chat_response,
)


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


def test_github_copilot_provider_init(tmp_path):
    ker_root = tmp_path / ".ker"
    ker_root.mkdir()
    provider = GitHubCopilotProvider(ker_root=ker_root, token="test-token")
    assert provider._auth._static_token == "test-token"


# ── Model routing ───────────────────────────────────────────────────


def test_is_responses_model():
    assert _is_responses_model("gpt-5.3-codex")
    assert _is_responses_model("gpt-5.1-codex")
    assert not _is_responses_model("gpt-4o")
    assert not _is_responses_model("claude-sonnet-4")
    assert not _is_responses_model("o4-mini")


# ── /chat/completions conversion tests ──────────────────────────────


def test_convert_messages_chat_system_and_text():
    msgs = _convert_messages_chat("Be helpful.", [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ])
    assert msgs[0] == {"role": "system", "content": "Be helpful."}
    assert msgs[1] == {"role": "user", "content": "Hello"}
    assert msgs[2] == {"role": "assistant", "content": "Hi there!"}


def test_convert_messages_chat_tool_use_and_result():
    msgs = _convert_messages_chat("", [
        {"role": "assistant", "content": [
            {"type": "text", "text": "Running tool."},
            {"type": "tool_use", "id": "c1", "name": "exec", "input": {"command": "ls"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "file.txt"},
        ]},
    ])
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "Running tool."
    assert msgs[0]["tool_calls"][0]["id"] == "c1"
    assert msgs[0]["tool_calls"][0]["function"]["name"] == "exec"
    assert json.loads(msgs[0]["tool_calls"][0]["function"]["arguments"]) == {"command": "ls"}
    assert msgs[1] == {"role": "tool", "tool_call_id": "c1", "content": "file.txt"}


def test_convert_messages_chat_no_system():
    msgs = _convert_messages_chat("", [{"role": "user", "content": "hi"}])
    assert msgs[0]["role"] == "user"


def test_convert_tools_chat():
    tools = _convert_tools_chat([
        {"name": "exec", "description": "Run cmd", "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }},
    ])
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "exec"
    assert tools[0]["function"]["parameters"]["required"] == ["command"]


def test_parse_chat_response_text():
    resp = _parse_chat_response({
        "choices": [{"message": {"content": "Done!", "tool_calls": None}, "finish_reason": "stop"}],
    })
    assert resp.stop_reason == "end_turn"
    assert len(resp.content) == 1
    assert resp.content[0].type == "text"
    assert resp.content[0].text == "Done!"


def test_parse_chat_response_tool_calls():
    resp = _parse_chat_response({
        "choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "exec", "arguments": '{"command": "ls"}'}},
        ]}, "finish_reason": "tool_calls"}],
    })
    assert resp.stop_reason == "tool_use"
    assert resp.content[0].type == "tool_use"
    assert resp.content[0].name == "exec"
    assert resp.content[0].input == {"command": "ls"}


def test_parse_chat_response_length():
    resp = _parse_chat_response({
        "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
    })
    assert resp.stop_reason == "max_tokens"


# ── /responses conversion tests ─────────────────────────────────────


def test_convert_messages_responses_basic():
    instructions, items = _convert_messages_responses("You are helpful.", [
        {"role": "user", "content": "Hello"},
    ])
    assert instructions == "You are helpful."
    assert len(items) == 1
    assert items[0]["role"] == "user"
    assert items[0]["content"][0] == {"type": "input_text", "text": "Hello"}


def test_convert_messages_responses_tool_flow():
    instructions, items = _convert_messages_responses("", [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Running."},
            {"type": "tool_use", "id": "c1", "name": "exec", "input": {"command": "ls"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "a.txt\nb.txt"},
        ]},
    ])
    assert items[0]["role"] == "user"
    assert items[1]["type"] == "message"
    assert items[1]["role"] == "assistant"
    assert items[2]["type"] == "function_call"
    assert items[2]["call_id"] == "c1"
    assert items[2]["name"] == "exec"
    assert items[3]["type"] == "function_call_output"
    assert items[3]["call_id"] == "c1"
    assert items[3]["output"] == "a.txt\nb.txt"


def test_convert_tools_responses():
    tools = _convert_tools_responses([
        {"name": "exec", "description": "Run cmd", "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
        }},
    ])
    assert tools[0]["type"] == "function"
    assert tools[0]["name"] == "exec"
    # Flat format — no nested "function" key
    assert "function" not in tools[0]
    assert tools[0]["parameters"]["properties"]["command"]["type"] == "string"
