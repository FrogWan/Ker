"""Media file utilities for loading image attachments."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from ker.logger import get_logger

log = get_logger("media")

SUPPORTED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def load_media_base64(ker_root: Path, media_ref: dict[str, Any]) -> str | None:
    """Return base64-encoded image data from a media reference.

    Supports two sources:
    - ``data`` key: already base64-encoded (e.g. from Teams inline images)
    - ``path`` key: relative path under .ker/media/

    Returns None if the file doesn't exist or the media_type is unsupported.
    """
    media_type = media_ref.get("media_type", "")
    if media_type not in SUPPORTED_TYPES:
        return None

    # Fast path: base64 data already present
    inline = media_ref.get("data")
    if inline:
        return inline

    rel_path = media_ref.get("path", "")
    if not rel_path:
        return None

    file_path = ker_root / "media" / rel_path

    # Path traversal protection
    try:
        file_path = file_path.resolve()
        media_root = (ker_root / "media").resolve()
        if not str(file_path).startswith(str(media_root) + os.sep):
            log.warning("Path traversal attempt blocked: %s", rel_path)
            return None
    except (OSError, ValueError):
        return None

    if not file_path.is_file():
        log.debug("Media file not found: %s", file_path)
        return None

    try:
        data = file_path.read_bytes()
        return base64.b64encode(data).decode("ascii")
    except OSError as exc:
        log.warning("Failed to read media file %s: %s", file_path, exc)
        return None
