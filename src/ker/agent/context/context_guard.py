from __future__ import annotations

from typing import Any


class ContextGuard:
    def truncate_large_tool_results(self, messages: list[dict[str, Any]], max_chars: int = 4000) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
                out.append(msg)
                continue
            blocks = []
            for block in msg["content"]:
                if block.get("type") != "tool_result":
                    blocks.append(block)
                    continue
                content = str(block.get("content", ""))
                if len(content) > max_chars:
                    content = content[:max_chars] + "\n...[truncated]"
                blocks.append({**block, "content": content})
            out.append({**msg, "content": blocks})
        return out

    def compact_history(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(messages) < 8:
            return messages
        keep_count = max(4, int(len(messages) * 0.2))
        compress_count = max(2, int(len(messages) * 0.5))
        compress_count = min(compress_count, len(messages) - keep_count)
        old = messages[:compress_count]
        summary_lines = []
        for m in old:
            role = m.get("role", "?")
            content = m.get("content")
            if isinstance(content, list):
                text = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
            elif isinstance(content, str):
                text = content
            else:
                text = str(content)
            summary_lines.append(f"{role}: {text[:160]}")
        summary = "\n".join(summary_lines)
        compacted = [
            {"role": "user", "content": "[Previous conversation summary]\n" + summary},
            {"role": "assistant", "content": [{"type": "text", "text": "Understood, I have the context."}]},
        ]
        compacted.extend(messages[compress_count:])
        return compacted

    async def guard_call(self, call_fn, messages: list[dict[str, Any]], max_retries: int = 2):
        current = messages
        for attempt in range(max_retries + 1):
            try:
                result = await call_fn(current)
                if current is not messages:
                    messages.clear()
                    messages.extend(current)
                return result
            except Exception as exc:
                msg = str(exc).lower()
                overflow = "context" in msg or "token" in msg or "overflow" in msg
                if not overflow or attempt >= max_retries:
                    raise
                if attempt == 0:
                    current = self.truncate_large_tool_results(current)
                else:
                    current = self.compact_history(current)
        raise RuntimeError("unreachable")
