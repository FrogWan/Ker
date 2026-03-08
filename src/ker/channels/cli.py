from __future__ import annotations

import asyncio
import sys
from typing import Any

from ker.channels.base import AsyncChannel
from ker.types import InboundMessage


class CLIChannel(AsyncChannel):
    name = "cli"

    def __init__(self) -> None:
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._stop = False

    async def receive(self) -> InboundMessage | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def send(self, to: str, text: str, **kwargs: Any) -> bool:
        print(f"Assistant > {text}")
        return True

    async def thinking(self, status: str) -> None:
        sys.stdout.write(f"\r[thinking] {status}...   ")
        sys.stdout.flush()

    async def listen(self, queue: asyncio.Queue[InboundMessage]) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop:
            try:
                text = await loop.run_in_executor(None, self._read_input)
            except (KeyboardInterrupt, EOFError):
                await queue.put(
                    InboundMessage(text="/exit", sender_id="cli-user", channel="cli", user="cli-user")
                )
                return

            if text is None:
                continue
            text = text.strip()
            if not text:
                continue

            await queue.put(
                InboundMessage(
                    text=text,
                    sender_id="cli-user",
                    channel="cli",
                    user="cli-user",
                )
            )

    def _read_input(self) -> str | None:
        try:
            return input("You > ")
        except (KeyboardInterrupt, EOFError):
            raise

    def stop(self) -> None:
        self._stop = True
