from __future__ import annotations

import argparse
import asyncio
import sys

from ker.config import load_settings
from ker.logger import init_logger


def main() -> None:
    parser = argparse.ArgumentParser(prog="ker", description="Ker agent runtime")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("cli", help="Start Ker in CLI mode")
    sub.add_parser("gateway", help="Start Ker gateway with all channels")

    gh_copilot = sub.add_parser("github_copilot", help="GitHub Copilot commands")
    gh_sub = gh_copilot.add_subparsers(dest="gh_action")
    gh_sub.add_parser("login", help="Run GitHub Copilot OAuth login")

    args = parser.parse_args()

    if args.command is None:
        # Default to CLI mode
        args.command = "cli"

    if args.command == "cli":
        _run_cli()
    elif args.command == "gateway":
        _run_gateway()
    elif args.command == "github_copilot":
        if getattr(args, "gh_action", None) == "login":
            from ker.llm.github_copilot import oauth_login

            oauth_login()
        else:
            gh_copilot.print_help()
    else:
        parser.print_help()


def _run_cli() -> None:
    settings = load_settings()
    init_logger(settings.ker_root)

    from ker.channels.cli import CLIChannel
    from ker.gateway.gateway import Gateway

    gateway = Gateway(settings)
    cli = CLIChannel()
    gateway.register_channel(cli)

    print("Ker CLI ready. Type /help for commands.")
    asyncio.run(gateway.run())


def _run_gateway() -> None:
    settings = load_settings()
    init_logger(settings.ker_root)

    from ker.gateway.gateway import Gateway

    gateway = Gateway(settings)

    if settings.kerweb_enabled:
        # Prefer WebSocket channel, fall back to HTTP polling
        try:
            from ker.channels.kerweb_ws import KerWebWSChannel

            ws_url = settings.kerweb_base_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://") + "/api/agent/ws"
            gateway.register_channel(KerWebWSChannel(
                ws_url=ws_url,
                api_key=settings.kerweb_api_key,
                ker_root=settings.ker_root,
            ))
        except ImportError:
            from ker.channels.kerweb import KerWebPollingChannel, KerWebConfig

            kerweb_config = KerWebConfig(
                enabled=True,
                base_url=settings.kerweb_base_url,
                api_key=settings.kerweb_api_key,
                poll_interval_sec=settings.kerweb_poll_interval_sec,
            )
            gateway.register_channel(KerWebPollingChannel(kerweb_config))

    if settings.teams_enabled:
        from ker.channels.teams import TeamsChannel, TeamsConfig

        teams_config = TeamsConfig(
            enabled=True,
            chat_id=settings.teams_chat_id,
            poll_interval_sec=settings.teams_poll_interval_sec,
            mcp_command=settings.teams_mcp_command,
        )
        gateway.register_channel(TeamsChannel(teams_config))

    print("Ker gateway starting...")
    asyncio.run(gateway.run())


if __name__ == "__main__":
    main()
