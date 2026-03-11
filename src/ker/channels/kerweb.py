from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from ker.agent.context.session import sanitize_session_name
from ker.channels.base import AsyncChannel
from ker.types import InboundMessage

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


@dataclass
class KerWebConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:3000"
    api_key: str = ""
    poll_interval_sec: float = 1.0


class KerWebPollingChannel(AsyncChannel):
    name = "kerweb"

    def __init__(self, config: KerWebConfig | None = None) -> None:
        self.config = config or KerWebConfig()
        self._client: httpx.AsyncClient | None = None
        self._inbound_buffer: deque[InboundMessage] = deque()
        self.current_agent: str = "ker"
        self.current_session: str = "default"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            if httpx is None:
                raise RuntimeError("httpx is required for KerWeb channel")
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def receive(self) -> InboundMessage | None:
        if not self.config.enabled or not self.config.api_key:
            return None

        if self._inbound_buffer:
            return self._inbound_buffer.popleft()

        client = await self._get_client()
        try:
            r = await client.get(
                f"{self.config.base_url.rstrip('/')}/api/agent/messages",
                headers={"x-api-key": self.config.api_key, "Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None

        if not isinstance(data, list) or not data:
            return None

        for msg in data:
            content = str(msg.get("content", "")).strip()
            media_list = msg.get("media") or []
            if not content and not media_list:
                continue
            sender_id = str(msg.get("profileId") or msg.get("loginName") or msg.get("from") or "kerweb-user")
            session_name = sanitize_session_name(str(msg.get("session") or "default"))
            agent_hint = str(msg.get("agent") or "")
            self._inbound_buffer.append(
                InboundMessage(
                    text=content,
                    sender_id=sender_id,
                    channel=self.name,
                    user=sender_id,
                    session_name=session_name,
                    media=media_list,
                    raw={"message_id": str(msg.get("id", "")), "source": "kerweb", "agent": agent_hint},
                )
            )

        return self._inbound_buffer.popleft() if self._inbound_buffer else None

    async def send(self, to: str, text: str, **kwargs: Any) -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        client = await self._get_client()
        try:
            payload: dict[str, Any] = {
                "content": text,
                "to": to,
                "agent": kwargs.get("agent", self.current_agent),
                "session": kwargs.get("session", self.current_session),
            }
            media = kwargs.get("media")
            if media:
                payload["media"] = media
            r = await client.post(
                f"{self.config.base_url.rstrip('/')}/api/agent/output",
                json=payload,
                headers={"x-api-key": self.config.api_key, "Content-Type": "application/json"},
            )
            return r.status_code == 200
        except Exception:
            return False

    async def thinking(self, status: str) -> None:
        if not self.config.enabled or not self.config.api_key:
            return
        client = await self._get_client()
        try:
            await client.post(
                f"{self.config.base_url.rstrip('/')}/api/agent/thinking",
                json={"status": status, "agent": self.current_agent, "session": self.current_session},
                headers={"x-api-key": self.config.api_key, "Content-Type": "application/json"},
            )
        except Exception:
            pass

    async def append_tool_log(self, tool: str, status: str, detail: str = "") -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.config.base_url.rstrip('/')}/api/agent/tool-log",
                json={"tool": tool, "status": status, "detail": detail, "agent": self.current_agent, "session": self.current_session},
                headers={"x-api-key": self.config.api_key, "Content-Type": "application/json"},
            )
            return r.status_code == 200
        except Exception:
            return False

    async def clear_tool_logs(self) -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        client = await self._get_client()
        try:
            r = await client.delete(
                f"{self.config.base_url.rstrip('/')}/api/agent/tool-log",
                headers={"x-api-key": self.config.api_key},
            )
            return r.status_code == 200
        except Exception:
            return False

    async def update_job(self, to: str, job: str | None) -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.config.base_url.rstrip('/')}/api/agent/job",
                json={"to": to, "job": job or "", "agent": self.current_agent, "session": self.current_session},
                headers={"x-api-key": self.config.api_key, "Content-Type": "application/json"},
            )
            return r.status_code == 200
        except Exception:
            return False

    async def publish_telemetry(self, to: str, telemetry: dict[str, Any]) -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.config.base_url.rstrip('/')}/api/agent/telemetry",
                json={"to": to, "telemetry": telemetry},
                headers={"x-api-key": self.config.api_key, "Content-Type": "application/json"},
            )
            return r.status_code == 200
        except Exception:
            return False

    async def push_agents_info(self, info: dict) -> bool:
        if not self.config.enabled or not self.config.api_key:
            return False
        client = await self._get_client()
        try:
            r = await client.post(
                f"{self.config.base_url.rstrip('/')}/api/agent/agents-info",
                json=info,
                headers={"x-api-key": self.config.api_key, "Content-Type": "application/json"},
            )
            return r.status_code == 200
        except Exception:
            return False

    async def listen(self, queue: asyncio.Queue[InboundMessage]) -> None:
        while True:
            msg = await self.receive()
            if msg is not None:
                await queue.put(msg)
            await asyncio.sleep(max(0.05, self.config.poll_interval_sec))

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# Backward-compatible alias
KerWebChannel = KerWebPollingChannel
