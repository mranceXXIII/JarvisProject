"""Gmail OAuth client with secure token storage (spec section 11).

Authorization model:
- One-time interactive OAuth via ``authorize_interactive()`` (or the CLI:
  ``python -m integrations.gmail setup``) using the user's downloaded
  client-secret file.
- The resulting token JSON (refresh token included) is stored ONLY in the
  secure credential store under ``token_credential_ref`` - never on disk.
- Minimum necessary scopes by default: readonly + compose + send.

All API access goes through an injectable ``service`` object so tests run
against a fake and no real email is ever touched (spec section 21).
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from core.config_loader import GmailConfig
from security.credential_manager import CredentialManager

logger = logging.getLogger("jarvis.gmail.client")

try:  # optional dependencies
    from googleapiclient.discovery import build as _google_build

    _DEPS_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment
    _google_build = None
    _DEPS_AVAILABLE = False

API_SERVICE_NAME = "gmail"
API_VERSION = "v1"


class GmailError(RuntimeError):
    """Raised when a Gmail operation cannot be completed."""


@dataclass(frozen=True)
class MessageSummary:
    """Lightweight message info from a search."""

    message_id: str
    thread_id: str
    snippet: str


@dataclass(frozen=True)
class MessageContent:
    """A full message with headers and decoded body text."""

    message_id: str
    thread_id: str
    sender: str
    to: str
    subject: str
    date: str
    body_text: str


def _decode_body_part(payload: dict[str, Any]) -> str:
    """Recursively extract text/plain content from a Gmail payload."""
    body = payload.get("body") or {}
    data = body.get("data")
    if payload.get("mimeType") == "text/plain" and isinstance(data, str):
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts") or []:
        extracted = _decode_body_part(part)
        if extracted:
            return extracted
    if isinstance(data, str):
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


def _header(payload: dict[str, Any], name: str) -> str:
    for header in payload.get("headers") or []:
        if header.get("name", "").lower() == name.lower():
            return str(header.get("value", ""))
    return ""


class GmailClient:
    """Gmail API wrapper with credential-store-backed OAuth tokens."""

    def __init__(
        self,
        config: GmailConfig,
        credential_manager: CredentialManager,
        service: Any = None,
        project_root: Path | None = None,
    ) -> None:
        self._config = config
        self._credentials = credential_manager
        self._service = service
        self._project_root = (
            project_root if project_root is not None else Path.cwd()
        )

    # -- availability and authorization ---------------------------------

    @property
    def available(self) -> bool:
        """True when the Google API libraries are installed."""
        return _DEPS_AVAILABLE

    @property
    def config(self) -> GmailConfig:
        return self._config

    def is_authorized(self) -> bool:
        """True when a stored OAuth token exists in the credential store."""
        return self._credentials.has_secret(self._config.token_credential_ref)

    def secrets_file_path(self) -> Path:
        path = Path(self._config.client_secrets_file)
        if not path.is_absolute():
            path = self._project_root / path
        return path

    def authorize_interactive(self, client_secrets_path: Path | None = None) -> str:
        """Run the one-time OAuth flow and store the token securely.

        This is the manual-setup entry point. Opens a local browser window;
        requires the client-secret file downloaded from Google Cloud.
        """
        if not _DEPS_AVAILABLE:
            raise GmailError(
                "Google API libraries are not installed; run "
                "python -m pip install -r requirements-gmail.txt"
            )
        secrets_path = client_secrets_path or self.secrets_file_path()
        if not secrets_path.is_file():
            raise GmailError(
                f"client secret file not found: {secrets_path} (see "
                "docs/GOOGLE_GMAIL_SETUP.md)"
            )
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            str(secrets_path), self._config.scopes
        )
        credentials = flow.run_local_server(port=0)
        token_data = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
        }
        self._credentials.set_secret(
            self._config.token_credential_ref,
            json.dumps(token_data),
        )
        logger.info(
            "Gmail OAuth token stored in credential store under '%s'",
            self._config.token_credential_ref,
        )
        return (
            f"Gmail authorized; token stored as "
            f"'{self._config.token_credential_ref}'"
        )

    def revoke(self) -> str:
        """Remove the stored token (also revoke via Google account page)."""
        if self.is_authorized():
            self._credentials.delete_secret(self._config.token_credential_ref)
        return "Stored Gmail token removed."

    def _load_credentials(self) -> Any:
        from google.oauth2.credentials import Credentials

        try:
            token_json = self._credentials.get_secret(
                self._config.token_credential_ref
            )
        except Exception as exc:
            raise GmailError(
                "Gmail is not authorized yet; run "
                "'python -m integrations.gmail setup' (see "
                "docs/GOOGLE_GMAIL_SETUP.md)"
            ) from exc
        data = json.loads(token_json)
        return Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
        )

    def _get_service(self) -> Any:
        """Return the injected test service, or build the real one."""
        if self._service is not None:
            return self._service
        if not _DEPS_AVAILABLE:
            raise GmailError(
                "Google API libraries are not installed; run "
                "python -m pip install -r requirements-gmail.txt"
            )
        credentials = self._load_credentials()
        return _google_build(
            API_SERVICE_NAME, API_VERSION, credentials=credentials
        )

    # -- API operations ----------------------------------------------------

    def search_messages(self, query: str, max_results: int | None = None) -> list[MessageSummary]:
        """Search messages with a Gmail query; returns lightweight summaries."""
        service = self._get_service()
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=max_results or self._config.max_results,
            )
            .execute()
        )
        summaries: list[MessageSummary] = []
        for item in response.get("messages") or []:
            detail = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="metadata")
                .execute()
            )
            summaries.append(
                MessageSummary(
                    message_id=item["id"],
                    thread_id=item.get("threadId", ""),
                    snippet=str(detail.get("snippet", "")),
                )
            )
        return summaries

    def read_message(self, message_id: str) -> MessageContent:
        """Fetch and decode one full message."""
        service = self._get_service()
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        payload = message.get("payload") or {}
        return MessageContent(
            message_id=str(message.get("id", message_id)),
            thread_id=str(message.get("threadId", "")),
            sender=_header(payload, "From"),
            to=_header(payload, "To"),
            subject=_header(payload, "Subject"),
            date=_header(payload, "Date"),
            body_text=_decode_body_part(payload),
        )

    def create_draft(self, to: str, subject: str, body: str) -> str:
        """Create a draft (never sends). Returns a confirmation string."""
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        service = self._get_service()
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
            .execute()
        )
        draft_id = draft.get("id", "unknown")
        logger.info("draft created (id=%s) to %s", draft_id, to)
        return f"Draft created (id: {draft_id}) to {to} - subject: {subject}"

    def send_message(self, to: str, subject: str, body: str) -> str:
        """Send an email. HIGH RISK: the approval system must gate this."""
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        service = self._get_service()
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": encoded})
            .execute()
        )
        sent_id = sent.get("id", "unknown")
        logger.info("message sent (id=%s) to %s", sent_id, to)
        return f"Sent (id: {sent_id}) to {to} - subject: {subject}"


def main(argv: list[str] | None = None) -> int:
    """Manual setup CLI: python -m integrations.gmail setup|status|revoke."""
    import argparse

    from core.config_loader import load_settings
    from core.logging_setup import setup_logging
    from security.credential_manager import CredentialManager

    parser = argparse.ArgumentParser(
        description="Gmail OAuth setup for JARVIS (see docs/GOOGLE_GMAIL_SETUP.md)"
    )
    parser.add_argument("command", choices=["setup", "status", "revoke"])
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config",
    )
    args = parser.parse_args(argv)

    app_config = load_settings(args.config_dir)
    setup_logging(app_config.logging)
    gmail_config = app_config.gmail
    manager = CredentialManager()
    client = GmailClient(gmail_config, manager)

    if args.command == "status":
        print(f"Google libraries installed: {client.available}")
        print(f"Authorized: {client.is_authorized()}")
        print(f"Client secrets file: {client.secrets_file_path()}")
        print(f"Scopes: {', '.join(gmail_config.scopes)}")
        return 0
    if args.command == "revoke":
        print(client.revoke())
        return 0
    print(client.authorize_interactive())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
