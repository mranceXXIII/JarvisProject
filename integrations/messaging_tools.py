"""Registration of Phase 9 messaging tools (spec section 12).

Risks: reading = low; sending = HIGH (approval dialog always shown).
Tools register only when the adapter is enabled AND authorized; otherwise
skipped with an honest log message.
"""

from __future__ import annotations

import logging

from core.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry
from integrations.discord.discord_client import DiscordClient
from integrations.telegram.telegram_client import TelegramClient

logger = logging.getLogger("jarvis.messaging.tools")


def _wrap_tool(tool_name: str, function):
    def execute(arguments: dict) -> ToolExecutionResult:
        try:
            output = function(**arguments)
            return ToolExecutionResult(tool=tool_name, success=True, output=str(output))
        except Exception as exc:
            logger.warning("tool '%s' failed: %s", tool_name, exc)
            return ToolExecutionResult(tool=tool_name, success=False, output=str(exc))

    return execute


def register_telegram_tools(registry: ToolRegistry, client: TelegramClient) -> None:
    """Register Telegram read (low) and send (high) tools."""
    if not client.is_authorized():
        logger.info(
            "Telegram tools skipped: not set up (run "
            "'python -m integrations.telegram setup'; see docs/TELEGRAM_SETUP.md)"
        )
        return

    def telegram_read_messages() -> str:
        messages = client.get_recent_messages()
        if not messages:
            return (
                "No recent messages. Note: Telegram bots only receive "
                "messages sent to them/in their groups after activation."
            )
        lines = [
            f"[{m.chat_title}] {m.sender}: {m.text} (chat_id={m.chat_id})"
            for m in messages
        ]
        return "\n".join(lines)

    registry.register(
        ToolDefinition(
            name="telegram_read_messages",
            description=(
                "Read recent Telegram messages visible to the JARVIS bot "
                "(only messages sent to it/in its groups after activation)"
            ),
            risk="low",
            parameters={},
        ),
        _wrap_tool("telegram_read_messages", telegram_read_messages),
    )
    registry.register(
        ToolDefinition(
            name="telegram_send_message",
            description=(
                "Send a Telegram message to a chat (requires explicit "
                "approval; consequential)"
            ),
            risk="high",
            parameters={
                "chat_id": {
                    "type": "integer",
                    "description": "target chat id (from telegram_read_messages)",
                    "required": True,
                },
                "text": {
                    "type": "string",
                    "description": "message text",
                    "required": True,
                },
            },
        ),
        _wrap_tool(
            "telegram_send_message",
            lambda chat_id, text: client.send_message(int(chat_id), text),
        ),
    )
    logger.info("Telegram tools registered (read low, send high)")


def register_discord_tools(registry: ToolRegistry, client: DiscordClient) -> None:
    """Register Discord list/read (low) and send (high) tools."""
    if not client.is_authorized():
        logger.info(
            "Discord tools skipped: not set up (run "
            "'python -m integrations.discord setup'; see docs/DISCORD_SETUP.md)"
        )
        return
    register_discord_tools_authorized(registry, client)


def register_discord_tools_authorized(
    registry: ToolRegistry, client: DiscordClient
) -> None:
    """Tool registration body for an authorized Discord client."""
    def discord_list_guilds() -> str:
        guilds = client.list_guilds()
        if not guilds:
            return "The bot is not a member of any server yet."
        return "\n".join(
            f"- {g['name']} (guild_id={g['guild_id']})" for g in guilds
        )

    def discord_list_channels(guild_id: str) -> str:
        channels = client.list_guild_channels(guild_id)
        if not channels:
            return "No text channels visible in this server."
        return "\n".join(
            f"- #{c.name} (channel_id={c.channel_id})" for c in channels
        )

    def discord_read_messages(channel_id: str) -> str:
        messages = client.get_recent_messages(channel_id)
        if not messages:
            return "No recent messages in this channel."
        return "\n".join(
            f"[{m.timestamp}] {m.author}: {m.content}" for m in messages
        )

    registry.register(
        ToolDefinition(
            name="discord_list_guilds",
            description="List the Discord servers the JARVIS bot is in",
            risk="low",
            parameters={},
        ),
        _wrap_tool("discord_list_guilds", discord_list_guilds),
    )
    registry.register(
        ToolDefinition(
            name="discord_list_channels",
            description="List text channels of a Discord server",
            risk="low",
            parameters={
                "guild_id": {
                    "type": "string",
                    "description": "guild id from discord_list_guilds",
                    "required": True,
                }
            },
        ),
        _wrap_tool("discord_list_channels", discord_list_channels),
    )
    registry.register(
        ToolDefinition(
            name="discord_read_messages",
            description="Read recent messages from a Discord channel",
            risk="low",
            parameters={
                "channel_id": {
                    "type": "string",
                    "description": "channel id from discord_list_channels",
                    "required": True,
                }
            },
        ),
        _wrap_tool("discord_read_messages", discord_read_messages),
    )
    registry.register(
        ToolDefinition(
            name="discord_send_message",
            description=(
                "Post a message to a Discord channel (requires explicit "
                "approval; consequential)"
            ),
            risk="high",
            parameters={
                "channel_id": {
                    "type": "string",
                    "description": "target channel id",
                    "required": True,
                },
                "content": {
                    "type": "string",
                    "description": "message content",
                    "required": True,
                },
            },
        ),
        _wrap_tool(
            "discord_send_message",
            lambda channel_id, content: client.send_message(channel_id, content),
        ),
    )
    logger.info("Discord tools registered (list/read low, send high)")
