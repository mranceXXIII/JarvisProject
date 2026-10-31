"""Ollama adapter (local model runtime, native API).

Uses the native Ollama API (``/api/chat``, ``/api/tags``) at the user's
configured base URL. No authentication is used for local runtimes.
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

logger = logging.getLogger("jarvis.providers.ollama")


class OllamaAdapter(ProviderAdapter):
    """Adapter for local Ollama servers."""

    def __init__(
        self,
        config: ProviderConfig,
        base_url: str,
        api_key: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(config, base_url, None)  # local: never send credentials
        self._session = session if session is not None else requests.Session()

    @property
    def provider_type(self) -> str:
        return "ollama"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_generation=True,
            tool_calling=True,
            structured_output=True,
        )

    def test_connection(self) -> ConnectionTestResult:
        """Minimal safe check: GET /api/tags (local model list)."""
        try:
            response = self._session.get(
                self._base_url + "/api/tags",
                timeout=self._config.timeout_seconds,
            )
            payload = raise_for_response(self.name, response, "connection test")
        except ProviderError as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        except Exception as exc:
            mapped = map_transport_error(self.name, exc, "connection test")
            return ConnectionTestResult(success=False, message=str(mapped))
        models = payload.get("models")
        names = [m.get("name", "?") for m in models if isinstance(m, dict)] if isinstance(models, list) else []
        return ConnectionTestResult(
            success=True,
            message="Ollama server reachable",
            details={"models": ", ".join(names[:5]) or "<none installed>"},
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self._config.model:
            raise ProviderResponseError(self.name, "no model configured for this provider")
        if request.tools:
            self._require_capability(self.capabilities.tool_calling, "tool calling")

        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": request.messages,
            "stream": False,
        }
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
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if options:
            body["options"] = options

        path = self._config.endpoint_path or "/api/chat"
        url = self._base_url + (path if path.startswith("/") else "/" + path)
        try:
            response = self._session.post(
                url, json=body, timeout=self._config.timeout_seconds
            )
            payload = raise_for_response(self.name, response, "chat request")
        except ProviderError:
            raise
        except Exception as exc:
            raise map_transport_error(self.name, exc, "chat request") from exc
        return self._parse_response(payload)

    def _parse_response(self, payload: dict[str, Any]) -> ChatResponse:
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ProviderResponseError(self.name, "chat response contained no message")
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        usage: dict[str, int] = {}
        for key in ("prompt_eval_count", "eval_count"):
            if isinstance(payload.get(key), int):
                usage[key] = payload[key]
        return ChatResponse(
            provider_name=self.name,
            model=str(payload.get("model") or self._config.model),
            content=str(message.get("content") or ""),
            tool_calls=tool_calls,
            finish_reason=payload.get("done_reason"),
            usage=usage,
        )

    def _parse_tool_calls(self, raw: Any) -> tuple[ToolCall, ...]:
        if not isinstance(raw, list):
            return ()
        parsed: list[ToolCall] = []
        for index, item in enumerate(raw):
            function = item.get("function") if isinstance(item, dict) else None
            if not isinstance(function, dict):
                continue
            arguments = function.get("arguments", {})
            parsed.append(
                ToolCall(
                    id=f"call_{index}",
                    name=str(function.get("name") or ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        return tuple(parsed)
