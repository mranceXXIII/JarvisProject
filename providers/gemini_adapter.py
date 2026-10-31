"""Google Gemini adapter (REST API, no vendor SDK).

Sends API keys via the ``x-goog-api-key`` header so keys never appear in
URLs (and therefore never in logged error messages).
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

logger = logging.getLogger("jarvis.providers.gemini")

API_VERSION = "v1beta"


class GeminiAdapter(ProviderAdapter):
    """Adapter for the Google Generative Language REST API."""

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
        return "gemini"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_generation=True,
            tool_calling=True,
            structured_output=True,
            image_input=True,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key
        return headers

    def test_connection(self) -> ConnectionTestResult:
        """Minimal safe check: GET the model list."""
        url = f"{self._base_url}/{API_VERSION}/models"
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
        models = payload.get("models")
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
        url = f"{self._base_url}/{API_VERSION}/models/{self._config.model}:generateContent"
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
        contents: list[dict[str, Any]] = []
        for message in request.messages:
            role = message.get("role", "user")
            text = message.get("content", "")
            if role == "system":
                system_parts.append(text)
                continue
            contents.append(
                {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
            )
        body: dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if generation_config:
            body["generationConfig"] = generation_config
        if request.tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        }
                        for tool in request.tools
                    ]
                }
            ]
        return body

    def _parse_response(self, payload: dict[str, Any]) -> ChatResponse:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderResponseError(self.name, "chat response contained no candidates")
        candidate = candidates[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        if not isinstance(parts, list):
            parts = []
        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                text_chunks.append(part["text"])
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                arguments = function_call.get("args", {})
                tool_calls.append(
                    ToolCall(
                        id=f"call_{index}",
                        name=str(function_call.get("name") or ""),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        usage_metadata = payload.get("usageMetadata") or {}
        usage = {
            key: int(value)
            for key, value in usage_metadata.items()
            if isinstance(value, int)
        }
        return ChatResponse(
            provider_name=self.name,
            model=str(self._config.model),
            content="".join(text_chunks),
            tool_calls=tuple(tool_calls),
            finish_reason=candidate.get("finishReason"),
            usage=usage,
        )
