"""Provider manager: builds adapters and executes provider operations.

Responsibilities (Phase 2):
- Map provider types to adapter classes (custom OpenAI-compatible endpoints
  supported through user configuration).
- Resolve the effective base URL through the gateway manager (gateway
  routing) and the API key through the secure credential manager, at request
  time, never persisted in logs.
- Provide test_connection() and chat() entry points with typed errors.
"""

from __future__ import annotations

import logging

from core.config_loader import GatewayConfig, ProviderConfig
from gateway.gateway_manager import GatewayManager
from providers.anthropic_adapter import AnthropicAdapter
from providers.base_adapter import (
    ChatRequest,
    ChatResponse,
    ConnectionTestResult,
    ProviderAdapter,
    ProviderCapabilities,
)
from providers.errors import ProviderError
from providers.gemini_adapter import GeminiAdapter
from providers.ollama_adapter import OllamaAdapter
from providers.openai_compatible import OpenAICompatibleAdapter
from security.credential_manager import CredentialManager

logger = logging.getLogger("jarvis.providers.manager")

# Known provider types and their default base URLs. Users may override the
# base URL per provider; these defaults reflect current public endpoints and
# should be re-verified against provider documentation when in doubt.
PROVIDER_TYPE_DEFAULTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openai_compatible": "",  # base_url required from configuration
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "lm_studio": "http://localhost:1234/v1",
    "ollama": "http://localhost:11434",
    "gemini": "https://generativelanguage.googleapis.com",
    "anthropic": "https://api.anthropic.com/v1",
}

LOCAL_PROVIDER_TYPES = frozenset({"ollama", "lm_studio"})

_ADAPTER_CLASSES: dict[str, type[ProviderAdapter]] = {
    "openai": OpenAICompatibleAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
    "groq": OpenAICompatibleAdapter,
    "cerebras": OpenAICompatibleAdapter,
    "openrouter": OpenAICompatibleAdapter,
    "lm_studio": OpenAICompatibleAdapter,
    "ollama": OllamaAdapter,
    "gemini": GeminiAdapter,
    "anthropic": AnthropicAdapter,
}


class ProviderManager:
    """Builds adapters from configuration and executes chat/test calls."""

    def __init__(
        self,
        credential_manager: CredentialManager,
        gateway_manager: GatewayManager,
    ) -> None:
        self._credentials = credential_manager
        self._gateways = gateway_manager

    def is_local(self, provider: ProviderConfig) -> bool:
        return provider.type in LOCAL_PROVIDER_TYPES

    def build_adapter(self, provider: ProviderConfig) -> ProviderAdapter:
        """Construct the adapter for *provider*, resolving URL and key.

        Raises:
            ProviderError: for unknown types or missing configuration.
        """
        adapter_class = _ADAPTER_CLASSES.get(provider.type)
        if adapter_class is None:
            raise ProviderError(
                provider.name, f"unsupported provider type '{provider.type}'"
            )
        base_url = self._resolve_base_url(provider)
        api_key = self._resolve_api_key(provider)
        return adapter_class(provider, base_url, api_key)

    def _resolve_base_url(self, provider: ProviderConfig) -> str:
        endpoint = self._gateways.resolve_endpoint(provider)
        return endpoint.base_url

    def _resolve_api_key(self, provider: ProviderConfig) -> str | None:
        if not provider.credential_ref:
            return None
        try:
            return self._credentials.get_secret(provider.credential_ref)
        except Exception as exc:
            raise ProviderError(
                provider.name,
                f"credential '{provider.credential_ref}' is not available "
                f"({type(exc).__name__})",
            ) from exc

    def test_connection(self, provider: ProviderConfig) -> ConnectionTestResult:
        """Run the adapter's minimal safe connection test."""
        try:
            adapter = self.build_adapter(provider)
            return adapter.test_connection()
        except ProviderError as exc:
            return ConnectionTestResult(success=False, message=str(exc))

    def chat(self, provider: ProviderConfig, request: ChatRequest) -> ChatResponse:
        """Execute a chat request against *provider*.

        Raises:
            ProviderError subclass: on auth, rate limit, timeout, network,
                server, or capability failures. Messages are safe to log.
        """
        adapter = self.build_adapter(provider)
        return adapter.chat(request)

    def capabilities_of(self, provider: ProviderConfig) -> ProviderCapabilities:
        """Declared capabilities of the provider's adapter type."""
        adapter_class = _ADAPTER_CLASSES.get(provider.type)
        if adapter_class is None:
            raise ProviderError(
                provider.name, f"unsupported provider type '{provider.type}'"
            )
        # Capabilities are type-level, so inspect without constructing.
        probe = adapter_class.__new__(adapter_class)  # noqa: SLF001 - safe probe
        return probe.capabilities


__all__ = [
    "LOCAL_PROVIDER_TYPES",
    "PROVIDER_TYPE_DEFAULTS",
    "GatewayConfig",
    "ProviderManager",
]
