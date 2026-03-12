from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from ker.channels.base import AsyncChannel
from ker.types import InboundMessage

log = logging.getLogger(__name__)

KER_PREFIX = "[ker] "

# Regex to extract data-URI images from HTML body
_DATA_URI_RE = re.compile(
    r'<img[^>]+src="data:(image/(?:png|jpeg|gif|webp));base64,([^"]+)"[^>]*>',
    re.IGNORECASE,
)

# Regex to extract hosted-content image references (Graph API style)
_HOSTED_IMG_RE = re.compile(
    r'<img[^>]+src="[^"]*hostedContents/([^/"]+)/\$value"[^>]*>',
    re.IGNORECASE,
)


@dataclass
class TeamsConfig:
    enabled: bool = False
    chat_id: str = "48:notes"
    poll_interval_sec: float = 5.0
    mcp_command: str = "C:\\Users\\kuwa\\AppData\\Roaming\\agency\\CurrentVersion\\agency.exe"
    mcp_args: list[str] = field(default_factory=lambda: ["mcp", "teams"])


class TeamsChannel(AsyncChannel):
    name = "teams"

    def __init__(self, config: TeamsConfig | None = None) -> None:
        self.config = config or TeamsConfig()
        self._stack: AsyncExitStack | None = None
        self._session: Any = None  # mcp.ClientSession
        self._last_seen_id: str | None = None

    async def _ensure_session(self) -> None:
        if self._session is not None:
            return
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            log.warning("mcp package not installed; Teams channel unavailable")
            return

        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=self.config.mcp_command,
            args=self.config.mcp_args,
        )
        transport = await self._stack.enter_async_context(stdio_client(params))
        read_stream, write_stream = transport
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        log.info("Connected to Teams MCP server")

    def _strip_html(self, text: str) -> str:
        """Remove all HTML tags and unescape entities."""
        return html.unescape(re.sub(r"<[^>]+>", "", text))

    def _extract_body_and_media(self, message: dict) -> tuple[str, list[dict[str, Any]]]:
        """Extract plain text and inline images from a message.

        Returns (text, media_list) where media_list contains dicts with
        ``media_type``, ``data`` (base64), and ``filename`` keys.
        """
        body = message.get("body", {})
        raw_content = body.get("content", "")
        media_list: list[dict[str, Any]] = []

        if body.get("contentType", "").lower() == "html":
            # Extract data-URI images before stripping HTML
            for idx, m in enumerate(_DATA_URI_RE.finditer(raw_content)):
                media_list.append({
                    "media_type": m.group(1),
                    "data": m.group(2),
                    "filename": f"teams_image_{idx}.png",
                })
            text = self._strip_html(raw_content)
        else:
            text = raw_content

        # Also check hostedContents array (Graph API enriched responses)
        for hc in message.get("hostedContents", []):
            content_bytes = hc.get("contentBytes", "")
            content_type = hc.get("contentType", "")
            if content_bytes and content_type.startswith("image/"):
                media_list.append({
                    "media_type": content_type,
                    "data": content_bytes,
                    "filename": f"teams_hosted_{hc.get('id', 'img')}.png",
                })

        return text.strip(), media_list

    async def receive(self) -> InboundMessage | None:
        if not self.config.enabled or self._session is None:
            return None

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(
                    "ListChatMessages",
                    {"chatId": self.config.chat_id, "orderby": "createdDateTime desc"},
                ),
                timeout=30,
            )
        except Exception:
            log.debug("Teams ListChatMessages failed", exc_info=True)
            return None

        # Parse response: result.content is a list of content blocks.
        # The first text block contains the JSON payload; subsequent blocks
        # may be correlation metadata (not valid JSON).
        data = None
        for block in getattr(result, "content", []):
            if not hasattr(block, "text"):
                continue
            try:
                data = json.loads(block.text)
                break
            except (json.JSONDecodeError, TypeError):
                continue
        if data is None:
            return None

        if isinstance(data, list):
            messages = data
        else:
            messages = data.get("messages") or data.get("value") or []
        if not messages:
            return None

        # Find first non-Ker message
        for msg in messages:
            body_text, media_list = self._extract_body_and_media(msg)
            if body_text.startswith(KER_PREFIX):
                continue  # Skip Ker's own messages

            msg_id = str(msg.get("id", ""))
            if msg_id == self._last_seen_id:
                return None  # Already processed

            self._last_seen_id = msg_id
            sender = msg.get("from", {}) or {}
            # Agency MCP returns flat {displayName, id}; Graph API nests under .user
            if "user" in sender:
                sender = sender["user"]
            display_name = sender.get("displayName", "teams-user")
            user_id = sender.get("id", display_name)

            return InboundMessage(
                text=body_text,
                sender_id=user_id,
                channel=self.name,
                user=display_name,
                media=media_list,
                raw={"message_id": msg_id, "source": "teams"},
            )

        return None

    async def send(self, to: str, text: str, **kwargs: Any) -> bool:
        if not self.config.enabled or self._session is None:
            return False

        media: list[dict[str, Any]] = kwargs.get("media") or []
        image_count = sum(
            1 for m in media
            if m.get("data") and m.get("media_type", "").startswith("image/")
        )

        # Teams MCP PostMessage doesn't support image uploads.
        # Append a note so the user knows images were generated.
        suffix = ""
        if image_count:
            suffix = f"\n\n[{image_count} image(s) generated — view in KerWeb]"

        content = f"{KER_PREFIX}{text}{suffix}"

        try:
            await asyncio.wait_for(
                self._session.call_tool(
                    "PostMessage",
                    {
                        "chatId": self.config.chat_id,
                        "content": content,
                        "contentType": "text",
                    },
                ),
                timeout=30,
            )
            return True
        except Exception:
            log.debug("Teams PostMessage failed", exc_info=True)
            return False

    async def listen(self, queue: asyncio.Queue[InboundMessage]) -> None:
        # Retry initial connection with backoff
        for attempt in range(5):
            try:
                await self._ensure_session()
                if self._session is not None:
                    break
                log.warning("Teams MCP session is None after connect (attempt %d/5)", attempt + 1)
            except Exception:
                log.error("Failed to connect to Teams MCP server (attempt %d/5)", attempt + 1, exc_info=True)
            await asyncio.sleep(min(5 * (attempt + 1), 30))
        else:
            log.error("Teams channel gave up connecting after 5 attempts")
            return

        while True:
            try:
                msg = await self.receive()
                if msg is not None:
                    await queue.put(msg)
            except Exception:
                log.error("Teams poll error, attempting reconnect", exc_info=True)
                await self.close()
                try:
                    await self._ensure_session()
                except Exception:
                    log.error("Teams reconnect failed", exc_info=True)
            await asyncio.sleep(max(0.05, self.config.poll_interval_sec))

    async def close(self) -> None:
        self._session = None
        if self._stack:
            try:
                await self._stack.aclose()
            except Exception:
                pass
            self._stack = None
