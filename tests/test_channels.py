import asyncio
import pytest
from ker.channels.cli import CLIChannel
from ker.channels.kerweb import KerWebChannel, KerWebConfig


@pytest.mark.asyncio
async def test_cli_channel_send(capsys):
    ch = CLIChannel()
    result = await ch.send("user", "hello")
    assert result is True
    captured = capsys.readouterr()
    assert "hello" in captured.out


@pytest.mark.asyncio
async def test_cli_channel_receive_empty():
    ch = CLIChannel()
    msg = await ch.receive()
    assert msg is None


def test_kerweb_config_defaults():
    config = KerWebConfig()
    assert config.enabled is False
    assert config.base_url == "http://127.0.0.1:3000"


@pytest.mark.asyncio
async def test_kerweb_disabled():
    ch = KerWebChannel(KerWebConfig(enabled=False))
    msg = await ch.receive()
    assert msg is None
    result = await ch.send("user", "test")
    assert result is False
