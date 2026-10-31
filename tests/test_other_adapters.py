"""Tests for Ollama, Gemini, and Anthropic adapters (Phase 2)."""

from __future__ import annotations

import pytest

from core.config_loader import ProviderConfig
from providers.anthropic_adapter import AnthropicAdapter
from providers.base_adapter import ChatRequest
from providers.errors import ProviderAuthError, ProviderError
from providers.gemini_adapter import GeminiAdapter
from providers.ollama_adapter import OllamaAdapter
from tests.fakes import FakeResponse, FakeSession


@pytest.mark.unit
class TestOllamaAdapter:
    def _adapter(self, session: FakeSession) -> OllamaAdapter:
        config = ProviderConfig.model_validate(
            {
                "name": "Local Ollama",
                "type": "ollama",
                "base_url": "http://localhost:11434",
                "model": "llama3.1",
                "enabled": True,
            }
        )
        return OllamaAdapter(config, "http://localhost:11434", None, session)

    def test_connection_lists_models(self) -> None:
        session = FakeSession([FakeResponse(200, {"models": [{"name": "llama3.1"}]})])
        result = self._adapter(session).test_connection()
        assert result.success is True
        assert "llama3.1" in result.details["models"]

    def test_chat_native_format(self) -> None:
        payload = {
            "model": "llama3.1",
            "message": {"role": "assistant", "content": "hi there"},
            "done_reason": "stop",
            "eval_count": 12,
        }
        session = FakeSession([FakeResponse(200, payload)])
        response = self._adapter(session).chat(
            ChatRequest(messages=[{"role": "user", "content": "hello"}])
        )
        assert response.content == "hi there"
        assert response.usage["eval_count"] == 12
        body = session.requests[-1]["json"]
        assert body["stream"] is False
        assert body["model"] == "llama3.1"

    def test_tool_calls_native_format(self) -> None:
        payload = {
            "model": "llama3.1",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": {"app": "calc"}}}
                ],
            },
        }
        session = FakeSession([FakeResponse(200, payload)])
        response = self._adapter(session).chat(
            ChatRequest(messages=[{"role": "user", "content": "x"}])
        )
        assert response.tool_calls[0].arguments == {"app": "calc"}

    def test_is_local_type(self) -> None:
        from providers.provider_manager import LOCAL_PROVIDER_TYPES

        assert "ollama" in LOCAL_PROVIDER_TYPES


@pytest.mark.unit
class TestGeminiAdapter:
    def _adapter(self, session: FakeSession, api_key: str | None = "gkey") -> GeminiAdapter:
        config = ProviderConfig.model_validate(
            {
                "name": "Gemini",
                "type": "gemini",
                "model": "gemini-1.5-flash",
                "enabled": True,
            }
        )
        return GeminiAdapter(
            config, "https://generativelanguage.googleapis.com", api_key, session
        )

    def test_connection_uses_header_not_query_param(self) -> None:
        session = FakeSession([FakeResponse(200, {"models": []})])
        result = self._adapter(session).test_connection()
        assert result.success is True
        request = session.requests[0]
        assert "gkey" not in request["url"]
        assert request["headers"]["x-goog-api-key"] == "gkey"

    def test_missing_key_raises(self) -> None:
        adapter = self._adapter(FakeSession(), api_key=None)
        with pytest.raises(ProviderError, match="no API key"):
            adapter.chat(ChatRequest(messages=[{"role": "user", "content": "x"}]))

    def test_chat_maps_roles_and_system(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "candidates": [
                            {
                                "content": {"parts": [{"text": "answer"}]},
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {"totalTokenCount": 9},
                    },
                )
            ]
        )
        response = self._adapter(session).chat(
            ChatRequest(
                messages=[
                    {"role": "system", "content": "be brief"},
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                    {"role": "user", "content": "how are you"},
                ]
            )
        )
        assert response.content == "answer"
        assert response.usage["totalTokenCount"] == 9
        body = session.requests[-1]["json"]
        assert body["systemInstruction"]["parts"][0]["text"] == "be brief"
        assert body["contents"][0]["role"] == "user"
        assert body["contents"][1]["role"] == "model"

    def test_function_call_parsed(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "functionCall": {
                                                "name": "open_app",
                                                "args": {"app": "calc"},
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                )
            ]
        )
        response = self._adapter(session).chat(
            ChatRequest(messages=[{"role": "user", "content": "x"}])
        )
        assert response.tool_calls[0].name == "open_app"
        assert response.tool_calls[0].arguments == {"app": "calc"}


@pytest.mark.unit
class TestAnthropicAdapter:
    def _adapter(self, session: FakeSession) -> AnthropicAdapter:
        config = ProviderConfig.model_validate(
            {
                "name": "Claude",
                "type": "anthropic",
                "model": "claude-sonnet-4-5",
                "enabled": True,
            }
        )
        return AnthropicAdapter(config, "https://api.anthropic.com/v1", "akey", session)

    def test_connection_uses_models_endpoint(self) -> None:
        session = FakeSession([FakeResponse(200, {"data": [{"id": "m"}]})])
        result = self._adapter(session).test_connection()
        assert result.success is True
        assert session.requests[0]["headers"]["anthropic-version"] == "2023-06-01"

    def test_chat_separates_system_and_requires_max_tokens(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "model": "claude-sonnet-4-5",
                        "content": [{"type": "text", "text": "reply"}],
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 3, "output_tokens": 1},
                    },
                )
            ]
        )
        response = self._adapter(session).chat(
            ChatRequest(
                messages=[
                    {"role": "system", "content": "s"},
                    {"role": "user", "content": "u"},
                ]
            )
        )
        assert response.content == "reply"
        body = session.requests[-1]["json"]
        assert body["system"] == "s"
        assert body["max_tokens"] >= 1
        assert all(m["role"] != "system" for m in body["messages"])

    def test_tool_use_block_parsed(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "t1",
                                "name": "open_app",
                                "input": {"app": "calc"},
                            }
                        ],
                        "stop_reason": "tool_use",
                    },
                )
            ]
        )
        response = self._adapter(session).chat(
            ChatRequest(messages=[{"role": "user", "content": "x"}])
        )
        assert response.tool_calls[0].id == "t1"
        assert response.tool_calls[0].arguments == {"app": "calc"}

    def test_auth_failure_raises_typed_error(self) -> None:
        session = FakeSession([FakeResponse(401, {})])
        with pytest.raises(ProviderAuthError):
            self._adapter(session).chat(
                ChatRequest(messages=[{"role": "user", "content": "x"}])
            )
