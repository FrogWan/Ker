"""GitHub Copilot LLM provider.

Authentication flow (mirrors LiteLLM's github_copilot authenticator):
  1. ``oauth_login()`` runs the GitHub device-code flow and stores the
     access token in ``.ker/config.json`` (``github_copilot_token`` key).
  2. The access token is exchanged for a short-lived Copilot API key via
     ``https://api.github.com/copilot_internal/v2/token``.
  3. Requests are sent to the OpenAI-compatible endpoint at
     ``https://api.githubcopilot.com``.

Two endpoint modes:
  - ``/chat/completions`` — standard models (gpt-4o, claude-sonnet-4, …)
  - ``/responses`` — codex models (gpt-5.3-codex, …) via SSE streaming

Configuration (in ``.env``):
  LLM_PROVIDER=github_copilot
  MODEL_ID=gpt-4o              # or gpt-5.3-codex, claude-sonnet-4, etc.
  GITHUB_COPILOT_TOKEN=...     # optional — skips device-flow if set
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import uuid4

import httpx

from ker.llm.base import LLMProvider
from ker.logger import get_logger
from ker.types import ProviderBlock, ProviderResponse

log = get_logger("github_copilot")

# ── GitHub OAuth constants ──────────────────────────────────────────
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_KEY_URL = "https://api.github.com/copilot_internal/v2/token"

# ── Copilot API constants ──────────────────────────────────────────
COPILOT_API_BASE = "https://api.githubcopilot.com"
COPILOT_VERSION = "0.26.7"
EDITOR_PLUGIN_VERSION = f"copilot-chat/{COPILOT_VERSION}"
USER_AGENT = f"GitHubCopilotChat/{COPILOT_VERSION}"
API_VERSION = "2025-04-01"

# Models that require the /responses endpoint instead of /chat/completions
_RESPONSES_KEYWORDS = ("codex",)


def _is_responses_model(model: str) -> bool:
    m = model.lower()
    return any(kw in m for kw in _RESPONSES_KEYWORDS)


# ── Authenticator ───────────────────────────────────────────────────

class _Authenticator:
    """Handles GitHub Copilot OAuth device flow and API-key lifecycle.

    The long-lived GitHub access token is stored in ``.ker/config.json``
    (``github_copilot_token`` key).  The short-lived Copilot API key is
    cached separately under a cache directory.
    """

    def __init__(self, ker_root: Path, static_token: str = "") -> None:
        self._static_token = static_token
        self._config_path = ker_root / "config.json"
        # Short-lived API key cache (not the access token)
        cache_dir = ker_root / "cache" / "github_copilot"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._api_key_file = cache_dir / "api-key.json"

    # ── config.json helpers ─────────────────────────────────────────

    def _read_config(self) -> dict[str, Any]:
        try:
            return json.loads(self._config_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_config_key(self, key: str, value: str) -> None:
        cfg = self._read_config()
        cfg[key] = value
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(cfg, indent=2), "utf-8")

    # ── public ──────────────────────────────────────────────────────

    def get_api_key(self, force_refresh: bool = False) -> str:
        """Return a valid Copilot API key, refreshing as needed."""
        if not force_refresh:
            try:
                info = json.loads(self._api_key_file.read_text("utf-8"))
                if info.get("expires_at", 0) > time.time():
                    return info["token"]
                log.debug("API key expired, refreshing")
            except (OSError, json.JSONDecodeError, KeyError):
                pass

        info = self._refresh_api_key()
        try:
            self._api_key_file.write_text(json.dumps(info), "utf-8")
        except OSError as exc:
            log.warning("Failed to cache API key: %s", exc)
        return info["token"]

    def get_api_base(self) -> str:
        """Return the Copilot API endpoint (from cached token or default)."""
        try:
            info = json.loads(self._api_key_file.read_text("utf-8"))
            endpoint = info.get("endpoints", {}).get("api")
            if endpoint:
                return endpoint
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        return COPILOT_API_BASE

    def get_access_token(self) -> str:
        """Return a GitHub access token, running device flow if needed."""
        if self._static_token:
            return self._static_token

        token = self._read_config().get("github_copilot_token", "")
        if token:
            return token

        token = self._device_flow()
        self._write_config_key("github_copilot_token", token)
        return token

    # ── private ─────────────────────────────────────────────────────

    def _github_headers(self, access_token: str = "") -> dict[str, str]:
        headers: dict[str, str] = {
            "accept": "application/json",
            "content-type": "application/json",
            "editor-version": "vscode/1.85.1",
            "editor-plugin-version": "copilot/1.155.0",
            "user-agent": "GithubCopilot/1.155.0",
        }
        if access_token:
            headers["authorization"] = f"token {access_token}"
        return headers

    def _refresh_api_key(self) -> dict[str, Any]:
        access_token = self.get_access_token()
        headers = self._github_headers(access_token)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = httpx.get(GITHUB_API_KEY_URL, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                if "token" in data:
                    return data
                log.warning("API key response missing token: %s", data)
            except Exception as exc:
                last_err = exc
                log.warning("API key refresh attempt %d failed: %s", attempt + 1, exc)
        raise RuntimeError(f"Failed to refresh Copilot API key: {last_err}")

    def _device_flow(self) -> str:
        """Run the GitHub OAuth device-code flow (interactive)."""
        headers = self._github_headers()

        resp = httpx.post(
            GITHUB_DEVICE_CODE_URL,
            headers=headers,
            json={"client_id": GITHUB_CLIENT_ID, "scope": "read:user"},
            timeout=30,
        )
        resp.raise_for_status()
        info = resp.json()
        device_code = info["device_code"]
        user_code = info["user_code"]
        verification_uri = info["verification_uri"]

        print(f"\nPlease visit {verification_uri} and enter code: {user_code}\n", flush=True)

        for _ in range(60):  # 5 min max
            time.sleep(5)
            resp = httpx.post(
                GITHUB_ACCESS_TOKEN_URL,
                headers=headers,
                json={
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if "access_token" in data:
                return data["access_token"]
            if data.get("error") != "authorization_pending":
                log.warning("Unexpected device-flow response: %s", data)

        raise RuntimeError("Timed out waiting for GitHub device authorization")


# ═══════════════════════════════════════════════════════════════════
#  /chat/completions helpers (standard models)
# ═══════════════════════════════════════════════════════════════════

def _convert_tools_chat(anthropic_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic tool schema → OpenAI function-calling schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in anthropic_tools
    ]


def _convert_messages_chat(
    system: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Anthropic-format conversation to OpenAI /chat/completions messages."""
    out: list[dict[str, Any]] = []

    if system:
        out.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            out.append({"role": role, "content": str(content) if content else ""})
            continue

        has_tool_use = any(b.get("type") == "tool_use" for b in content if isinstance(b, dict))
        has_tool_result = any(b.get("type") == "tool_result" for b in content if isinstance(b, dict))

        if role == "assistant" and has_tool_use:
            text_parts = []
            tool_calls = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
            oai_msg: dict[str, Any] = {"role": "assistant"}
            oai_msg["content"] = "\n".join(text_parts) if text_parts else None
            if tool_calls:
                oai_msg["tool_calls"] = tool_calls
            out.append(oai_msg)

        elif has_tool_result:
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            b.get("text", "") for b in result_content if isinstance(b, dict)
                        )
                    out.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": str(result_content),
                    })

        else:
            oai_content: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    oai_content.append({"type": "text", "text": block.get("text", "")})
                elif btype == "image":
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        oai_content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}",
                            },
                        })
            out.append({"role": role, "content": oai_content if oai_content else ""})

    return out


