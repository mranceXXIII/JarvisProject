"""Discord bot client with secure token storage (spec section 12).

Platform limitations (documented honestly, spec section 12):
- The bot reads channels only in servers it was explicitly invited to.
- The Message Content intent must be enabled in the Developer Portal and
  granted during the invite, or message content arrives empty.
- Discord bots cannot join private channels without permission.

The token is sent via the Authorization header (never in URLs) and stored
in the secure credential store. The HTTP layer is injectable for tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import requests

from core.config_loader import DiscordConfig
from security.credential_manager import CredentialManager

logger = logging.getLogger("jarvis.discord")


class DiscordError(RuntimeError):
    """Raised when a Discord operation fails (never exposes the token)."""


@dataclass(frozen=True)
class DiscordMessage:
    """One channel message."""

    message_id: str
    channel_id: str
    author: str
    content: str
    timestamp: str


@dataclass(frozen=True)
class DiscordChannel:
    """One channel the bot can see in a guild."""

    channel_id: str
    name: str
    guild_id: str
    channel_type: int


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {token}"}


class DiscordClient:
    """Discord REST API wrapper with credential-store tokens."""

    def __init__(
        self,
        config: DiscordConfig,
        credential_manager: CredentialManager,
        requester: Callable[[str, str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._config = config
        self._credentials = credential_manager
        self._requester = (
            requester if requester is not None else self._default_requester
        )

    @property
    def available(self) -> bool:
        """Discord needs only ``requests``, so it is always available."""
        return True

    @property
    def config(self) -> DiscordConfig:
        return self._config

    def is_authorized(self) -> bool:
        return self._credentials.has_secret(self._config.bot_token_ref)

    def _token(self) -> str:
        try:
            return self._credentials.get_secret(self._config.bot_token_ref)
        except Exception as exc:
            raise DiscordError(
                "Discord is not set up yet; run "
                "'python -m integrations.discord setup' (see "
                "docs/DISCORD_SETUP.md)"
            ) from exc

    @staticmethod
    def _default_requester(method: str, url: str, kwargs: dict[str, Any]) -> Any:
        response = requests.request(method, url, timeout=15, **kwargs)
        if response.status_code >= 400:
            raise DiscordError(
                f"Discord API error: HTTP {response.status_code} "
                f"{response.text[:200]}"
            )
        return response

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request_with_token(self._token(), method, path, **kwargs)

    def _request_with_token(
        self, token: str, method: str, path: str, **kwargs: Any
    ) -> Any:
        headers = {**_bearer(token), **(kwargs.pop("headers", {}) or {})}
        url = f"{self._config.api_base}{path}"
        try:
            return self._requester(method, url, {**kwargs, "headers": headers})
        except DiscordError:
            raise
        except Exception as exc:
            raise DiscordError(
                f"Discord request failed: {type(exc).__name__}"
            ) from exc

    def setup_interactive(self, token: str | None = None) -> str:
        """Store the bot token (prompts securely when omitted)."""
        import getpass

        if not token:
            token = getpass.getpass(
                "Paste the Discord bot token (input hidden): "
            ).strip()
        if not token:
            raise DiscordError("no token provided")
        me = self._request_with_token(token, "GET", "/users/@me").json()
        username = me.get("username", "?")
        self._credentials.set_secret(self._config.bot_token_ref, token)
        return f"Discord bot '{username}' verified and token stored."

    # -- messaging -------------------------------------------------------------

    def list_guilds(self) -> list[dict[str, Any]]:
        """Servers the bot is a member of."""
        response = self._request("GET", "/users/@me/guilds")
        return [
            {"guild_id": g.get("id", ""), "name": g.get("name", "")}
            for g in response.json()
        ]

    def list_guild_channels(self, guild_id: str) -> list[DiscordChannel]:
        """Text channels in a guild (for finding channel IDs)."""
        response = self._request("GET", f"/guilds/{guild_id}/channels")
        channels: list[DiscordChannel] = []
        for channel in response.json():
            if channel.get("type") in (0, 5):  # text/announcement channels
                channels.append(
                    DiscordChannel(
                        channel_id=str(channel.get("id", "")),
                        name=str(channel.get("name", "")),
                        guild_id=guild_id,
                        channel_type=int(channel.get("type", 0)),
                    )
                )
        return channels

    def get_recent_messages(
        self, channel_id: str, limit: int | None = None
    ) -> list[DiscordMessage]:
        """Fetch the most recent messages from a channel."""
        response = self._request(
            "GET",
            f"/channels/{channel_id}/messages",
            params={"limit": limit or self._config.max_messages},
        )
        messages: list[DiscordMessage] = []
        for message in response.json():
            author = message.get("author") or {}
            messages.append(
                DiscordMessage(
                    message_id=str(message.get("id", "")),
                    channel_id=channel_id,
                    author=str(author.get("username", "unknown")),
                    content=str(message.get("content", "")),
                    timestamp=str(message.get("timestamp", "")),
                )
            )
        return messages

    def send_message(self, channel_id: str, content: str) -> str:
        """Post a message. HIGH RISK: approval must gate this call."""
        response = self._request(
            "POST",
            f"/channels/{channel_id}/messages",
            json={"content": content},
        )
        message_id = response.json().get("id", "?")
        logger.info("discord message sent to channel %s", channel_id)
        return f"Sent to channel {channel_id} (message id: {message_id})"
