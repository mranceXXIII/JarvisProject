"""Base adapter interface for AI providers (Phase 1 foundation).

Concrete adapters (OpenAI-compatible, Gemini, Anthropic, Ollama, ...) are
Phase 2 work. This module defines the contract every adapter must satisfy so
the registry, gateway manager, and future dashboard can be built against a
stable interface now.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

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


class ProviderAdapter(ABC):
    """Abstract contract for provider adapters."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    @property
    def config(self) -> ProviderConfig:
        return self._config

    @property
    def name(self) -> str:
        return self._config.name

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

        Must never expose secret values in messages or details. Phase 2
        implements real network checks per provider.
        """