def _parse_chat_response(data: dict[str, Any]) -> ProviderResponse:
    """Parse an OpenAI /chat/completions JSON response."""
    choice = data["choices"][0]
    message = choice["message"]
    finish = choice.get("finish_reason", "stop")

    blocks: list[ProviderBlock] = []

    text = message.get("content")
    if text:
        blocks.append(ProviderBlock(type="text", text=text))

    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
        blocks.append(ProviderBlock(
            type="tool_use",
            id=tc.get("id", ""),
            name=fn.get("name", ""),
            input=args,
        ))

    stop_reason = "end_turn"
    if finish == "tool_calls":
        stop_reason = "tool_use"
    elif finish == "length":
        stop_reason = "max_tokens"

    return ProviderResponse(stop_reason=stop_reason, content=blocks)


# ═══════════════════════════════════════════════════════════════════
#  /responses helpers (codex models — SSE streaming)
# ═══════════════════════════════════════════════════════════════════

def _convert_tools_responses(anthropic_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic tool schema → Responses API flat tool format."""
    return [
        {
            "type": "function",
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("input_schema", {}),
        }
        for t in anthropic_tools
    ]


def _convert_messages_responses(
    system: str,
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert Anthropic-format conversation to Responses API input items.

    Returns (instructions, input_items).
    """
    input_items: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        role = msg["role"]
        content = msg.get("content")

        # ── user ──
        if role == "user":
            if isinstance(content, str):
                input_items.append({
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}],
                })
            elif isinstance(content, list):
                # Could be text blocks or tool_result blocks
                has_tool_result = any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                )
                if has_tool_result:
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_result":
                            result_content = block.get("content", "")
                            if isinstance(result_content, list):
                                result_content = "\n".join(
                                    b.get("text", "") for b in result_content
                                    if isinstance(b, dict)
                                )
                            input_items.append({
                                "type": "function_call_output",
                                "call_id": block["tool_use_id"],
                                "output": str(result_content),
                            })
                else:
                    converted: list[dict[str, Any]] = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type", "")
                        if btype == "text":
                            converted.append({"type": "input_text", "text": block.get("text", "")})
                        elif btype == "image":
                            source = block.get("source", {})
                            if source.get("type") == "base64":
                                data_url = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
                                converted.append({"type": "input_image", "image_url": data_url, "detail": "auto"})
                    input_items.append({"role": "user", "content": converted or [{"type": "input_text", "text": ""}]})
            continue

        # ── assistant ──
        if role == "assistant":
            if isinstance(content, str) and content:
                input_items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                    "status": "completed",
                    "id": f"msg_{idx}",
                })
            elif isinstance(content, list):
                # Text blocks first
                text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if text_parts:
                    combined = "\n".join(text_parts)
                    if combined:
                        input_items.append({
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": combined}],
                            "status": "completed",
                            "id": f"msg_{idx}",
                        })
                # Then tool calls
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    input_items.append({
                        "type": "function_call",
                        "id": f"fc_{idx}",
                        "call_id": block["id"],
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    })
            continue

    return system, input_items


