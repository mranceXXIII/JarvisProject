"""Tests for the OpenAI-compatible adapter (Phase 2)."""

from __future__ import annotations

import pytest

from core.config_loader import ProviderConfig
from providers.base_adapter import ChatRequest, ToolSpec
from providers.errors import (
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderServerError,
)
from providers.openai_compatible import OpenAICompatibleAdapter
from tests.fakes import FakeResponse, FakeSession


def _config(**overrides) -> ProviderConfig:
    data = {
        "name": "TestProvider",
        "type": "openai_compatible",
        "base_url": "https://api.example.com/v1",
        "model": "test-model",
        "enabled": True,
    }
    data.update(overrides)
    return ProviderConfig.model_validate(data)


@pytest.mark.unit
class TestConnectionTesting:
    def test_success_reports_model_count(self) -> None:
        session = FakeSession([FakeResponse(200, {"data": [{"id": "m1"}, {"id": "m2"}]})])
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", "k", session)
        result = adapter.test_connection()
        assert result.success is True
        assert result.details["models_listed"] == "2"

    def test_auth_failure_reported(self) -> None:
        session = FakeSession([FakeResponse(401, {"error": {"message": "bad key"}})])
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", "bad", session)
        result = adapter.test_connection()
        assert result.success is False
        assert "authentication failed" in result.message

    def test_api_key_never_in_url(self) -> None:
        session = FakeSession([FakeResponse(200, {"data": []})])
        adapter = OpenAICompatibleAdapter(
            _config(), "https://api.example.com/v1", "sk-secret-key-1", session
        )
        adapter.test_connection()
        assert "sk-secret-key-1" not in session.requests[0]["url"]
        assert session.requests[0]["headers"]["Authorization"] == "Bearer sk-secret-key-1"


@pytest.mark.unit
class TestChat:
    def test_successful_chat_response(self) -> None:
        payload = {
            "model": "test-model",
            "choices": [
                {"message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
        session = FakeSession([FakeResponse(200, payload)])
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", None, session)
        response = adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}]))
        assert response.content == "Hello!"
        assert response.provider_name == "TestProvider"
        assert response.usage["prompt_tokens"] == 5
        assert response.tool_calls == ()

    def test_tool_calls_parsed_from_arguments_json(self) -> None:
        payload = {
            "model": "test-model",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "open_app",
                                    "arguments": '{"app": "notepad"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        session = FakeSession([FakeResponse(200, payload)])
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", None, session)
        response = adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}]))
        assert response.tool_calls[0].name == "open_app"
        assert response.tool_calls[0].arguments == {"app": "notepad"}
        assert response.finish_reason == "tool_calls"

    def test_tools_sent_in_openai_format(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    {"model": "m", "choices": [{"message": {"content": "ok"}}]},
                )
            ]
        )
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", None, session)
        tools = [ToolSpec(name="get_time", description="time", parameters={"type": "object"})]
        adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}], tools=tools))
        assert session.requests[0]["json"]["tools"][0]["function"]["name"] == "get_time"

    def test_rate_limit_mapped(self) -> None:
        session = FakeSession([FakeResponse(429, {})])
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", None, session)
        with pytest.raises(ProviderRateLimitError):
            adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}]))

    def test_server_error_mapped(self) -> None:
        session = FakeSession([FakeResponse(503, {})])
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", None, session)
        with pytest.raises(ProviderServerError):
            adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}]))

    def test_malformed_payload_raises_response_error(self) -> None:
        session = FakeSession([FakeResponse(200, {"nope": True})])
        adapter = OpenAICompatibleAdapter(_config(), "https://api.example.com/v1", None, session)
        with pytest.raises(ProviderResponseError):
            adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}]))

    def test_missing_model_raises(self) -> None:
        adapter = OpenAICompatibleAdapter(
            _config(model=None), "https://api.example.com/v1", None, FakeSession()
        )
        with pytest.raises(ProviderResponseError, match="no model configured"):
            adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}]))

    def test_endpoint_path_respected(self) -> None:
        session = FakeSession(
            [FakeResponse(200, {"model": "m", "choices": [{"message": {"content": "x"}}]})]
        )
        adapter = OpenAICompatibleAdapter(
            _config(endpoint_path="/v2/chat"), "https://api.example.com", None, session
        )
        adapter.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}]))
        assert session.requests[0]["url"].endswith("/v2/chat")
