"""Tests for the secure credential manager (uses an in-memory fake backend)."""

from __future__ import annotations

import pytest

from security.credential_manager import CredentialError, CredentialManager


class FakeKeyring:
    """In-memory keyring backend for tests - no real OS credential store."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise KeyError("not found")
        del self._store[(service, username)]


class FailingKeyring(FakeKeyring):
    """Backend that always fails, simulating a locked or missing store."""

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("backend unavailable")


@pytest.mark.unit
class TestCredentialManager:
    def test_set_and_get_secret(self) -> None:
        manager = CredentialManager(backend=FakeKeyring())
        manager.set_secret("jarvis/test-key", "value-1234567890")
        assert manager.get_secret("jarvis/test-key") == "value-1234567890"

    def test_has_secret_true_and_false(self) -> None:
        manager = CredentialManager(backend=FakeKeyring())
        manager.set_secret("jarvis/exists", "value-1234567890")
        assert manager.has_secret("jarvis/exists") is True
        assert manager.has_secret("jarvis/missing") is False

    def test_unknown_reference_raises(self) -> None:
        manager = CredentialManager(backend=FakeKeyring())
        with pytest.raises(CredentialError, match="unknown credential reference"):
            manager.get_secret("jarvis/nope")

    def test_delete_secret(self) -> None:
        manager = CredentialManager(backend=FakeKeyring())
        manager.set_secret("jarvis/doomed", "value-1234567890")
        manager.delete_secret("jarvis/doomed")
        assert manager.has_secret("jarvis/doomed") is False

    def test_empty_ref_and_value_rejected(self) -> None:
        manager = CredentialManager(backend=FakeKeyring())
        with pytest.raises(CredentialError, match="credential_ref"):
            manager.set_secret("", "value-1234567890")
        with pytest.raises(CredentialError, match="empty secret"):
            manager.set_secret("jarvis/x", "")

    def test_backend_failure_raises_credential_error(self) -> None:
        manager = CredentialManager(backend=FailingKeyring())
        with pytest.raises(CredentialError, match="failed to store"):
            manager.set_secret("jarvis/x", "value-1234567890")

    def test_service_name_isolated(self) -> None:
        backend = FakeKeyring()
        jarvis = CredentialManager(service_name="JARVIS", backend=backend)
        other = CredentialManager(service_name="Other", backend=backend)
        jarvis.set_secret("shared-ref", "value-1234567890")
        assert other.has_secret("shared-ref") is False
