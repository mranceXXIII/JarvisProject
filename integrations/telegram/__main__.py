"""Manual Telegram setup CLI (see docs/TELEGRAM_SETUP.md)."""

from __future__ import annotations

from pathlib import Path

from core.config_loader import load_settings
from core.logging_setup import setup_logging
from integrations.telegram.telegram_client import TelegramClient
from security.credential_manager import CredentialManager


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Telegram setup for JARVIS (see docs/TELEGRAM_SETUP.md)"
    )
    parser.add_argument("command", choices=["setup", "status", "revoke"])
    parser.add_argument("--token", help="bot token (prompted if omitted)")
    args = parser.parse_args()

    app_config = load_settings(Path.cwd() / "config")
    setup_logging(app_config.logging)
    manager = CredentialManager()
    client = TelegramClient(app_config.telegram, manager)

    if args.command == "status":
        print(f"Authorized: {client.is_authorized()}")
        if client.is_authorized():
            try:
                me = client.get_me()
                print(f"Bot: @{me.get('result', {}).get('username', '?')}")
            except Exception as exc:
                print(f"Token check failed: {exc}")
        return 0
    if args.command == "revoke":
        if client.is_authorized():
            manager.delete_secret(app_config.telegram.bot_token_ref)
        print("Stored Telegram token removed.")
        return 0
    print(client.setup_interactive(args.token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from integrations.telegram.telegram_client import main

if __name__ == "__main__":
    raise SystemExit(main())
