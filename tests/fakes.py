"""Shared test fakes for provider/HTTP tests (no real network calls)."""

from __future__ import annotations

from typing import Any


class FakeKeyring:
    """In-memory keyring backend for tests - no real OS credential store."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise KeyError("not found")
        del self._store[(service, username)]


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int = 200, payload: Any | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> Any:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


class FakeSession:
    """Records requests and returns scripted responses."""

    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": "GET", "url": url, **kwargs})
        return self._next()

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": "POST", "url": url, **kwargs})
        return self._next()

    def _next(self) -> FakeResponse:
        if not self.responses:
            raise AssertionError("no scripted response left")
        return self.responses.pop(0)
