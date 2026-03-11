from __future__ import annotations

import asyncio
import json
from typing import Any

from pathlib import Path

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
        ker_root: str | Path = ".ker",
        reconnect_base: float = 1.0,
        reconnect_max: float = 30.0,
    ) -> None:
        self.ws_url = ws_url
        self.api_key = api_key
        self.ker_root = Path(ker_root)
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
                        elif data.get("type") == "sync_request":
                            asyncio.create_task(self._handle_sync_request(data))
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

    async def _handle_sync_request(self, data: dict) -> None:
        """Read all sessions from .ker and send sync_response back to Kerweb."""
        try:
            agents_dir = self.ker_root / "agents"
            if not agents_dir.exists():
                await self._send_frame("sync_response", {"sessions": [], "agentsInfo": {}})
                return

            # Discover agents
            agents = sorted(
                e.name for e in agents_dir.iterdir() if e.is_dir()
            )

            # Build sessions map and load messages
            sessions_map: dict[str, list[str]] = {}
            session_data: list[dict] = []

            for agent in agents:
                session_dir = agents_dir / agent / "session"
                if not session_dir.exists():
                    sessions_map[agent] = ["default"]
                    continue

                agent_sessions: list[str] = []
                for f in sorted(session_dir.iterdir()):
                    if not f.suffix == ".jsonl":
                        continue
                    # Parse filename: {channel}_{user}_{session}.jsonl
                    stem = f.stem
                    parts = stem.split("_", 2)
                    if len(parts) < 3:
                        continue
                    # Only include kerweb sessions
                    if parts[0] != "kerweb":
                        continue
                    session_name = parts[2]
                    if session_name not in agent_sessions:
                        agent_sessions.append(session_name)

                    # Parse JSONL file to extract messages
                    messages = []
                    try:
                        content = f.read_text(encoding="utf-8")
                        for line in content.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            ts = record.get("ts", 0)
                            timestamp = int(ts * 1000)
                            rec_type = record.get("type")
                            if rec_type == "user":
                                msg = {
                                    "id": f"hist-{ts}",
                                    "role": "user",
                                    "content": record.get("content", ""),
                                    "agent": agent,
                                    "session": session_name,
                                    "timestamp": timestamp,
                                }
                                media = record.get("media")
                                if media and isinstance(media, list) and len(media) > 0:
                                    msg["media"] = media
                                messages.append(msg)
                            elif rec_type == "assistant":
                                text = self._extract_text(record.get("content", ""))
                                if text:
                                    messages.append({
                                        "id": f"hist-{ts}",
                                        "role": "agent",
                                        "content": text,
                                        "agent": agent,
                                        "session": session_name,
                                        "timestamp": timestamp,
                                    })
                    except Exception as exc:
                        log.warning("Failed to read session file %s: %s", f, exc)
                        continue

                    messages.sort(key=lambda m: m["timestamp"])
                    session_data.append({
                        "agent": agent,
                        "session": session_name,
                        "messages": messages,
                    })

                sessions_map[agent] = agent_sessions if agent_sessions else ["default"]

            agents_info = {
                "agents": agents,
                "sessions": sessions_map,
                "currentAgent": self.current_agent,
                "currentSession": self.current_session,
            }

            await self._send_frame("sync_response", {
                "agentsInfo": agents_info,
                "sessions": session_data,
            })
            log.info("Sent sync_response with %d session(s)", len(session_data))
        except Exception as exc:
            log.error("sync_request failed: %s", exc)
            await self._send_frame("sync_response", {"sessions": [], "agentsInfo": {}, "error": str(exc)})

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Extract visible text from assistant content (string or list of blocks)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
            return "\n".join(parts)
        return ""

    async def receive(self) -> InboundMessage | None:
        try:
            return self._inbound.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def send(self, to: str, text: str, **kwargs: Any) -> bool:
        payload: dict[str, Any] = {
            "content": text,
            "to": to,
            "agent": kwargs.get("agent", self.current_agent),
            "session": kwargs.get("session", self.current_session),
        }
        media = kwargs.get("media")
        if media:
            payload["media"] = media
        return await self._send_frame("output", payload)

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
