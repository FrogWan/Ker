import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ker.channels.teams import KER_PREFIX, TeamsChannel, TeamsConfig

TEST_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="


def test_teams_config_defaults():
    config = TeamsConfig()
    assert config.enabled is False
    assert config.chat_id == "48:notes"
    assert config.poll_interval_sec == 5.0
    assert config.mcp_command.endswith("agency.exe")
    assert config.mcp_args == ["mcp", "teams"]


@pytest.mark.asyncio
async def test_teams_disabled():
    ch = TeamsChannel(TeamsConfig(enabled=False))
    msg = await ch.receive()
    assert msg is None
    result = await ch.send("user", "test")
    assert result is False


@pytest.mark.asyncio
async def test_teams_receive_no_session():
    ch = TeamsChannel(TeamsConfig(enabled=True))
    # enabled but no MCP session established
    msg = await ch.receive()
    assert msg is None


def _make_mcp_result(messages: list[dict]) -> MagicMock:
    """Build a mock MCP call_tool result with JSON content (matches Agency MCP format)."""
    block = MagicMock()
    block.text = json.dumps({"messages": messages})
    # Second block is correlation metadata (non-JSON), like the real server
    meta_block = MagicMock()
    meta_block.text = "CorrelationId: test-123"
    result = MagicMock()
    result.content = [block, meta_block]
    return result


def _make_message(msg_id: str, body: str, display_name: str = "Alice", content_type: str = "text", hosted_contents: list | None = None) -> dict:
    """Match Agency MCP flat from format: {displayName, id} (not nested under .user)."""
    msg = {
        "id": msg_id,
        "body": {"content": body, "contentType": content_type},
        "from": {"id": "user-123", "displayName": display_name},
    }
    if hosted_contents:
        msg["hostedContents"] = hosted_contents
    return msg


def _channel_with_session(config: TeamsConfig | None = None) -> tuple[TeamsChannel, AsyncMock]:
    config = config or TeamsConfig(enabled=True)
    ch = TeamsChannel(config)
    session = AsyncMock()
    ch._session = session
    return ch, session


@pytest.mark.asyncio
async def test_teams_receive_skips_ker_prefix():
    ch, session = _channel_with_session()
    session.call_tool.return_value = _make_mcp_result([
        _make_message("1", f"{KER_PREFIX}Hello from Ker"),
    ])
    msg = await ch.receive()
    assert msg is None


@pytest.mark.asyncio
async def test_teams_receive_dedup():
    ch, session = _channel_with_session()

    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-42", "Hello"),
    ])
    msg1 = await ch.receive()
    assert msg1 is not None
    assert msg1.text == "Hello"

    # Same message ID again -> None
    msg2 = await ch.receive()
    assert msg2 is None


@pytest.mark.asyncio
async def test_teams_receive_new_message():
    ch, session = _channel_with_session()

    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-1", "First"),
    ])
    msg1 = await ch.receive()
    assert msg1 is not None
    assert msg1.text == "First"
    assert msg1.channel == "teams"
    assert msg1.user == "Alice"

    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-2", "Second"),
    ])
    msg2 = await ch.receive()
    assert msg2 is not None
    assert msg2.text == "Second"


@pytest.mark.asyncio
async def test_teams_html_stripping():
    ch, session = _channel_with_session()

    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-html", "<p>Hello &amp; <b>world</b></p>", content_type="html"),
    ])
    msg = await ch.receive()
    assert msg is not None
    assert msg.text == "Hello & world"


@pytest.mark.asyncio
async def test_teams_html_ker_prefix_detected_after_strip():
    ch, session = _channel_with_session()

    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-html-ker", f"<p>{KER_PREFIX}some reply</p>", content_type="html"),
    ])
    msg = await ch.receive()
    assert msg is None


@pytest.mark.asyncio
async def test_teams_send_adds_prefix():
    ch, session = _channel_with_session()

    session.call_tool.return_value = MagicMock()
    result = await ch.send("user", "Hi there")
    assert result is True

    session.call_tool.assert_called_once()
    call_args = session.call_tool.call_args
    assert call_args[0][0] == "PostMessage"
    payload = call_args[0][1]
    assert payload["content"] == f"{KER_PREFIX}Hi there"
    assert payload["chatId"] == "48:notes"
    assert payload["contentType"] == "text"


