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
from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from core.tool_registry import ToolExecutionResult
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
    tool_results: tuple = ()
    errors: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def needs_tool_execution(self) -> bool:
        """True when tool calls were requested but not executed."""
        return bool(self.tool_calls) and not self.tool_results


class JarvisAssistant:
    """Provider-independent text conversation with routing and fallback.

    When a tool registry and executor are provided, model tool calls are
    planned, approved, executed, and their results fed back to the provider
    for a final answer (one tool round; orchestration deepens in later
    phases).
    """

    def __init__(
        self,
        provider_manager: ProviderManager,
        router: AIRouter,
        planner: TaskPlanner | None = None,
        executor: TaskExecutor | None = None,
    ) -> None:
        self._providers = provider_manager
        self._router = router
        self._planner = planner
        self._executor = executor

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

            if response.tool_calls and self._planner is not None and self._executor is not None:
                return self._run_tool_round(
                    response, plan.candidates, request, errors
                )
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

    def _run_tool_round(
        self,
        response: ChatResponse,
        candidates,
        original_request: ChatRequest,
        errors: list[str],
    ) -> AssistantReply:
        """Plan, approve, execute the model's tool calls, then ask the
        provider for a final answer with the verified results."""
        plan = self._planner.plan(response.tool_calls)
        if plan.rejections:
            logger.info("tool rejections: %s", plan.rejections)
        executed: list[ToolExecutionResult] = []
        if plan.tasks:
            executed = list(self._executor.execute(plan.tasks))
        else:
            executed = [
                ToolExecutionResult(
                    tool="unknown", success=False, output="; ".join(plan.rejections)
                )
            ]

        follow_up = list(original_request.messages)
        follow_up.append(
            {
                "role": "assistant",
                "content": response.content
                or f"[requested tools: {', '.join(c.name for c in response.tool_calls)}]",
            }
        )
        follow_up.append(
            {
                "role": "user",
                "content": "Tool execution results (verified locally):\n"
                + "\n".join(
                    f"- {r.tool}: {'OK' if r.success else 'FAILED'} - {r.output}"
                    for r in executed
                )
                + "\nUse these verified results to answer.",
            }
        )

        retry_request = ChatRequest(
            messages=follow_up,
            tools=original_request.tools,
            temperature=original_request.temperature,
            max_tokens=original_request.max_tokens,
            sensitive=original_request.sensitive,
        )
        for provider in candidates:
            try:
                final = self._providers.chat(provider, retry_request)
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            return AssistantReply(
                success=True,
                text=final.content,
                provider_name=final.provider_name,
                model=final.model,
                tool_calls=response.tool_calls,
                tool_results=tuple(executed),
                errors=errors,
            )
        # No second round available: report tool results honestly.
        summary = "Tool results (no provider available for a final summary):\n" + "\n".join(
            f"- {r.tool}: {'OK' if r.success else 'FAILED'} - {r.output}"
            for r in executed
        )
        return AssistantReply(
            success=any(r.success for r in executed),
            text=summary,
            provider_name=response.provider_name,
            model=response.model,
            tool_calls=response.tool_calls,
            tool_results=tuple(executed),
            errors=errors,
        )


def _required_capabilities(tools: list[ToolSpec] | None) -> Any:
    """Build the capability requirement implied by a request."""
    from providers.base_adapter import ProviderCapabilities

    return ProviderCapabilities(tool_calling=bool(tools))
