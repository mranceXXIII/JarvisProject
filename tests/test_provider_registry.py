"""Tests for the provider registry and gateway manager (Phase 1)."""

from __future__ import annotations

import pytest

from core.config_loader import GatewayConfig, ProviderConfig
from gateway.gateway_manager import GatewayError, GatewayManager
from providers.provider_registry import ProviderRegistry, ProviderRegistryError


def _provider(name: str = "Local", enabled: bool = True, gateway: str | None = None) -> ProviderConfig:
    return ProviderConfig.model_validate(
        {
            "name": name,
            "type": "ollama",
            "base_url": "http://localhost:11434",
            "enabled": enabled,
            "gateway": gateway,
        }
    )


@pytest.mark.unit
class TestProviderRegistry:
    def test_list_and_get(self) -> None:
        registry = ProviderRegistry(providers=(_provider(),))
        assert [p.name for p in registry.list_providers()] == ["Local"]
        assert registry.get("Local").type == "ollama"

    def test_unknown_provider_raises(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(ProviderRegistryError, match="unknown provider"):
            registry.get("Nope")

    def test_activation_requires_validation(self) -> None:
        registry = ProviderRegistry(providers=(_provider(),))
        with pytest.raises(ProviderRegistryError, match="connection test"):
            registry.activate("Local")

    def test_activation_requires_enabled(self) -> None:
        registry = ProviderRegistry(providers=(_provider(enabled=False),))
        registry.mark_validated("Local")
        with pytest.raises(ProviderRegistryError, match="disabled"):
            registry.activate("Local")

    def test_successful_activation_flow(self) -> None:
        registry = ProviderRegistry(providers=(_provider(),))
        registry.mark_validated("Local")
        registry.activate("Local")
        assert registry.get("Local").active is True
        registry.deactivate("Local")
        assert registry.get("Local").active is False

    def test_build_adapter_without_factory_raises(self) -> None:
        registry = ProviderRegistry(providers=(_provider(),))
        with pytest.raises(ProviderRegistryError, match="Phase 2"):
            registry.build_adapter("Local")

    def test_credential_ref_resolvable_without_secret(self) -> None:
        registry = ProviderRegistry(providers=(_provider(),))
        assert registry.credential_ref_is_resolvable("Local") is True


@pytest.mark.unit
class TestGatewayManager:
    def test_direct_endpoint_when_no_gateway(self) -> None:
        manager = GatewayManager()
        endpoint = manager.resolve_endpoint(_provider())
        assert endpoint.via_gateway is None
        assert endpoint.base_url == "http://localhost:11434"

    def test_endpoint_through_enabled_gateway(self) -> None:
        gateway = GatewayConfig.model_validate(
            {"name": "gw", "url": "http://localhost:8080", "api_path": "/v1", "enabled": True}
        )
        manager = GatewayManager((gateway,))
        endpoint = manager.resolve_endpoint(_provider(gateway="gw"))
        assert endpoint.via_gateway == "gw"
        assert endpoint.base_url == "http://localhost:8080/v1"

    def test_disabled_gateway_falls_back_to_direct(self) -> None:
        gateway = GatewayConfig.model_validate(
            {"name": "gw", "url": "http://localhost:8080", "enabled": False}
        )
        manager = GatewayManager((gateway,))
        endpoint = manager.resolve_endpoint(_provider(gateway="gw"))
        assert endpoint.via_gateway is None

    def test_missing_base_url_raises(self) -> None:
        manager = GatewayManager()
        orphan = ProviderConfig.model_validate({"name": "orphan", "type": "custom"})
        with pytest.raises(GatewayError, match="neither a usable gateway"):
            manager.resolve_endpoint(orphan)

    def test_unknown_gateway_raises(self) -> None:
        manager = GatewayManager()
        with pytest.raises(GatewayError, match="unknown gateway"):
            manager.get("missing")

    def test_duplicate_gateway_names_rejected(self) -> None:
        gw = GatewayConfig.model_validate({"name": "dup", "url": "http://x"})
        with pytest.raises(GatewayError, match="duplicate"):
            GatewayManager((gw, gw))
