"""Gmail tools (Phase 8, spec section 11).

Risks: search/read/draft = low; send = HIGH (approval dialog always shown
before anything is sent). Tools register only when the client is available
AND authorized; otherwise they are skipped honestly.
"""

from __future__ import annotations

import logging

from core.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry
from integrations.gmail.gmail_client import GmailClient

logger = logging.getLogger("jarvis.gmail.tools")


def _wrap_tool(tool_name: str, function):
    def execute(arguments: dict) -> ToolExecutionResult:
        try:
            output = function(**arguments)
            return ToolExecutionResult(tool=tool_name, success=True, output=str(output))
        except Exception as exc:
            logger.warning("tool '%s' failed: %s", tool_name, exc)
            return ToolExecutionResult(tool=tool_name, success=False, output=str(exc))

    return execute


def register_gmail_tools(registry: ToolRegistry, client: GmailClient) -> None:
    """Register Gmail tools when the client is usable."""
    if not client.available:
        logger.info(
            "Gmail tools skipped: Google API libraries not installed "
            "(python -m pip install -r requirements-gmail.txt)"
        )
        return
    if not client.is_authorized():
        logger.info(
            "Gmail tools skipped: not authorized yet (run "
            "'python -m integrations.gmail setup'; see docs/GOOGLE_GMAIL_SETUP.md)"
        )
        return

    def gmail_search(query: str) -> str:
        summaries = client.search_messages(query)
        if not summaries:
            return "No messages matched the search."
        lines = [
            f"[{i}] id={s.message_id} - {s.snippet}"
            for i, s in enumerate(summaries, start=1)
        ]
        return "\n".join(lines)

    def gmail_read(message_id: str) -> str:
        content = client.read_message(message_id)
        return (
            f"From: {content.sender}\nTo: {content.to}\n"
            f"Subject: {content.subject}\nDate: {content.date}\n\n"
            f"{content.body_text[:4000]}"
        )

    registry.register(
        ToolDefinition(
            name="gmail_search",
            description="Search Gmail messages with a Gmail search query",
            risk="low",
            parameters={
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g. 'from:x is:unread')",
                    "required": True,
                }
            },
        ),
        _wrap_tool("gmail_search", gmail_search),
    )
    registry.register(
        ToolDefinition(
            name="gmail_read",
            description="Read a Gmail message by its id",
            risk="low",
            parameters={
                "message_id": {
                    "type": "string",
                    "description": "message id from gmail_search",
                    "required": True,
                }
            },
        ),
        _wrap_tool("gmail_read", gmail_read),
    )
    registry.register(
        ToolDefinition(
            name="gmail_create_draft",
            description="Create a Gmail draft (never sends)",
            risk="low",
            parameters={
                "to": {
                    "type": "string",
                    "description": "recipient address",
                    "required": True,
                },
                "subject": {
                    "type": "string",
                    "description": "subject",
                    "required": True,
                },
                "body": {
                    "type": "string",
                    "description": "plain-text body",
                    "required": True,
                },
            },
        ),
        _wrap_tool(
            "gmail_create_draft",
            lambda to, subject, body: client.create_draft(to, subject, body),
        ),
    )
    registry.register(
        ToolDefinition(
            name="gmail_send",
            description=(
                "Send an email via Gmail (requires explicit approval; "
                "consequential and irreversible)"
            ),
            risk="high",
            parameters={
                "to": {
                    "type": "string",
                    "description": "recipient address",
                    "required": True,
                },
                "subject": {
                    "type": "string",
                    "description": "subject",
                    "required": True,
                },
                "body": {
                    "type": "string",
                    "description": "plain-text body",
                    "required": True,
                },
            },
        ),
        _wrap_tool(
            "gmail_send",
            lambda to, subject, body: client.send_message(to, subject, body),
        ),
    )
    logger.info("Gmail tools registered (search/read/draft low, send high)")
