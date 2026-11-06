"""Tests for Phase 8: Gmail client and tools (fake service, no real email)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import integrations.gmail.gmail_client as gmail_client_module
from core.config_loader import GmailConfig
from core.tool_registry import ToolRegistry
from integrations.gmail.gmail_client import GmailClient
from security.credential_manager import CredentialManager
from tests.fakes import FakeKeyring


@pytest.fixture(autouse=True)
def _google_deps_available(monkeypatch):
    """Tests exercise logic paths, not the optional-dependency check."""
    monkeypatch.setattr(gmail_client_module, "_DEPS_AVAILABLE", True)


class FakeRequest:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeGmailService:
    """Fake of the gmail v1 service surface JARVIS uses."""

    def __init__(self) -> None:
        self.search_results = [
            {"id": "msg1", "threadId": "t1"},
            {"id": "msg2", "threadId": "t2"},
        ]
        self.snippets = {
            "msg1": "Meeting tomorrow at 10",
            "msg2": "Invoice attached",
        }
        self.full_messages = {
            "msg1": {
                "id": "msg1",
                "threadId": "t1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "boss@corp.example.com"},
                        {"name": "To", "value": "me@corp.example.com"},
                        {"name": "Subject", "value": "Meeting"},
                        {"name": "Date", "value": "Mon, 1 Nov 2026"},
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {
                                "data": base64.urlsafe_b64encode(
                                    "Please join the meeting.".encode()
                                ).decode()
                            },
                        }
                    ],
                },
            }
        }
        self.sent: list[dict] = []
        self.created_drafts: list[dict] = []
        self.last_query: str | None = None

    def users(self):
        return self

    def messages(self):
        return self

    def drafts(self):
        return self

    def list(self, userId=None, q=None, maxResults=None):
        self.last_query = q
        return FakeRequest({"messages": self.search_results})

    def get(self, userId=None, id=None, format=None):
        if format == "metadata":
            return FakeRequest({"id": id, "snippet": self.snippets.get(id, "")})
        return FakeRequest(self.full_messages[id])

    def send(self, userId=None, body=None):
        self.sent.append(body)
        return FakeRequest({"id": "sent-123"})

    def create(self, userId=None, body=None):
        self.created_drafts.append(body)
        return FakeRequest({"id": "draft-456"})


def _client(service: FakeGmailService, authorized: bool = True) -> GmailClient:
    config = GmailConfig(enabled=True)
    manager = CredentialManager(backend=FakeKeyring())
    if authorized:
        manager.set_secret(
            config.token_credential_ref,
            json.dumps({"token": "t", "refresh_token": "r", "scopes": []}),
        )
    return GmailClient(config, manager, service=service)


@pytest.mark.unit
class TestAuthorization:
    def test_not_authorized_without_token(self) -> None:
        assert _client(FakeGmailService(), authorized=False).is_authorized() is False

    def test_authorized_with_stored_token(self) -> None:
        assert _client(FakeGmailService()).is_authorized() is True

    def test_authorize_interactive_missing_secrets_file(self, tmp_path) -> None:
        client = _client(FakeGmailService())
        with pytest.raises(Exception, match="client secret file not found"):
            client.authorize_interactive(tmp_path / "nope.json")

    def test_token_lives_in_credential_store_not_disk(self, tmp_path) -> None:
        """Mirror what authorize_interactive stores after the OAuth flow."""
        manager = CredentialManager(backend=FakeKeyring())
        client = GmailClient(
            GmailConfig(enabled=True), manager, service=FakeGmailService()
        )
        token_data = {
            "token": "abc",
            "refresh_token": "ref",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "id",
            "client_secret": "secret",
            "scopes": ["s"],
        }
        manager.set_secret(
            client.config.token_credential_ref, json.dumps(token_data)
        )
        assert client.is_authorized() is True
        stored = json.loads(
            manager.get_secret(client.config.token_credential_ref)
        )
        assert stored["refresh_token"] == "ref"
        assert not list(Path(tmp_path).glob("*token*"))


@pytest.mark.unit
class TestApiOperations:
    def test_search_returns_summaries(self) -> None:
        service = FakeGmailService()
        client = _client(service)
        summaries = client.search_messages("is:unread")
        assert len(summaries) == 2
        assert summaries[0].message_id == "msg1"
        assert summaries[0].snippet == "Meeting tomorrow at 10"
        assert service.last_query == "is:unread"

    def test_read_message_decodes_body_and_headers(self) -> None:
        client = _client(FakeGmailService())
        content = client.read_message("msg1")
        assert content.sender == "boss@corp.example.com"
        assert content.subject == "Meeting"
        assert content.body_text == "Please join the meeting."

    def test_create_draft_does_not_send(self) -> None:
        service = FakeGmailService()
        client = _client(service)
        result = client.create_draft("a@b.c", "Hi", "Body text")
        assert "Draft created" in result
        assert service.sent == []  # never sent
        assert len(service.created_drafts) == 1
        raw = service.created_drafts[0]["message"]["raw"]
        decoded = base64.urlsafe_b64decode(raw).decode()
        assert "Hi" in decoded and "Body text" in decoded

    def test_send_message(self) -> None:
        service = FakeGmailService()
        client = _client(service)
        result = client.send_message("a@b.c", "Hi", "Body")
        assert "Sent" in result
        assert len(service.sent) == 1

    def test_send_encodes_mime_correctly(self) -> None:
        service = FakeGmailService()
        client = _client(service)
        client.send_message("a@b.c", "Subject line", "Body line")
        decoded = base64.urlsafe_b64decode(service.sent[0]["raw"]).decode()
        assert "Subject: Subject line" in decoded
        assert "Body line" in decoded


@pytest.mark.unit
class TestGmailTools:
    def _registry(self, authorized: bool = True, deps: bool = True):
        from integrations.gmail.gmail_tools import register_gmail_tools

        client = _client(FakeGmailService(), authorized=authorized)
        if not deps:
            import integrations.gmail.gmail_client as module

            original = module._DEPS_AVAILABLE
            module._DEPS_AVAILABLE = False
            try:
                client = GmailClient(
                    client.config, CredentialManager(backend=FakeKeyring())
                )
                registry = ToolRegistry()
                register_gmail_tools(registry, client)
            finally:
                module._DEPS_AVAILABLE = original
            return registry
        registry = ToolRegistry()
        register_gmail_tools(registry, client)
        return registry

    def test_tools_registered_when_authorized(self) -> None:
        risks = {t.name: t.risk for t in self._registry().list_tools()}
        assert risks == {
            "gmail_search": "low",
            "gmail_read": "low",
            "gmail_create_draft": "low",
            "gmail_send": "high",
        }

    def test_tools_skipped_when_not_authorized(self) -> None:
        assert self._registry(authorized=False).list_tools() == ()

    def test_tools_skipped_without_dependencies(self) -> None:
        assert self._registry(deps=False).list_tools() == ()

    def test_search_tool_formats(self) -> None:
        result = self._registry().execute("gmail_search", {"query": "is:unread"})
        assert result.success is True
        assert "msg1" in result.output
        assert "Meeting tomorrow" in result.output

    def test_read_tool_formats(self) -> None:
        result = self._registry().execute("gmail_read", {"message_id": "msg1"})
        assert result.success is True
        assert "boss@corp.example.com" in result.output
        assert "Please join the meeting." in result.output

    def test_draft_tool_creates_not_sends(self) -> None:
        result = self._registry().execute(
            "gmail_create_draft", {"to": "x@y.z", "subject": "S", "body": "B"}
        )
        assert result.success is True
        assert "Draft created" in result.output

    def test_send_tool_is_high_risk_gated(self) -> None:
        from core.config_loader import PermissionPolicy
        from security.permission_checker import PermissionChecker

        registry = self._registry()
        decision = PermissionChecker(PermissionPolicy()).check(
            "gmail_send", registry.get("gmail_send").risk
        )
        assert decision.approval_required is True
