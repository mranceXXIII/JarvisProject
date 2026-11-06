"""Discord setup CLI (see docs/DISCORD_SETUP.md)."""

from __future__ import annotations

from pathlib import Path

from core.config_loader import load_settings
from core.logging_setup import setup_logging
from integrations.discord.discord_client import DiscordClient
from security.credential_manager import CredentialManager


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Discord setup for JARVIS (see docs/DISCORD_SETUP.md)"
    )
    parser.add_argument("command", choices=["setup", "status", "revoke"])
    parser.add_argument("--token", help="bot token (prompted if omitted)")
    args = parser.parse_args()

    app_config = load_settings(Path.cwd() / "config")
    setup_logging(app_config.logging)
    manager = CredentialManager()
    client = DiscordClient(app_config.discord, manager)

    if args.command == "status":
        print(f"Authorized: {client.is_authorized()}")
        if client.is_authorized():
            try:
                guilds = client.list_guilds()
                print(f"Member of {len(guilds)} server(s).")
                for guild in guilds[:5]:
                    print(f"- {guild['name']} ({guild['guild_id']})")
            except Exception as exc:
                print(f"Token check failed: {exc}")
        return 0
    if args.command == "revoke":
        if client.is_authorized():
            manager.delete_secret(app_config.discord.bot_token_ref)
        print("Stored Discord token removed.")
        return 0
    print(client.setup_interactive(args.token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
