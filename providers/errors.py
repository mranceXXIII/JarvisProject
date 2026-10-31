"""Provider error hierarchy.

Errors never carry secret values; messages are safe for logs and UI.
"""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for all provider/AI-layer failures."""

    def __init__(self, provider_name: str, message: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"[{provider_name}] {message}")


class ProviderAuthError(ProviderError):
    """Authentication failed (e.g. HTTP 401/403) or credential missing."""


class ProviderRateLimitError(ProviderError):
    """Provider quota or rate limit hit (HTTP 429)."""


class ProviderTimeoutError(ProviderError):
    """The request timed out."""


class ProviderNetworkError(ProviderError):
    """Network-level failure reaching the provider or gateway."""


class ProviderServerError(ProviderError):
    """Provider returned a server-side error (HTTP 5xx)."""


class ProviderResponseError(ProviderError):
    """Provider responded with an unusable/unexpected payload."""


class UnsupportedCapabilityError(ProviderError):
    """Requested capability is not declared by the provider adapter."""


class SensitiveFallbackBlocked(ProviderError):
    """Fallback would disclose sensitive content to another external provider."""
