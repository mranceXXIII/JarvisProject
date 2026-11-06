"""Tests for Phase 9: Telegram and Discord adapters (fake HTTP, no network)."""

from __future__ import annotations

import pytest

from core.config_loader import DiscordConfig, TelegramConfig
from core.tool_registry import ToolRegistry
from integrations.discord.discord_client import DiscordClient, DiscordError
from integrations.messaging_tools import (
    register_discord_tools,
    register_telegram_tools,
)
from integrations.telegram.telegram_client import TelegramClient
from security.credential_manager import CredentialManager
from tests.fakes import FakeKeyring


class FakeTelegramAPI:
    """Records calls and returns scripted Telegram responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict) -> dict:
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, payload))
        if method == "getMe":
            return {"ok": True, "result": {"username": "my_jarvis_bot"}}
        if method == "getUpdates":
            return {
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "message": {
                            "message_id": 1,
                            "date": 1700000000,
                            "text": "hello jarvis",
                            "chat": {"id": 555, "title": "Test Group"},
                            "from": {"username": "alice"},
                        },
                    }
                ],
            }
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 77}}
        return {"ok": True, "result": {}}


class FakeDiscordAPI:
    """Records calls and returns scripted Discord responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method: str, url: str, kwargs: dict) -> object:
        path = url.split("/api/v10")[-1]
        self.calls.append((method, path, kwargs.get("headers", {})))
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization", "").startswith("Bot ")

        class Response:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        if path == "/users/@me":
            return Response({"username": "jarvis-bot"})
        if path == "/users/@me/guilds":
            return Response([{"id": "g1", "name": "My Server"}])
        if path == "/guilds/g1/channels":
            return Response(
                [
                    {"id": "c1", "name": "general", "type": 0},
                    {"id": "c2", "name": "voice-room", "type": 2},
                ]
            )
        if path.startswith("/channels/c1/messages") and method == "GET":
            return Response(
                [
                    {
                        "id": "m1",
                        "author": {"username": "bob"},
                        "content": "hello all",
                        "timestamp": "2026-11-06T10:00:00Z",
                    }
                ]
            )
        if path.startswith("/channels/") and method == "POST":
            return Response({"id": "m99"})
        return Response([])


def _telegram(authorized: bool = True):
    manager = CredentialManager(backend=FakeKeyring())
    api = FakeTelegramAPI()
    client = TelegramClient(TelegramConfig(enabled=True), manager, fetcher=api)
    if authorized:
        manager.set_secret(client.config.bot_token_ref, "fake-discord-token")
    return client, api, manager


@pytest.mark.unit
class TestTelegramClient:
    def test_not_authorized_without_token(self) -> None:
        client, _, _ = _telegram(authorized=False)
        assert client.is_authorized() is False

    def test_setup_validates_and_stores_token(self) -> None:
        client, api, manager = _telegram(authorized=False)
        message = client.setup_interactive("12345:fake-token")
        assert "@my_jarvis_bot" in message
        assert manager.has_secret(client.config.bot_token_ref)
        assert ("getMe", {}) in api.calls

    def test_setup_rejects_bad_token(self) -> None:
        client, _, _ = _telegram(authorized=False)
        from integrations.telegram.telegram_client import TelegramError

        def failing(url, payload):
            raise TelegramError("Telegram API error: 401 Unauthorized")

        client._fetcher = failing
        with pytest.raises(TelegramError, match="401"):
            client.setup_interactive("bad-token")

    def test_token_never_leaks_in_errors(self) -> None:
        client, _, _ = _telegram(authorized=False)
        with pytest.raises(Exception) as excinfo:
            client.get_me()
        assert "12345:fake-token" not in str(excinfo.value)

    def test_get_recent_messages_parses_updates(self) -> None:
        client, api, _ = _telegram()
        messages = client.get_recent_messages()
        assert len(messages) == 1
        assert messages[0].chat_id == 555
        assert messages[0].sender == "alice"
        assert messages[0].text == "hello jarvis"
        assert any(method == "getUpdates" for method, _ in api.calls)

    def test_send_message(self) -> None:
        client, api, _ = _telegram()
        result = client.send_message(555, "all done")
        assert "Sent to chat 555" in result
        assert any(
            method == "sendMessage" and payload.get("chat_id") == 555
            for method, payload in api.calls
        )


