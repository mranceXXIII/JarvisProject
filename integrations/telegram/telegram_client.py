"""Telegram Bot API client with secure token storage (spec section 12).

Platform limitations (documented honestly, spec section 12):
- Bots can only see messages sent to them directly or in groups they are a
  member of AFTER activation - arbitrary chat history is not accessible.
- getUpdates returns recent updates only (roughly the last 24 hours).
- Sending is a HIGH risk action, gated by the approval system.

The token is stored in the secure credential store, never in files. The
HTTP layer is injectable so tests never touch the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import requests

from core.config_loader import TelegramConfig
from security.credential_manager import CredentialManager

logger = logging.getLogger("jarvis.telegram")

API_BASE = "https://api.telegram.org"


class TelegramError(RuntimeError):
    """Raised when a Telegram operation fails (never exposes the token)."""


@dataclass(frozen=True)
class TelegramMessage:
    """One incoming message visible to the bot."""

    message_id: int
    chat_id: int
    chat_title: str
    sender: str
    text: str
    date: str


class TelegramClient:
    """Telegram Bot API wrapper with credential-store tokens."""

    def __init__(
        self,
        config: TelegramConfig,
        credential_manager: CredentialManager,
        fetcher: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._config = config
        self._credentials = credential_manager
        self._fetcher = fetcher if fetcher is not None else self._default_fetcher
        self._update_offset = 0

    @property
    def available(self) -> bool:
        """Telegram needs only ``requests``, so it is always available."""
        return True

    @property
    def config(self) -> TelegramConfig:
        return self._config

    def is_authorized(self) -> bool:
        return self._credentials.has_secret(self._config.bot_token_ref)

    def _token(self) -> str:
        try:
            return self._credentials.get_secret(self._config.bot_token_ref)
        except Exception as exc:
            raise TelegramError(
                "Telegram is not set up yet; run "
                "'python -m integrations.telegram setup' (see "
                "docs/TELEGRAM_SETUP.md)"
            ) from exc

    @staticmethod
    def _default_fetcher(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(url, json=payload, timeout=15)
        data = response.json()
        if response.status_code != 200 or not data.get("ok"):
            # Never include the URL (it contains the token) in errors.
            raise TelegramError(
                f"Telegram API error: {data.get('description', 'unknown error')}"
            )
        return data

    def _call(self, method: str, **params: Any) -> dict[str, Any]:
        token = self._token()
        return self._call_with_token(token, method, **params)

    def _call_with_token(
        self, token: str, method: str, **params: Any
    ) -> dict[str, Any]:
        url = f"{API_BASE}/bot{token}/{method}"
        try:
            return self._fetcher(url, params)
        except TelegramError:
            raise
        except Exception as exc:
            raise TelegramError(
                f"Telegram request failed: {type(exc).__name__}"
            ) from exc

    def get_me(self) -> dict[str, Any]:
        """Bot identity check (used by setup and status)."""
        return self._call("getMe")

    # -- setup -------------------------------------------------------------

    def setup_interactive(self, token: str | None = None) -> str:
        """Store the bot token (prompts securely when omitted)."""
        import getpass

        if not token:
            token = getpass.getpass(
                "Paste the Telegram bot token from @BotFather (input hidden): "
            ).strip()
        if not token:
            raise TelegramError("no token provided")
        me = self._call_with_token(token, "getMe")
        bot_name = me.get("result", {}).get("username", "?")
        self._credentials.set_secret(self._config.bot_token_ref, token)
        return f"Telegram bot '@{bot_name}' verified and token stored."

    # -- messaging -----------------------------------------------------------

    def get_recent_messages(self, limit: int | None = None) -> list[TelegramMessage]:
        """Poll recent updates; returns messages visible to the bot.

        Limitation: only updates since the bot's last poll (and within
        Telegram's ~24h retention) are returned - a platform rule.
        """
        response = self._call(
            "getUpdates",
            offset=self._update_offset,
            timeout=self._config.poll_timeout_seconds,
            limit=limit or self._config.max_messages,
        )
        messages: list[TelegramMessage] = []
        for update in response.get("result") or []:
            self._update_offset = max(
                self._update_offset, update.get("update_id", 0) + 1
            )
            message = update.get("message")
            if not message:
                continue
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            messages.append(
                TelegramMessage(
                    message_id=message.get("message_id", 0),
                    chat_id=chat.get("id", 0),
                    chat_title=str(
                        chat.get("title") or chat.get("username") or "private"
                    ),
                    sender=str(
                        sender.get("username")
                        or sender.get("first_name")
                        or "unknown"
                    ),
                    text=str(message.get("text") or ""),
                    date=str(message.get("date", "")),
                )
            )
        return messages[-(limit or self._config.max_messages):]

    def send_message(self, chat_id: int, text: str) -> str:
        """Send a message. HIGH RISK: approval must gate this call."""
        result = self._call("sendMessage", chat_id=chat_id, text=text)
        message_id = result.get("result", {}).get("message_id", "?")
        logger.info("telegram message sent to chat %s", chat_id)
        return f"Sent to chat {chat_id} (message id: {message_id})"