@pytest.mark.asyncio
async def test_teams_send_disabled():
    ch = TeamsChannel(TeamsConfig(enabled=True))
    # No session
    result = await ch.send("user", "test")
    assert result is False


@pytest.mark.asyncio
async def test_teams_receive_skips_ker_finds_user_message():
    """When the latest message is from Ker, skip it and find the next user message."""
    ch, session = _channel_with_session()

    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-ker", f"{KER_PREFIX}Ker's reply"),
        _make_message("msg-user", "User question"),
    ])
    msg = await ch.receive()
    assert msg is not None
    assert msg.text == "User question"
    assert msg.raw["message_id"] == "msg-user"


# --- Media tests ---


@pytest.mark.asyncio
async def test_teams_receive_extracts_data_uri_images():
    """Inline data-URI images in HTML body are extracted as media."""
    ch, session = _channel_with_session()

    html_body = f'<p>Look at this</p><img src="data:image/png;base64,{TEST_B64}" alt="cat">'
    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-img", html_body, content_type="html"),
    ])
    msg = await ch.receive()
    assert msg is not None
    assert msg.text == "Look at this"
    assert len(msg.media) == 1
    assert msg.media[0]["media_type"] == "image/png"
    assert msg.media[0]["data"] == TEST_B64


@pytest.mark.asyncio
async def test_teams_receive_hosted_contents():
    """hostedContents array with contentBytes is extracted as media."""
    ch, session = _channel_with_session()

    session.call_tool.return_value = _make_mcp_result([
        _make_message(
            "msg-hosted",
            '<p>photo</p><img src="../hostedContents/abc123/$value">',
            content_type="html",
            hosted_contents=[{
                "id": "abc123",
                "contentType": "image/jpeg",
                "contentBytes": TEST_B64,
            }],
        ),
    ])
    msg = await ch.receive()
    assert msg is not None
    assert msg.text == "photo"
    assert len(msg.media) == 1
    assert msg.media[0]["media_type"] == "image/jpeg"
    assert msg.media[0]["data"] == TEST_B64


@pytest.mark.asyncio
async def test_teams_receive_image_only_message():
    """A message with only an image and no text is still accepted."""
    ch, session = _channel_with_session()

    html_body = f'<img src="data:image/png;base64,{TEST_B64}">'
    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-imgonly", html_body, content_type="html"),
    ])
    msg = await ch.receive()
    assert msg is not None
    assert msg.text == ""
    assert len(msg.media) == 1


@pytest.mark.asyncio
async def test_teams_receive_ker_image_skipped():
    """Ker's own image messages (prefixed with [ker]) are skipped."""
    ch, session = _channel_with_session()

    html_body = f'<p>{KER_PREFIX}here is the image</p><img src="data:image/png;base64,{TEST_B64}">'
    session.call_tool.return_value = _make_mcp_result([
        _make_message("msg-ker-img", html_body, content_type="html"),
    ])
    msg = await ch.receive()
    assert msg is None


@pytest.mark.asyncio
async def test_teams_send_with_media_adds_note():
    """send() with images appends a note since Teams MCP can't upload images."""
    ch, session = _channel_with_session()
    session.call_tool.return_value = MagicMock()

    media = [{"media_type": "image/png", "data": TEST_B64, "filename": "cat.png"}]
    result = await ch.send("user", "Check this out", media=media)
    assert result is True

    payload = session.call_tool.call_args[0][1]
    assert payload["contentType"] == "text"
    assert KER_PREFIX in payload["content"]
    assert "1 image(s) generated" in payload["content"]
    assert "KerWeb" in payload["content"]


@pytest.mark.asyncio
async def test_teams_send_text_only():
    """send() without media uses plain text."""
    ch, session = _channel_with_session()
    session.call_tool.return_value = MagicMock()

    result = await ch.send("user", "Just text")
    assert result is True

    payload = session.call_tool.call_args[0][1]
    assert payload["contentType"] == "text"
    assert payload["content"] == f"{KER_PREFIX}Just text"


@pytest.mark.asyncio
async def test_teams_send_non_image_media_no_note():
    """Non-image media doesn't add the image note."""
    ch, session = _channel_with_session()
    session.call_tool.return_value = MagicMock()

    media = [{"media_type": "application/pdf", "path": "/tmp/doc.pdf", "filename": "doc.pdf"}]
    result = await ch.send("user", "Here's the doc", media=media)
    assert result is True

    payload = session.call_tool.call_args[0][1]
    assert "image(s)" not in payload["content"]
