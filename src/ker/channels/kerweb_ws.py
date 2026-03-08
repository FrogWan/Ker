from __future__ import annotations

import asyncio
import json
from typing import Any

from ker.agent.context.session import sanitize_session_name
from ker.channels.base import AsyncChannel
from ker.logger import get_logger
from ker.types import InboundMessage

log = get_logger("kerweb_ws")


class KerWebWSChannel(AsyncChannel):
    """Persistent WebSocket channel to KerWeb, replacing HTTP polling."""

    name = "kerweb"

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:3000/api/agent/ws",
        api_key: str = "",
        reconnect_base: float = 1.0,
        reconnect_max: float = 30.0,
    ) -> None:
        self.ws_url = ws_url
        self.api_key = api_key
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self._ws: Any = None
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._connected = False
        self.current_agent: str = "ker"
        self.current_session: str = "default"

    async def _connect(self) -> None:
        try:
            import websockets
        except ImportError:
            log.warning("websockets package not installed; WS channel disabled")
            return

        delay = self.reconnect_base
        while True:
            try:
                headers = {"x-api-key": self.api_key} if self.api_key else {}
                self._ws = await websockets.connect(self.ws_url, additional_headers=headers)
                self._connected = True
                delay = self.reconnect_base
                log.info("WebSocket connected to %s", self.ws_url)

                async for raw in self._ws:
                    try:
                        data = json.loads(raw)
                        if data.get("type") == "user_message":
                            msg_data = data.get("data", {})
                            media_list = msg_data.get("media") or []
                            await self._inbound.put(
                                InboundMessage(
                                    text=str(msg_data.get("content", "")),
                                    sender_id=str(msg_data.get("profileId", "kerweb-user")),
                                    channel=self.name,
                                    user=str(msg_data.get("profileId", "kerweb-user")),
                                    session_name=sanitize_session_name(str(msg_data.get("session", "default"))),
                                    media=media_list,
                                    raw={"agent": msg_data.get("agent", ""), "source": "kerweb-ws"},
                                )
                            )
                    except json.JSONDecodeError:
                        pass
            except Exception as exc:
                self._connected = False
                log.warning("WebSocket disconnected: %s, retrying in %.1fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max)

    async def _send_frame(self, frame_type: str, payload: dict) -> bool:
        if not self._ws or not self._connected:
            return False
        try:
            await self._ws.send(json.dumps({"type": frame_type, **payload}))
            return True
        except Exception:
            return False

    async def receive(self) -> InboundMessage | None:
        try:
            return self._inbound.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def send(self, to: str, text: str, **kwargs: Any) -> bool:
        return await self._send_frame("output", {
            "content": text,
            "to": to,
            "agent": kwargs.get("agent", self.current_agent),
            "session": kwargs.get("session", self.current_session),
        })

    async def thinking(self, status: str) -> None:
        await self._send_frame("thinking", {
            "status": status,
            "agent": self.current_agent,
            "session": self.current_session,
        })

    async def append_tool_log(self, tool: str, status: str, detail: str = "") -> bool:
        return await self._send_frame("tool-log", {
            "tool": tool,
            "status": status,
            "detail": detail,
            "agent": self.current_agent,
            "session": self.current_session,
        })

    async def clear_tool_logs(self) -> bool:
        return await self._send_frame("tool-log-clear", {
            "agent": self.current_agent,
            "session": self.current_session,
        })

    async def update_job(self, to: str, job: str | None) -> bool:
        return await self._send_frame("job", {
            "to": to,
            "job": job or "",
            "agent": self.current_agent,
            "session": self.current_session,
        })

    async def publish_telemetry(self, to: str, telemetry: dict[str, Any]) -> bool:
        return await self._send_frame("telemetry", {"to": to, "telemetry": telemetry})

    async def push_agents_info(self, info: dict) -> bool:
        return await self._send_frame("agents-info", info)

    async def listen(self, queue: asyncio.Queue[InboundMessage]) -> None:
        # Start WebSocket connection as background task
        asyncio.create_task(self._connect())
        while True:
            msg = await self._inbound.get()
            await queue.put(msg)

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None
            self._connected = False
