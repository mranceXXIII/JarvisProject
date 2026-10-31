"""OpenAI-compatible adapter.

One implementation covers every OpenAI-chat-completions-compatible service:
OpenAI, Groq, Cerebras, OpenRouter, LM Studio, custom gateways, and custom
providers (JARVIS_Project_Context.md 5.1). Endpoint paths, base URLs, and
models are user-configured; no vendor SDK dependency.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from core.config_loader import ProviderConfig
from providers.base_adapter import (
    ChatRequest,
    ChatResponse,
    ConnectionTestResult,
    ProviderAdapter,
    ProviderCapabilities,
    ToolCall,
)
from providers.errors import ProviderError, ProviderResponseError
from providers.http_client import map_transport_error, raise_for_response

logger = logging.getLogger("jarvis.providers.openai_compatible")


class OpenAICompatibleAdapter(ProviderAdapter):
    """Adapter for OpenAI-chat-completions style APIs."""

    def __init__(
        self,
        config: ProviderConfig,
        base_url: str,
        api_key: str | None,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(config, base_url, api_key)
        self._session = session if session is not None else requests.Session()

    @property
    def provider_type(self) -> str:
        return "openai_compatible"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_generation=True,
            tool_calling=True,
            structured_output=True,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _chat_url(self) -> str:
        path = self._config.endpoint_path or "/chat/completions"
        return self._base_url + (path if path.startswith("/") else "/" + path)

    def test_connection(self) -> ConnectionTestResult:
        """Minimal safe check: GET the model list endpoint."""
        url = self._base_url + "/models"
        try:
            response = self._session.get(
                url, headers=self._headers(), timeout=self._config.timeout_seconds
            )
            payload = raise_for_response(self.name, response, "connection test")
        except ProviderError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        except Exception as exc:
            mapped = map_transport_error(self.name, exc, "connection test")
            return ConnectionTestResult(success=False, message=str(mapped))
        models = payload.get("data")
        count = len(models) if isinstance(models, list) else 0
        return ConnectionTestResult(
            success=True,
            message="endpoint reachable and authenticated",
            details={"models_listed": str(count), "base_url": self._base_url},
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self._config.model:
            raise ProviderResponseError(self.name, "no model configured for this provider")
        if request.tools:
            self._require_capability(self.capabilities.tool_calling, "tool calling")

        body = self._build_body(request)
        try:
            response = self._session.post(
                self._chat_url(),
                headers=self._headers(),
                json=body,
                timeout=self._config.timeout_seconds,
            )
            payload = raise_for_response(self.name, response, "chat request")
        except ProviderError:
            raise
        except Exception as exc:
            raise map_transport_error(self.name, exc, "chat request") from exc
        return self._parse_response(payload)

    def _build_body(self, request: ChatRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": request.messages,
            "stream": False,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        return body

    def _parse_response(self, payload: dict[str, Any]) -> ChatResponse:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError(self.name, "chat response contained no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        usage_raw = payload.get("usage") or {}
        usage = {
            key: int(value)
            for key, value in usage_raw.items()
            if isinstance(value, int)
        }
        return ChatResponse(
            provider_name=self.name,
            model=str(payload.get("model") or self._config.model),
            content=content if isinstance(content, str) else "",
            tool_calls=self._parse_tool_calls(message.get("tool_calls")),
            finish_reason=choices[0].get("finish_reason"),
            usage=usage,
        )

    def _parse_tool_calls(self, raw: Any) -> tuple[ToolCall, ...]:
        if not isinstance(raw, list):
            return ()
        parsed: list[ToolCall] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            function = item.get("function") or {}
            arguments_raw = function.get("arguments", "{}")
            try:
                arguments = (
                    json.loads(arguments_raw)
                    if isinstance(arguments_raw, str)
                    else arguments_raw
                )
            except json.JSONDecodeError:
                logger.warning("tool call %d had invalid JSON arguments; skipped", index)
                arguments = {}
            parsed.append(
                ToolCall(
                    id=str(item.get("id") or f"call_{index}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        return tuple(parsed)
