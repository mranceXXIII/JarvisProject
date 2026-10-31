"""Anthropic adapter (Messages REST API, no vendor SDK).

Authenticates with ``x-api-key`` plus the required ``anthropic-version``
header. Connection tests use the low-cost model list endpoint.
"""

from __future__ import annotations

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

logger = logging.getLogger("jarvis.providers.anthropic")

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdapter(ProviderAdapter):
    """Adapter for the Anthropic Messages API."""

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
        return "anthropic"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_generation=True,
            tool_calling=True,
            structured_output=True,
            image_input=True,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def test_connection(self) -> ConnectionTestResult:
        """Minimal safe check: GET /v1/models."""
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
            details={"models_listed": str(count)},
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self._config.model:
            raise ProviderResponseError(self.name, "no model configured for this provider")
        if request.tools:
            self._require_capability(self.capabilities.tool_calling, "tool calling")
        if not self._api_key:
            raise ProviderError(self.name, "no API key available (check credential_ref)")

        body = self._build_body(request)
        url = self._base_url + "/messages"
        try:
            response = self._session.post(
                url,
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
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            role = message.get("role", "user")
            text = message.get("content", "")
            if role == "system":
                system_parts.append(text)
                continue
            messages.append({"role": role, "content": text})
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
        }
        if system_parts:
            body["system"] = "\n".join(system_parts)
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in request.tools
            ]
        return body

    def _parse_response(self, payload: dict[str, Any]) -> ChatResponse:
        content_blocks = payload.get("content")
        if not isinstance(content_blocks, list):
            raise ProviderResponseError(self.name, "chat response contained no content")
        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text" and isinstance(block.get("text"), str):
                text_chunks.append(block["text"])
            elif block_type == "tool_use":
                tool_input = block.get("input", {})
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id") or "call_unknown"),
                        name=str(block.get("name") or ""),
                        arguments=tool_input if isinstance(tool_input, dict) else {},
                    )
                )
        usage_raw = payload.get("usage") or {}
        usage = {
            key: int(value)
            for key, value in usage_raw.items()
            if isinstance(value, int)
        }
        return ChatResponse(
            provider_name=self.name,
            model=str(payload.get("model") or self._config.model),
            content="".join(text_chunks),
            tool_calls=tuple(tool_calls),
            finish_reason=payload.get("stop_reason"),
            usage=usage,
        )
