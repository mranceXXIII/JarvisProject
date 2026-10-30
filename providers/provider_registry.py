"""Provider registry: validates and manages configured providers.

Phase 1 scope:
- Load validated provider definitions from configuration.
- Verify credential references resolve in the secure credential store.
- Map provider types to adapter classes (adapters themselves are Phase 2).

A provider is *active* only when it is enabled AND its configuration has been
validated (connection tests arrive in Phase 2). The registry refuses to
activate a provider that has not passed validation.
"""

from __future__ import annotations

import logging
from typing import Callable

from core.config_loader import ProviderConfig
from providers.base_adapter import ConnectionTestResult, ProviderAdapter
from security.credential_manager import CredentialManager

logger = logging.getLogger("jarvis.providers.registry")

# Adapter factory type: receives the validated config, returns an adapter.
AdapterFactory = Callable[[ProviderConfig], ProviderAdapter]


class ProviderRegistryError(RuntimeError):
    """Raised for provider registry usage errors."""


class ProviderRegistry:
    """Holds validated provider configs and their adapter factories."""

    def __init__(
        self,
        providers: tuple[ProviderConfig, ...] = (),
        credential_manager: CredentialManager | None = None,
    ) -> None:
        self._credential_manager = credential_manager
        self._factories: dict[str, AdapterFactory] = {}
        self._validated: set[str] = set()
        self._providers: dict[str, ProviderConfig] = {}
        for provider in providers:
            self._add(provider)

    def _add(self, provider: ProviderConfig) -> None:
        if provider.name in self._providers:
            raise ProviderRegistryError(
                f"duplicate provider name in configuration: '{provider.name}'"
            )
        self._providers[provider.name] = provider

    def register_adapter_factory(self, provider_type: str, factory: AdapterFactory) -> None:
        """Register an adapter factory for a provider type (Phase 2 adapters)."""
        self._factories[provider_type] = factory

    def list_providers(self) -> tuple[ProviderConfig, ...]:
        """All configured providers, in configuration order."""
        return tuple(self._providers.values())

    def get(self, name: str) -> ProviderConfig:
        """Return the provider config for *name*."""
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderRegistryError(f"unknown provider: '{name}'") from exc

    def credential_ref_is_resolvable(self, provider_name: str) -> bool:
        """True when the provider needs no secret or its ref exists in the store."""
        provider = self.get(provider_name)
        if provider.credential_ref is None:
            return True
        if self._credential_manager is None:
            return False
        return self._credential_manager.has_secret(provider.credential_ref)

    def mark_validated(self, provider_name: str) -> None:
        """Record that *provider_name* passed validation (e.g. a test connection)."""
        self.get(provider_name)  # raises for unknown names
        self._validated.add(provider_name)
        logger.info("provider '%s' marked validated", provider_name)

    def activate(self, provider_name: str) -> None:
        """Activate a provider after successful validation.

        Raises:
            ProviderRegistryError: if the provider is unknown, disabled, or
                has not been validated yet.
        """
        provider = self.get(provider_name)
        if not provider.enabled:
            raise ProviderRegistryError(
                f"provider '{provider_name}' is disabled and cannot be activated"
            )
        if provider_name not in self._validated:
            raise ProviderRegistryError(
                f"provider '{provider_name}' cannot be activated before a "
                "successful connection test (Phase 2) or explicit user override"
            )
        self._providers[provider_name] = provider.model_copy(update={"active": True})
        logger.info("provider '%s' activated", provider_name)

    def deactivate(self, provider_name: str) -> None:
        """Deactivate a provider."""
        provider = self.get(provider_name)
        self._providers[provider_name] = provider.model_copy(update={"active": False})

    def build_adapter(self, provider_name: str) -> ProviderAdapter:
        """Build the adapter instance for *provider_name*.

        Raises:
            ProviderRegistryError: if no adapter factory exists for the
                provider type (real adapters arrive in Phase 2).
        """
        provider = self.get(provider_name)
        factory = self._factories.get(provider.type)
        if factory is None:
            raise ProviderRegistryError(
                f"no adapter registered for provider type '{provider.type}' "
                "(adapters are implemented in Phase 2)"
            )
        return factory(provider)


__all__ = [
    "AdapterFactory",
    "ConnectionTestResult",
    "ProviderAdapter",
    "ProviderRegistry",
    "ProviderRegistryError",
]
