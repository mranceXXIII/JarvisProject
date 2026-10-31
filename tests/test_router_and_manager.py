"""Tests for the provider manager and AI router (Phase 2)."""

from __future__ import annotations

import pytest

from core.ai_router import AIRouter, RoutingError
from core.config_loader import ProviderConfig, RoutingConfig, RouteEntry
from gateway.gateway_manager import GatewayManager
from providers.base_adapter import ProviderCapabilities
from providers.errors import ProviderError
from providers.provider_manager import ProviderManager
from security.credential_manager import CredentialManager
from tests.fakes import FakeKeyring  # type: ignore[attr-defined]


def _provider(name: str, ptype: str = "ollama", **overrides) -> ProviderConfig:
    data = {
        "name": name,
        "type": ptype,
        "enabled": True,
        "base_url": "http://localhost:11434" if ptype == "ollama" else "https://api.example.com/v1",
    }
    data.update(overrides)
    return ProviderConfig.model_validate(data)


def _manager(providers_secrets: dict[str, str] | None = None) -> ProviderManager:
    credentials = CredentialManager(backend=FakeKeyring())
    for ref, value in (providers_secrets or {}).items():
        credentials.set_secret(ref, value)
    return ProviderManager(credentials, GatewayManager())


@pytest.mark.unit
class TestProviderManager:
    def test_adapter_type_mapping(self) -> None:
        manager = _manager()
        for ptype in ("openai", "groq", "cerebras", "openrouter", "lm_studio"):
            adapter = manager.build_adapter(_provider("X", ptype))
            assert adapter.provider_type == "openai_compatible"
        assert manager.build_adapter(_provider("L", "ollama")).provider_type == "ollama"

    def test_credential_resolution_at_build_time(self) -> None:
        manager = _manager({"jarvis/test-key": "sk-abcdef123456"})
        provider = _provider("C", "openai", credential_ref="jarvis/test-key")
        adapter = manager.build_adapter(provider)
        assert adapter._api_key == "sk-abcdef123456"  # noqa: SLF001 - test probe

    def test_missing_credential_raises_typed_error(self) -> None:
        manager = _manager()
        provider = _provider("C", "openai", credential_ref="jarvis/missing")
        with pytest.raises(ProviderError, match="not available"):
            manager.build_adapter(provider)

    def test_unknown_type_rejected(self) -> None:
        manager = _manager()
        with pytest.raises(ProviderError, match="unsupported provider type"):
            manager.build_adapter(_provider("U", "weird_type"))

    def test_gateway_routed_endpoint_used(self) -> None:
        from core.config_loader import GatewayConfig

        credentials = CredentialManager(backend=FakeKeyring())
        gateway = GatewayConfig.model_validate(
            {"name": "gw", "url": "http://localhost:8080", "api_path": "/v1", "enabled": True}
        )
        manager = ProviderManager(credentials, GatewayManager((gateway,)))
        provider = _provider("Routed", "openai_compatible", gateway="gw")
        adapter = manager.build_adapter(provider)
        assert adapter.base_url == "http://localhost:8080/v1"

    def test_capabilities_of_known_type(self) -> None:
        manager = _manager()
        caps = manager.capabilities_of(_provider("L", "ollama"))
        assert caps.tool_calling is True


@pytest.mark.unit
class TestAIRouter:
    def _router(
        self,
        providers: list[ProviderConfig],
        routing: RoutingConfig | None = None,
    ) -> AIRouter:
        routing = routing or RoutingConfig(
            default=RouteEntry(provider="primary"),
            fallback_chain=["primary", "backup", "local"],
        )
        manager = _manager()
        is_local = {p.name: manager.is_local(p) for p in providers}
        return AIRouter(routing, {p.name: p for p in providers}, is_local, manager.capabilities_of)

    def test_primary_first_then_chain(self) -> None:
        providers = [
            _provider("primary", "openai"),
            _provider("backup", "groq"),
            _provider("local", "ollama"),
        ]
        plan = self._router(providers).build_plan()
        assert [p.name for p in plan.candidates] == ["primary", "backup", "local"]

    def test_disabled_providers_skipped(self) -> None:
        providers = [
            _provider("primary", "openai", enabled=False),
            _provider("local", "ollama"),
        ]
        plan = self._router(providers).build_plan()
        assert [p.name for p in plan.candidates] == ["local"]
        assert any("disabled" in reason for reason in plan.excluded_reasons)

    def test_tools_supported_by_all_default_types(self) -> None:
        providers = [_provider("primary", "openai"), _provider("local", "ollama")]
        plan = self._router(providers).build_plan(
            required=ProviderCapabilities(tool_calling=True)
        )
        assert [p.name for p in plan.candidates] == ["primary", "local"]

    def test_capability_filter_removes_unsupported(self) -> None:
        providers = [_provider("local", "ollama")]
        router = self._router(providers)
        with pytest.raises(RoutingError, match="missing capabilities"):
            router.build_plan(required=ProviderCapabilities(image_input=True))

    def test_sensitive_fallback_blocks_external(self) -> None:
        routing = RoutingConfig(
            default=RouteEntry(provider="primary"),
            fallback_chain=["primary", "backup"],
            sensitive_fallback_local_only=True,
        )
        providers = [_provider("primary", "openai"), _provider("backup", "groq")]
        plan = self._router(providers, routing).build_plan(sensitive=True)
        # The primary still serves the request; the external fallback is pruned.
        assert [p.name for p in plan.candidates] == ["primary"]
        assert any("sensitive" in reason for reason in plan.excluded_reasons)

    def test_sensitive_fallback_allows_local(self) -> None:
        routing = RoutingConfig(
            default=RouteEntry(provider="primary"),
            fallback_chain=["primary", "local"],
            sensitive_fallback_local_only=True,
        )
        providers = [_provider("primary", "openai"), _provider("local", "ollama")]
        plan = self._router(providers, routing).build_plan(sensitive=True)
        assert [p.name for p in plan.candidates] == ["primary", "local"]

    def test_cloud_only_mode_blocks_local(self) -> None:
        routing = RoutingConfig(
            settings=RoutingConfig().settings.model_copy(update={"mode": "cloud_only"}),
            default=RouteEntry(provider="local"),
            fallback_chain=["local", "primary"],
        )
        providers = [_provider("primary", "openai"), _provider("local", "ollama")]
        plan = self._router(providers, routing).build_plan()
        assert [p.name for p in plan.candidates] == ["primary"]

    def test_local_only_mode_blocks_cloud(self) -> None:
        routing = RoutingConfig(
            settings=RoutingConfig().settings.model_copy(update={"mode": "local_only"}),
            default=RouteEntry(provider="primary"),
            fallback_chain=["primary", "local"],
        )
        providers = [_provider("primary", "openai"), _provider("local", "ollama")]
        plan = self._router(providers, routing).build_plan()
        assert [p.name for p in plan.candidates] == ["local"]

    def test_unknown_route_provider_errors(self) -> None:
        routing = RoutingConfig(default=RouteEntry(provider="ghost"))
        with pytest.raises(RoutingError, match="not configured"):
            self._router([_provider("local", "ollama")], routing).build_plan()