@pytest.mark.unit
class TestDiscordClient:
    def test_not_authorized_without_token(self) -> None:
        client, _, _ = _discord(authorized=False)
        assert client.is_authorized() is False

    def test_setup_validates_and_stores_token(self) -> None:
        client, api, manager = _discord(authorized=False)
        message = client.setup_interactive("fake-discord-token")
        assert "jarvis-bot" in message
        assert manager.has_secret(client.config.bot_token_ref)
        assert any(path == "/users/@me" for _m, path, _h in api.calls)

    def test_token_in_header_not_url(self) -> None:
        client, api, _ = _discord()
        client.list_guilds()
        _method, path, headers = api.calls[0]
        assert headers["Authorization"] == "Bot fake-discord-token"
        assert "fake-discord-token" not in path

    def test_list_guilds_and_channels(self) -> None:
        client, _, _ = _discord()
        guilds = client.list_guilds()
        assert guilds == [{"guild_id": "g1", "name": "My Server"}]
        channels = client.list_guild_channels("g1")
        assert [c.name for c in channels] == ["general"]  # voice filtered

    def test_read_and_send(self) -> None:
        client, api, _ = _discord()
        messages = client.get_recent_messages("c1")
        assert messages[0].author == "bob"
        assert messages[0].content == "hello all"
        result = client.send_message("c1", "all done")
        assert "Sent to channel c1" in result
        assert any(
            m == "POST" and path.startswith("/channels/c1/messages")
            for m, path, _h in api.calls
        )

    def test_http_error_raises_typed_error(self) -> None:
        client, _, _ = _discord(authorized=False)

        def failing(method, url, kwargs):
            raise DiscordError("Discord API error: HTTP 401")

        client._requester = failing
        with pytest.raises(DiscordError):
            client.list_guilds()


@pytest.mark.unit
class TestMessagingTools:
    def test_telegram_tools_registered_with_risks(self) -> None:
        client, _, _ = _telegram()
        registry = ToolRegistry()
        register_telegram_tools(registry, client)
        risks = {t.name: t.risk for t in registry.list_tools()}
        assert risks == {
            "telegram_read_messages": "low",
            "telegram_send_message": "high",
        }

    def test_telegram_tools_skipped_when_unauthorized(self) -> None:
        client, _, _ = _telegram(authorized=False)
        registry = ToolRegistry()
        register_telegram_tools(registry, client)
        assert registry.list_tools() == ()

    def test_discord_tools_registered_with_risks(self) -> None:
        client, _, _ = _discord()
        registry = ToolRegistry()
        register_discord_tools(registry, client)
        risks = {t.name: t.risk for t in registry.list_tools()}
        assert risks == {
            "discord_list_guilds": "low",
            "discord_list_channels": "low",
            "discord_read_messages": "low",
            "discord_send_message": "high",
        }

    def test_discord_tools_skipped_when_unauthorized(self) -> None:
        client, _, _ = _discord(authorized=False)
        registry = ToolRegistry()
        register_discord_tools(registry, client)
        assert registry.list_tools() == ()

    def test_telegram_read_tool_roundtrip(self) -> None:
        client, _, _ = _telegram()
        registry = ToolRegistry()
        register_telegram_tools(registry, client)
        result = registry.execute("telegram_read_messages", {})
        assert result.success is True
        assert "alice" in result.output
        assert "chat_id=555" in result.output

    def test_discord_read_and_send_roundtrip(self) -> None:
        client, _, _ = _discord()
        registry = ToolRegistry()
        register_discord_tools(registry, client)
        read = registry.execute("discord_read_messages", {"channel_id": "c1"})
        assert "bob" in read.output
        send = registry.execute(
            "discord_send_message", {"channel_id": "c1", "content": "done"}
        )
        assert send.success is True

    def test_send_tools_are_high_risk_gated(self) -> None:
        from core.config_loader import PermissionPolicy
        from security.permission_checker import PermissionChecker

        checker = PermissionChecker(PermissionPolicy())
        t_registry = ToolRegistry()
        register_telegram_tools(t_registry, _telegram()[0])
        d_registry = ToolRegistry()
        register_discord_tools(d_registry, _discord()[0])
        for registry, tool in (
            (t_registry, "telegram_send_message"),
            (d_registry, "discord_send_message"),
        ):
            assert checker.check(tool, registry.get(tool).risk).approval_required


def _discord(authorized: bool = True):
    manager = CredentialManager(backend=FakeKeyring())
    api = FakeDiscordAPI()
    client = DiscordClient(DiscordConfig(enabled=True), manager, requester=api)
    if authorized:
        manager.set_secret(client.config.bot_token_ref, "fake-discord-token")
    return client, api, manager
