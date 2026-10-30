"""Secure credential storage for JARVIS.

Wraps the platform keyring (Windows Credential Manager on the target
platform) behind a small interface so the rest of the application never
touches raw secret values except at the exact point of use. Configuration
files reference secrets by ``credential_ref`` only.

Every value stored or retrieved is registered with the global
:class:`~core.logging_setup.SecretRegistry` so it is masked in logs.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import keyring

from core.logging_setup import secret_registry

logger = logging.getLogger("jarvis.security.credentials")

DEFAULT_SERVICE_NAME = "JARVIS"


class CredentialError(RuntimeError):
    """Raised when a credential operation fails in the secure store."""


class KeyringBackend(Protocol):
    """Minimal protocol the credential manager needs from a backend."""

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def get_password(self, service: str, username: str) -> str | None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class CredentialManager:
    """Store, read, and delete secrets via the platform credential store."""

    def __init__(
        self,
        service_name: str = DEFAULT_SERVICE_NAME,
        backend: Any = None,
    ) -> None:
        self._service_name = service_name
        self._backend: KeyringBackend = backend if backend is not None else keyring

    @property
    def service_name(self) -> str:
        return self._service_name

    def set_secret(self, credential_ref: str, value: str) -> None:
        """Store *value* under *credential_ref* in the secure store."""
        if not credential_ref:
            raise CredentialError("credential_ref must not be empty")
        if not value:
            raise CredentialError("refusing to store an empty secret")
        try:
            self._backend.set_password(self._service_name, credential_ref, value)
        except Exception as exc:
            raise CredentialError(
                f"failed to store credential '{credential_ref}': {type(exc).__name__}"
            ) from exc
        secret_registry.register(value)
        logger.info("stored credential '%s' in secure store", credential_ref)

    def get_secret(self, credential_ref: str) -> str:
        """Return the secret for *credential_ref*.

        Raises:
            CredentialError: if the reference is unknown or the store fails.
        """
        if not credential_ref:
            raise CredentialError("credential_ref must not be empty")
        try:
            value = self._backend.get_password(self._service_name, credential_ref)
        except Exception as exc:
            raise CredentialError(
                f"failed to read credential '{credential_ref}': {type(exc).__name__}"
            ) from exc
        if value is None:
            raise CredentialError(f"unknown credential reference: '{credential_ref}'")
        secret_registry.register(value)
        return value

    def delete_secret(self, credential_ref: str) -> None:
        """Delete the secret for *credential_ref* if it exists."""
        try:
            self._backend.delete_password(self._service_name, credential_ref)
        except Exception as exc:
            raise CredentialError(
                f"failed to delete credential '{credential_ref}': {type(exc).__name__}"
            ) from exc
        logger.info("deleted credential '%s' from secure store", credential_ref)

    def has_secret(self, credential_ref: str) -> bool:
        """Return True when *credential_ref* resolves to a stored secret."""
        try:
            return self._backend.get_password(self._service_name, credential_ref) is not None
        except Exception:
            return False
