from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

from ker.tools.tool_base import ToolContext, safe_path
from ker.types import OutboundMessage

logger = logging.getLogger(__name__)

MAX_FILE_ATTACHMENTS = 10
MAX_BASE64_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

_IMAGE_MIME_PREFIXES = ("image/jpeg", "image/png", "image/gif", "image/webp")


async def reply_user(
    ctx: ToolContext,
    content: str = "",
    file_paths: list[str] | None = None,
) -> str:
    """Send content directly to the user mid-turn via the outbound queue."""
    if not ctx.outbound_queue:
        return "Error: outbound_queue not available — cannot deliver message."

    if not content and not file_paths:
        return "Error: provide at least content or file_paths."

    media_list: list[dict] = []
    warnings: list[str] = []

    if file_paths:
        if len(file_paths) > MAX_FILE_ATTACHMENTS:
            return f"Error: max {MAX_FILE_ATTACHMENTS} file attachments allowed, got {len(file_paths)}."

        for rel_path in file_paths:
            try:
                resolved = safe_path(ctx.workspace, rel_path)
            except ValueError:
                warnings.append(f"Rejected (path traversal): {rel_path}")
                continue

            if not resolved.exists():
                warnings.append(f"Skipped (not found): {rel_path}")
                continue

            mime_type, _ = mimetypes.guess_type(str(resolved))
            mime_type = mime_type or "application/octet-stream"
            filename = resolved.name

            if mime_type in _IMAGE_MIME_PREFIXES:
                raw = resolved.read_bytes()
                encoded = base64.b64encode(raw).decode("ascii")
                if len(encoded) > MAX_BASE64_IMAGE_BYTES:
                    warnings.append(f"Skipped (>10 MB encoded): {rel_path}")
                    continue
                media_list.append({
                    "media_type": mime_type,
                    "data": encoded,
                    "filename": filename,
                })
            else:
                media_list.append({
                    "media_type": mime_type,
                    "path": str(resolved),
                    "filename": filename,
                    "size": resolved.stat().st_size,
                })

    await ctx.outbound_queue.put(
        OutboundMessage(
            text=content,
            channel=ctx.current_channel,
            user=ctx.current_user,
            media=media_list,
        )
    )

    # Build confirmation
    parts: list[str] = []
    if content:
        parts.append(f"{len(content)} chars text")
    if media_list:
        parts.append(f"{len(media_list)} media item{'s' if len(media_list) != 1 else ''}")
    summary = "Delivered: " + ", ".join(parts)
    if warnings:
        summary += "\nWarnings:\n" + "\n".join(f"  - {w}" for w in warnings)
    return summary
