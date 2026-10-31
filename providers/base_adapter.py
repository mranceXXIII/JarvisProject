"""Base adapter interface for AI providers (Phases 1-2).

Concrete adapters (OpenAI-compatible, Gemini, Anthropic, Ollama) implement
this contract. All request/response types are provider-neutral so the AI
router and assistant never see vendor-specific payloads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.config_loader import ProviderConfig


@dataclass(frozen=True)
class ProviderCapabilities:
    """Features a provider/model adapter declares support for.

    The planner must never request unsupported capabilities; instead of
    pretending a feature exists, callers check this registry first.
    """

    text_generation: bool = True
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    image_input: bool = False
    audio_input: bool = False
    audio_output: bool = False
    context_limit: int | None = None


@dataclass(frozen=True)
class ConnectionTestResult:
    """Outcome of a minimal, safe connection test."""

    success: bool
    message: str
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    """Provider-neutral tool/function definition."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatRequest:
    """Provider-neutral chat request."""

    messages: list[dict[str, str]]
    tools: list[ToolSpec] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    sensitive: bool = False


@dataclass(frozen=True)
class ChatResponse:
    """Provider-neutral chat response."""

    provider_name: str
    model: str
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class ProviderAdapter(ABC):
    """Abstract contract for provider adapters."""

    def __init__(self, config: ProviderConfig, base_url: str, api_key: str | None) -> None:
        self._config = config
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    @property
    def config(self) -> ProviderConfig:
        return self._config

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Identifier of the adapter type, e.g. ``openai_compatible``."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declared capabilities for this provider type."""

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult:
        """Perform a minimal safe request and report the result.

        Must never expose secret values in messages or details.
        """

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Execute a chat request.

        Raises ProviderError subclasses on failure; messages are safe to log.
        """

    def _require_capability(self, enabled: bool, feature: str) -> None:
        if not enabled:
            from providers.errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(
                self._config.name,
                f"capability '{feature}' is not supported by this provider",
            )
