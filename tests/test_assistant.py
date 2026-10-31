"""Tests for the assistant conversation flow (Phase 2)."""

from __future__ import annotations

import pytest

from core.ai_router import AIRouter
from core.assistant import JarvisAssistant
from core.config_loader import ProviderConfig, RouteEntry, RoutingConfig
from providers.base_adapter import ChatResponse, ToolCall
from tests.test_router_and_manager import _manager, _provider


class StubManager:
    """Stub ProviderManager that returns scripted chat results."""

    def __init__(self, results: dict[str, object]) -> None:
        self.results = results  # provider name -> ChatResponse or Exception
        self.calls: list[str] = []

    def is_local(self, provider: ProviderConfig) -> bool:
        return provider.type in ("ollama", "lm_studio")

    def capabilities_of(self, provider: ProviderConfig):
        from providers.provider_manager import _ADAPTER_CLASSES

        cls = _ADAPTER_CLASSES[provider.type]
        return cls.__new__(cls).capabilities

    def chat(self, provider: ProviderConfig, request):
        self.calls.append(provider.name)
        outcome = self.results[provider.name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(name: str, content: str = "ok", tool_calls=()) -> ChatResponse:
    return ChatResponse(
        provider_name=name, model="m", content=content, tool_calls=tool_calls
    )


def _assistant(providers: list[ProviderConfig], results: dict[str, object]) -> JarvisAssistant:
    routing = RoutingConfig(
        default=RouteEntry(provider=providers[0].name),
        fallback_chain=[p.name for p in providers],
    )
    stub = StubManager(results)
    router = AIRouter(
        routing,
        {p.name: p for p in providers},
        {p.name: stub.is_local(p) for p in providers},
        stub.capabilities_of,
    )
    return JarvisAssistant(stub, router)


@pytest.mark.unit
class TestAssistant:
    def test_successful_reply(self) -> None:
        providers = [_provider("primary", "openai")]
        assistant = _assistant(providers, {"primary": _response("primary", "Hello!")})
        reply = assistant.handle_text("hi")
        assert reply.success is True
        assert reply.text == "Hello!"
        assert reply.provider_name == "primary"
        assert reply.errors == []

    def test_fallback_on_provider_failure(self) -> None:
        from providers.errors import ProviderRateLimitError

        providers = [_provider("primary", "openai"), _provider("backup", "groq")]
        results = {
            "primary": ProviderRateLimitError("primary", "rate limited"),
            "backup": _response("backup", "from backup"),
        }
        reply = _assistant(providers, results).handle_text("hi")
        assert reply.success is True
        assert reply.provider_name == "backup"
        assert len(reply.errors) == 1

    def test_all_failures_reported_honestly(self) -> None:
        from providers.errors import ProviderNetworkError

        providers = [_provider("primary", "openai"), _provider("backup", "groq")]
        results = {
            "primary": ProviderNetworkError("primary", "unreachable"),
            "backup": ProviderNetworkError("backup", "unreachable"),
        }
        reply = _assistant(providers, results).handle_text("hi")
        assert reply.success is False
        assert reply.provider_name is None
        assert len(reply.errors) == 2

    def test_empty_text_rejected(self) -> None:
        providers = [_provider("primary", "openai")]
        reply = _assistant(providers, {}).handle_text("   ")
        assert reply.success is False

    def test_tool_calls_surfaced_not_executed(self) -> None:
        calls = (ToolCall(id="c1", name="open_app", arguments={"app": "calc"}),)
        providers = [_provider("primary", "openai")]
        assistant = _assistant(providers, {"primary": _response("primary", "", calls)})
        reply = assistant.handle_text("open calculator", tools=[])
        assert reply.success is True
        assert reply.needs_tool_execution is True
        assert reply.tool_calls[0].name == "open_app"

    def test_history_prepended(self) -> None:
        providers = [_provider("primary", "openai")]

        class RecordingManager(StubManager):
            def chat(self, provider, request):
                self.last_request = request
                return _response(provider.name, "ok")

        assistant = _assistant(providers, {})
        stub = RecordingManager({})
        routing = RoutingConfig(
            default=RouteEntry(provider="primary"), fallback_chain=["primary"]
        )
        router = AIRouter(
            routing,
            {p.name: p for p in providers},
            {p.name: False for p in providers},
            stub.capabilities_of,
        )
        from core.assistant import JarvisAssistant as JA

        ja = JA(stub, router)
        ja.handle_text("second", history=[{"role": "user", "content": "first"}])
        assert stub.last_request.messages[0]["content"] == "first"
        assert stub.last_request.messages[-1]["content"] == "second"
