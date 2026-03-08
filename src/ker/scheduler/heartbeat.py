from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time

from ker.logger import get_logger

log = get_logger("heartbeat")


@dataclass
class HeartbeatStatus:
    enabled: bool
    running: bool
    last_run_at: float
    interval: int


class HeartbeatRunner:
    def __init__(
        self,
        ker_root: Path,
        run_once: Callable[[str], Awaitable[str]],
        interval: int = 60,
        active_hours: tuple[int, int] = (0, 24),
    ) -> None:
        self.ker_root = ker_root
        self.run_once = run_once
        self.interval = interval
        self.active_hours = active_hours
        self.last_run_at = 0.0
        self.running = False
        self.enabled = False
        self._last_output = ""
        self._pending_trigger = False

    @property
    def heartbeat_path(self) -> Path:
        return self.ker_root / "templates" / "HEARTBEAT.md"

    def start(self) -> None:
        self.enabled = True

    def stop(self) -> None:
        self.enabled = False

    def status(self) -> HeartbeatStatus:
        return HeartbeatStatus(self.enabled, self.running, self.last_run_at, self.interval)

    def trigger(self) -> None:
        self._pending_trigger = True

    def _has_active_tasks(self, content: str) -> bool:
        """Check if HEARTBEAT.md contains actual task content, not just boilerplate.

        Follows nanobot's pattern: skip silently when there are no real tasks.
        Looks for task markers (- [ ], - [x], numbered items) or non-template
        lines under the Active Tasks section.
        """
        # Quick check: task checkbox markers anywhere
        if re.search(r"- \[[ x]\]", content):
            return True

        # Check for content under "## Active Tasks" that isn't just HTML comments
        active_match = re.search(r"## Active Tasks\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if active_match:
            section = active_match.group(1).strip()
            # Strip HTML comments and blank lines
            lines = [
                line.strip()
                for line in section.splitlines()
                if line.strip() and not line.strip().startswith("<!--")
            ]
            if lines:
                return True

        return False

    def should_run(self) -> tuple[bool, str]:
        if self._pending_trigger:
            return True, "manual trigger"
        if not self.enabled:
            return False, "disabled"
        if not self.heartbeat_path.exists():
            return False, "HEARTBEAT.md not found"
        content = self.heartbeat_path.read_text(encoding="utf-8").strip()
        if not content:
            return False, "HEARTBEAT.md is empty"
        if not self._has_active_tasks(content):
            return False, "no active tasks in HEARTBEAT.md"
        elapsed = time.time() - self.last_run_at
        if elapsed < self.interval:
            return False, f"interval not elapsed ({int(self.interval - elapsed)}s remaining)"
        hour = datetime.now().hour
        start, end = self.active_hours
        in_hours = (start <= hour < end) if start <= end else not (end <= hour < start)
        if not in_hours:
            return False, f"outside active hours ({start}:00-{end}:00)"
        if self.running:
            return False, "already running"
        return True, "all checks passed"

    async def run_tick(self) -> list[str]:
        ok, _ = self.should_run()
        if not ok:
            return []

        self._pending_trigger = False
        self.running = True
        outputs: list[str] = []
        try:
            instructions = self.heartbeat_path.read_text(encoding="utf-8")
            reply = await self.run_once(instructions)
            text = reply.strip()
            if text and text != "HEARTBEAT_OK" and text != self._last_output:
                self._last_output = text
                outputs.append(text)
        except Exception as exc:
            outputs.append(f"Heartbeat error: {exc}")
            log.error("Heartbeat failed: %s", exc)
        finally:
            self.running = False
            self.last_run_at = time.time()
        return outputs
