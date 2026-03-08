from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from ker.types import InboundMessage


class AsyncChannel(ABC):
    name = "unknown"

    @abstractmethod
    async def receive(self) -> InboundMessage | None:
        raise NotImplementedError

    @abstractmethod
    async def send(self, to: str, text: str, **kwargs: Any) -> bool:
        raise NotImplementedError

    async def thinking(self, status: str) -> None:
        pass

    async def append_tool_log(self, tool: str, status: str, detail: str = "") -> bool:
        return False

    async def clear_tool_logs(self) -> bool:
        return False

    async def update_job(self, to: str, job: str | None) -> bool:
        return False

    async def publish_telemetry(self, to: str, telemetry: dict) -> bool:
        return False

    async def push_agents_info(self, info: dict) -> bool:
        return False

    async def listen(self, queue: asyncio.Queue[InboundMessage]) -> None:
        while True:
            msg = await self.receive()
            if msg is not None:
                await queue.put(msg)
            else:
                await asyncio.sleep(0.05)
