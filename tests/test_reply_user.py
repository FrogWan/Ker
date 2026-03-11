from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from ker.tools.tool_base import ToolContext
from ker.tools.tool_reply import reply_user
from ker.types import OutboundMessage


def _make_ctx(tmp_path: Path, with_queue: bool = True) -> ToolContext:
    ctx = ToolContext(
        workspace=tmp_path,
        ker_root=tmp_path / ".ker",
        current_channel="test-ch",
        current_user="test-user",
    )
    if with_queue:
        ctx.outbound_queue = asyncio.Queue()
    return ctx


def test_text_only(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = asyncio.run(reply_user(ctx, content="Hello!"))
    assert "6 chars text" in result
    msg: OutboundMessage = ctx.outbound_queue.get_nowait()
    assert msg.text == "Hello!"
    assert msg.channel == "test-ch"
    assert msg.user == "test-user"
    assert msg.media == []


def test_image_file(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    img = tmp_path / "photo.png"
    img.write_bytes(b"\x89PNG fake image data")
    result = asyncio.run(reply_user(ctx, file_paths=["photo.png"]))
    assert "1 media item" in result
    msg: OutboundMessage = ctx.outbound_queue.get_nowait()
    item = msg.media[0]
    assert item["media_type"] == "image/png"
    assert item["filename"] == "photo.png"
    assert base64.b64decode(item["data"]) == b"\x89PNG fake image data"


def test_non_image_file(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    doc = tmp_path / "report.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")
    result = asyncio.run(reply_user(ctx, file_paths=["report.pdf"]))
    assert "1 media item" in result
    msg: OutboundMessage = ctx.outbound_queue.get_nowait()
    item = msg.media[0]
    assert item["media_type"] == "application/pdf"
    assert item["filename"] == "report.pdf"
    assert "data" not in item
    assert item["size"] == len(b"%PDF-1.4 fake")
    assert "path" in item


def test_no_content_no_files(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = asyncio.run(reply_user(ctx))
    assert result.startswith("Error")
    assert ctx.outbound_queue.empty()


def test_path_traversal_rejected(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = asyncio.run(reply_user(ctx, content="hi", file_paths=["../../etc/passwd"]))
    assert "Rejected (path traversal)" in result
    msg: OutboundMessage = ctx.outbound_queue.get_nowait()
    assert msg.media == []


def test_missing_outbound_queue(tmp_path: Path):
    ctx = _make_ctx(tmp_path, with_queue=False)
    result = asyncio.run(reply_user(ctx, content="test"))
    assert "Error" in result
    assert "outbound_queue" in result


def test_missing_file_graceful(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    result = asyncio.run(reply_user(ctx, content="hi", file_paths=["nonexistent.txt"]))
    assert "Skipped (not found)" in result
    msg: OutboundMessage = ctx.outbound_queue.get_nowait()
    assert msg.text == "hi"
    assert msg.media == []


def test_confirmation_format(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    img = tmp_path / "a.png"
    img.write_bytes(b"data")
    result = asyncio.run(reply_user(ctx, content="Look at this", file_paths=["a.png"]))
    assert "Delivered:" in result
    assert "12 chars text" in result
    assert "1 media item" in result


def test_too_many_files(tmp_path: Path):
    ctx = _make_ctx(tmp_path)
    paths = [f"file{i}.txt" for i in range(11)]
    result = asyncio.run(reply_user(ctx, file_paths=paths))
    assert "Error" in result
    assert "max 10" in result
    assert ctx.outbound_queue.empty()
