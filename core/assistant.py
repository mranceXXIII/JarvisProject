"""JARVIS assistant: text conversation and tool calling (Phase 2).

Handles a user request end to end at the AI layer:
1. Ask the router for an ordered provider plan (capability- and
   privacy-aware).
2. Try providers in order; on a provider failure, log it (redacted) and fall
   back to the next candidate.
3. Return a verified reply (the provider's own response) or an honest
   failure summary - never claim success without a real response.

Tool execution/orchestration and permission checks arrive in Phase 4; tool
*calls requested by the model* are surfaced to the caller here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.ai_router import AIRouter, DEFAULT_CATEGORY, RoutingError
from providers.base_adapter import ChatRequest, ChatResponse, ToolSpec
from providers.errors import ProviderError
from providers.provider_manager import ProviderManager

logger = logging.getLogger("jarvis.core.assistant")


@dataclass
class AssistantReply:
    """The outcome of one assistant interaction."""

    success: bool
    text: str
    provider_name: str | None = None
    model: str | None = None
    tool_calls: tuple = ()
    errors: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def needs_tool_execution(self) -> bool:
        """True when the model requested tools but none were provided."""
        return bool(self.tool_calls)


class JarvisAssistant:
    """Provider-independent text conversation with routing and fallback."""

    def __init__(self, provider_manager: ProviderManager, router: AIRouter) -> None:
        self._providers = provider_manager
        self._router = router

    def handle_text(
        self,
        text: str,
        *,
        category: str = DEFAULT_CATEGORY,
        sensitive: bool = False,
        history: list[dict[str, str]] | None = None,
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AssistantReply:
        """Process one user text request.

        Args:
            text: the user's message.
            category: task category for routing (e.g. general_conversation).
            sensitive: when True, external fallback is restricted per routing
                configuration.
            history: prior messages [{"role": ..., "content": ...}].
            tools: optional tool definitions the model may call.
        """
        if not text.strip():
            return AssistantReply(success=False, text="empty request")

        messages: list[dict[str, str]] = list(history or [])
        messages.append({"role": "user", "content": text})

        try:
            plan = self._router.build_plan(
                category=category,
                required=_required_capabilities(tools),
                sensitive=sensitive,
            )
        except RoutingError as exc:
            logger.warning("routing failed: %s", exc)
            return AssistantReply(success=False, text=str(exc), errors=[str(exc)])

        errors: list[str] = []
        for provider in plan.candidates:
            request = ChatRequest(
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                sensitive=sensitive,
            )
            try:
                response = self._providers.chat(provider, request)
            except ProviderError as exc:
                logger.warning("provider '%s' failed: %s", provider.name, exc)
                errors.append(str(exc))
                continue
            return self._to_reply(response, errors)

        summary = "All configured providers failed to answer this request."
        return AssistantReply(success=False, text=summary, errors=errors)

    @staticmethod
    def _to_reply(response: ChatResponse, errors: list[str]) -> AssistantReply:
        return AssistantReply(
            success=True,
            text=response.content,
            provider_name=response.provider_name,
            model=response.model,
            tool_calls=response.tool_calls,
            errors=errors,
            usage=dict(response.usage),
        )


def _required_capabilities(tools: list[ToolSpec] | None) -> Any:
    """Build the capability requirement implied by a request."""
    from providers.base_adapter import ProviderCapabilities

    return ProviderCapabilities(tool_calling=bool(tools))