async def _iter_sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    """Yield parsed JSON events from an SSE stream."""
    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if buffer:
                data_lines = [ln[5:].strip() for ln in buffer if ln.startswith("data:")]
                buffer = []
                if not data_lines:
                    continue
                data = "\n".join(data_lines).strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue
            continue
        buffer.append(line)


async def _consume_responses_sse(response: httpx.Response) -> ProviderResponse:
    """Consume a /responses SSE stream and return ProviderResponse."""
    text_content = ""
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    blocks: list[ProviderBlock] = []
    stop_reason = "end_turn"

    async for event in _iter_sse(response):
        etype = event.get("type", "")

        if etype == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id", "")
                if call_id:
                    tool_call_buffers[call_id] = {
                        "id": item.get("id", "fc_0"),
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", ""),
                    }

        elif etype == "response.output_text.delta":
            text_content += event.get("delta", "")

        elif etype == "response.function_call_arguments.delta":
            call_id = event.get("call_id", "")
            if call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] += event.get("delta", "")

        elif etype == "response.function_call_arguments.done":
            call_id = event.get("call_id", "")
            if call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] = event.get("arguments", "")

        elif etype == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id", "")
                buf = tool_call_buffers.get(call_id, {})
                raw_args = buf.get("arguments") or item.get("arguments", "{}")
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}
                blocks.append(ProviderBlock(
                    type="tool_use",
                    id=call_id,
                    name=buf.get("name") or item.get("name", ""),
                    input=args,
                ))

        elif etype == "response.completed":
            status = (event.get("response") or {}).get("status", "completed")
            if status == "incomplete":
                stop_reason = "max_tokens"

        elif etype in ("error", "response.failed"):
            error_msg = ""
            if etype == "error":
                error_msg = event.get("message", "")
            raise RuntimeError(f"Copilot responses API failed: {error_msg or event}")

    # Build final response
    if text_content:
        blocks.insert(0, ProviderBlock(type="text", text=text_content))

    if any(b.type == "tool_use" for b in blocks):
        stop_reason = "tool_use"

    return ProviderResponse(stop_reason=stop_reason, content=blocks)


# ═══════════════════════════════════════════════════════════════════
#  Provider
# ═══════════════════════════════════════════════════════════════════

