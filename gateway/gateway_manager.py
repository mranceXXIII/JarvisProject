"""Gateway manager: resolves provider endpoints through optional gateways.

Phase 1 scope:
- Load validated gateway definitions from configuration.
- Resolve the effective base URL for a provider: through its associated,
  enabled gateway when one is configured, otherwise the provider's own
  base_url (direct connection).

Network-level connection testing is Phase 2 work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.config_loader import GatewayConfig, ProviderConfig

logger = logging.getLogger("jarvis.gateway.manager")


class GatewayError(RuntimeError):
    """Raised for gateway configuration problems."""


@dataclass(frozen=True)
class ResolvedEndpoint:
    """The effective endpoint a provider should use."""

    provider_name: str
    base_url: str
    via_gateway: str | None
    timeout_seconds: int


class GatewayManager:
    """Manages gateway definitions and provider endpoint resolution."""

    def __init__(self, gateways: tuple[GatewayConfig, ...] = ()) -> None:
        self._gateways: dict[str, GatewayConfig] = {}
        for gateway in gateways:
            if gateway.name in self._gateways:
                raise GatewayError(
                    f"duplicate gateway name in configuration: '{gateway.name}'"
                )
            self._gateways[gateway.name] = gateway

    def list_gateways(self) -> tuple[GatewayConfig, ...]:
        """All configured gateways, in configuration order."""
        return tuple(self._gateways.values())

    def get(self, name: str) -> GatewayConfig:
        """Return the gateway config for *name*."""
        try:
            return self._gateways[name]
        except KeyError as exc:
            raise GatewayError(f"unknown gateway: '{name}'") from exc

    def resolve_endpoint(self, provider: ProviderConfig) -> ResolvedEndpoint:
        """Return the effective endpoint for *provider*.

        Prefers the provider's associated gateway when that gateway exists
        and is enabled; otherwise uses the provider's own ``base_url``.
        """
        if provider.gateway:
            gateway = self.get(provider.gateway)
            if gateway.enabled:
                base_url = gateway.url.rstrip("/") + "/" + gateway.api_path.lstrip("/")
                return ResolvedEndpoint(
                    provider_name=provider.name,
                    base_url=base_url,
                    via_gateway=gateway.name,
                    timeout_seconds=gateway.timeout_seconds,
                )
            logger.warning(
                "provider '%s' references gateway '%s' which is disabled; "
                "falling back to direct connection",
                provider.name,
                gateway.name,
            )
        if not provider.base_url:
            raise GatewayError(
                f"provider '{provider.name}' has neither a usable gateway "
                "nor a base_url configured"
            )
        return ResolvedEndpoint(
            provider_name=provider.name,
            base_url=provider.base_url,
            via_gateway=None,
            timeout_seconds=provider.timeout_seconds,
        )


__all__ = ["GatewayError", "GatewayManager", "ResolvedEndpoint"]
