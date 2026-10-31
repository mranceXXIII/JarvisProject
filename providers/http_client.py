"""Shared HTTP plumbing for provider adapters.

Maps transport/HTTP failures to the typed ProviderError hierarchy and keeps
secret values out of error messages. Adapters inject their own
``requests.Session`` so tests can substitute fake transports.
"""

from __future__ import annotations

from typing import Any

import requests

from providers.errors import (
    ProviderAuthError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTimeoutError,
)


def raise_for_response(
    provider_name: str,
    response: requests.Response,
    context: str,
) -> dict[str, Any]:
    """Validate an HTTP response and return its parsed JSON payload.

    Raises:
        ProviderError subclass: mapped from the HTTP status/transport error.
    """
    if response.status_code in (401, 403):
        raise ProviderAuthError(
            provider_name, f"{context}: authentication failed (HTTP {response.status_code})"
        )
    if response.status_code == 429:
        raise ProviderRateLimitError(
            provider_name, f"{context}: rate limit or quota exceeded (HTTP 429)"
        )
    if response.status_code >= 500:
        raise ProviderServerError(
            provider_name, f"{context}: provider server error (HTTP {response.status_code})"
        )
    if response.status_code >= 400:
        detail = _safe_detail(response)
        raise ProviderResponseError(
            provider_name,
            f"{context}: request rejected (HTTP {response.status_code}){detail}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderResponseError(
            provider_name, f"{context}: response was not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderResponseError(
            provider_name, f"{context}: unexpected response structure"
        )
    return payload


def _safe_detail(response: requests.Response) -> str:
    """Extract a short, secret-free hint from an error body if possible."""
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return f": {error['message'][:200]}"
        if isinstance(error, str):
            return f": {error[:200]}"
    return ""


def map_transport_error(provider_name: str, exc: Exception, context: str) -> ProviderError:
    """Translate a requests transport exception into a ProviderError."""
    if isinstance(exc, requests.Timeout):
        return ProviderTimeoutError(provider_name, f"{context}: request timed out")
    if isinstance(exc, requests.ConnectionError):
        return ProviderNetworkError(provider_name, f"{context}: could not reach the endpoint")
    if isinstance(exc, requests.RequestException):
        return ProviderNetworkError(
            provider_name, f"{context}: request failed ({type(exc).__name__})"
        )
    return ProviderNetworkError(
        provider_name, f"{context}: unexpected transport error ({type(exc).__name__})"
    )


__all__ = ["map_transport_error", "raise_for_response"]