class GitHubCopilotProvider(LLMProvider):
    """GitHub Copilot via /chat/completions or /responses (codex models)."""

    def __init__(self, ker_root: Path, token: str = "") -> None:
        self._auth = _Authenticator(ker_root=ker_root, static_token=token)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=300)
        return self._client

    def _copilot_headers(self, api_key: str, streaming: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "copilot-integration-id": "vscode-chat",
            "editor-version": "vscode/1.95.0",
            "editor-plugin-version": EDITOR_PLUGIN_VERSION,
            "user-agent": USER_AGENT,
            "openai-intent": "conversation-panel",
            "x-github-api-version": API_VERSION,
            "x-request-id": str(uuid4()),
        }
        if streaming:
            headers["accept"] = "text/event-stream"
        return headers

    async def _request_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        stream: bool = False,
    ) -> httpx.Response:
        """POST with 401 auto-retry (force-refreshes API key)."""
        client = await self._get_client()

        if stream:
            req = client.build_request("POST", url, headers=headers, json=body)
            resp = await client.send(req, stream=True)
        else:
            resp = await client.post(url, headers=headers, json=body)

        if resp.status_code == 401:
            if stream:
                await resp.aclose()
            log.info("Got 401, refreshing API key and retrying")
            api_key = self._auth.get_api_key(force_refresh=True)
            headers = {**headers, "Authorization": f"Bearer {api_key}"}
            if stream:
                req = client.build_request("POST", url, headers=headers, json=body)
                resp = await client.send(req, stream=True)
            else:
                resp = await client.post(url, headers=headers, json=body)

        return resp

    async def create_message(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ProviderResponse:
        api_key = self._auth.get_api_key()
        api_base = self._auth.get_api_base()

        if _is_responses_model(model):
            return await self._call_responses(api_key, api_base, model, system, messages, tools, max_tokens)
        return await self._call_chat(api_key, api_base, model, system, messages, tools, max_tokens)

    # ── /chat/completions ───────────────────────────────────────────

    async def _call_chat(
        self,
        api_key: str,
        api_base: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ProviderResponse:
        url = f"{api_base.rstrip('/')}/chat/completions"
        headers = self._copilot_headers(api_key)
        oai_messages = _convert_messages_chat(system, messages)

        body: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
        }
        if any(kw in model.lower() for kw in ("o1", "o3", "o4")):
            body["max_completion_tokens"] = max_tokens
        else:
            body["temperature"] = 0
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = _convert_tools_chat(tools)
            body["tool_choice"] = "auto"

        resp = await self._request_with_retry(url, headers, body)

        if resp.status_code >= 400:
            error_body = resp.text
            log.error("Copilot API %d: %s", resp.status_code, error_body)
            try:
                detail = json.loads(error_body).get("error", {}).get("message", "")
            except (json.JSONDecodeError, AttributeError):
                detail = ""
            raise RuntimeError(detail or f"Copilot API error {resp.status_code}: {error_body}")

        return _parse_chat_response(resp.json())

    # ── /responses (codex, SSE) ─────────────────────────────────────

    async def _call_responses(
        self,
        api_key: str,
        api_base: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> ProviderResponse:
        url = f"{api_base.rstrip('/')}/responses"
        headers = self._copilot_headers(api_key, streaming=True)
        instructions, input_items = _convert_messages_responses(system, messages)

        body: dict[str, Any] = {
            "model": model,
            "stream": True,
            "instructions": instructions,
            "input": input_items,
            "store": False,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        if tools:
            body["tools"] = _convert_tools_responses(tools)

        resp = await self._request_with_retry(url, headers, body, stream=True)

        if resp.status_code >= 400:
            error_body = (await resp.aread()).decode("utf-8", "ignore")
            await resp.aclose()
            log.error("Copilot API %d: %s", resp.status_code, error_body)
            try:
                detail = json.loads(error_body).get("error", {}).get("message", "")
            except (json.JSONDecodeError, AttributeError):
                detail = ""
            raise RuntimeError(detail or f"Copilot API error {resp.status_code}: {error_body}")

        try:
            return await _consume_responses_sse(resp)
        finally:
            await resp.aclose()


# ── CLI entry point ─────────────────────────────────────────────────

def oauth_login(ker_root: Path | None = None) -> str:
    """Run GitHub Copilot OAuth device flow and return the access token."""
    if ker_root is None:
        ker_root = Path.cwd().resolve() / ".ker"
    auth = _Authenticator(ker_root=ker_root)
    token = auth.get_access_token()
    try:
        auth.get_api_key()
        print("GitHub Copilot authenticated successfully.")
    except Exception as exc:
        print(f"Warning: got access token but API key exchange failed: {exc}")
    return token
