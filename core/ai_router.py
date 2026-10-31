"""Provider-independent AI router (Phase 2).

Resolves an ordered candidate list of providers for a request based on:
- the task category route from ``routing.yaml``,
- the routing mode (cloud_only / local_only / hybrid),
- required capabilities (candidates lacking them are skipped),
- sensitive-content protection: a fallback beyond the primary provider is
  only allowed to a LOCAL provider for sensitive requests
  (JARVIS_Project_Context.md 5.6 - never silently move sensitive content to
  a different external service).

The router never talks to the network; it only orders candidates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from core.config_loader import ProviderConfig, RoutingConfig
from providers.base_adapter import ProviderCapabilities

logger = logging.getLogger("jarvis.core.ai_router")

DEFAULT_CATEGORY = "general_conversation"

CAPABILITY_FIELDS = (
    "text_generation",
    "tool_calling",
    "structured_output",
    "image_input",
    "audio_input",
    "audio_output",
    "streaming",
)


class RoutingError(RuntimeError):
    """Raised when no provider can serve a request."""


@dataclass(frozen=True)
class RoutePlan:
    """The ordered provider candidates for one request."""

    category: str
    candidates: tuple[ProviderConfig, ...]
    excluded_reasons: tuple[str, ...]


class AIRouter:
    """Orders configured providers for each request."""

    def __init__(
        self,
        routing: RoutingConfig,
        providers: dict[str, ProviderConfig],
        is_local: dict[str, bool],
        capabilities_of: Callable[[ProviderConfig], ProviderCapabilities],
    ) -> None:
        self._routing = routing
        self._providers = providers
        self._is_local = is_local
        self._capabilities_of = capabilities_of

    @classmethod
    def from_config(
        cls,
        routing: RoutingConfig,
        provider_configs: tuple[ProviderConfig, ...],
        provider_manager,  # ProviderManager; typed loosely to avoid a cycle
    ) -> "AIRouter":
        providers = {p.name: p for p in provider_configs}
        is_local = {p.name: provider_manager.is_local(p) for p in provider_configs}
        return cls(routing, providers, is_local, provider_manager.capabilities_of)

    def build_plan(
        self,
        category: str = DEFAULT_CATEGORY,
        required: ProviderCapabilities | None = None,
        sensitive: bool = False,
    ) -> RoutePlan:
        """Build the ordered candidate list for a request."""
        required = required or ProviderCapabilities()
        primary_name = self._primary_name(category)
        chain_names = [
            name for name in self._routing.fallback_chain if name != primary_name
        ]
        ordered = [primary_name, *chain_names]

        candidates: list[ProviderConfig] = []
        excluded: list[str] = []
        seen: set[str] = set()
        for position, name in enumerate(ordered):
            if name in seen:
                continue
            seen.add(name)
            provider = self._providers.get(name)
            if provider is None:
                excluded.append(f"{name}: not configured")
                continue
            if not provider.enabled:
                excluded.append(f"{name}: disabled")
                continue
            if not self._mode_allows(name):
                excluded.append(
                    f"{name}: excluded by routing mode "
                    f"'{self._routing.settings.mode}'"
                )
                continue
            if position > 0 and sensitive:
                if self._routing.sensitive_fallback_local_only and not self._is_local.get(name, False):
                    excluded.append(
                        f"{name}: sensitive fallback to an external provider "
                        "is not allowed"
                    )
                    continue
            missing = self._missing_capabilities(provider, required)
            if missing:
                excluded.append(f"{name}: missing capabilities ({', '.join(missing)})")
                continue
            candidates.append(provider)

        if not candidates:
            detail = "; ".join(excluded) if excluded else "no providers configured"
            raise RoutingError(
                f"no provider can serve category '{category}': {detail}"
            )
        logger.info(
            "route plan for '%s': %s (excluded: %s)",
            category,
            [p.name for p in candidates],
            excluded or "none",
        )
        return RoutePlan(
            category=category,
            candidates=tuple(candidates),
            excluded_reasons=tuple(excluded),
        )

    def _primary_name(self, category: str) -> str:
        entry = self._routing.routes.get(category) or self._routing.default
        if entry is None:
            raise RoutingError(
                f"no route for category '{category}' and no default provider "
                "configured in routing.yaml"
            )
        return entry.provider

    def _mode_allows(self, name: str) -> bool:
        mode = self._routing.settings.mode
        if mode == "hybrid":
            return True
        local = self._is_local.get(name, False)
        if mode == "local_only":
            return local
        return not local  # cloud_only

    def _missing_capabilities(
        self, provider: ProviderConfig, required: ProviderCapabilities
    ) -> list[str]:
        declared = self._capabilities_of(provider)
        return [
            field_name
            for field_name in CAPABILITY_FIELDS
            if getattr(required, field_name)
            and not getattr(declared, field_name)
        ]


__all__ = ["AIRouter", "RoutePlan", "RoutingError"]
