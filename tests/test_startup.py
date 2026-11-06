"""Tests for Phase 12: startup manager (fake registry, no real registry)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.management_tools import register_startup_tools
from core.startup_manager import (
    RUN_VALUE_NAME,
    StartupError,
    StartupManager,
    _UnavailableApi,
)
from core.tool_registry import ToolRegistry


class FakeRegistryApi:
    """Dict-backed registry for tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set_value(self, name: str, command: str) -> None:
        self.values[name] = command

    def get_value(self, name: str) -> str | None:
        return self.values.get(name)

    def delete_value(self, name: str) -> None:
        self.values.pop(name, None)


@pytest.mark.unit
class TestStartupManager:
    def test_initially_disabled(self, tmp_path: Path) -> None:
        manager = StartupManager(tmp_path, registry_api=FakeRegistryApi())
        assert manager.available is True
        assert manager.is_enabled() is False

    def test_enable_sets_run_value(self, tmp_path: Path) -> None:
        api = FakeRegistryApi()
        manager = StartupManager(tmp_path, registry_api=api)
        result = manager.enable()
        assert "start at sign-in" in result
        command = api.values[RUN_VALUE_NAME]
        assert "main.py" in command
        assert command.startswith('"')

    def test_enable_prefers_pythonw(self, tmp_path: Path) -> None:
        venv_scripts = tmp_path / ".venv" / "Scripts"
        venv_scripts.mkdir(parents=True)
        (venv_scripts / "pythonw.exe").write_bytes(b"")
        manager = StartupManager(tmp_path, registry_api=FakeRegistryApi())
        manager.enable()
        assert "pythonw.exe" in manager.get_command()

    def test_disable_removes_value(self, tmp_path: Path) -> None:
        api = FakeRegistryApi()
        manager = StartupManager(tmp_path, registry_api=api)
        manager.enable()
        assert manager.is_enabled() is True
        manager.disable()
        assert manager.is_enabled() is False

    def test_disable_idempotent(self, tmp_path: Path) -> None:
        manager = StartupManager(tmp_path, registry_api=FakeRegistryApi())
        assert "no longer" in manager.disable()

    def test_unavailable_api_reports_honestly(self, tmp_path: Path) -> None:
        manager = StartupManager(tmp_path, registry_api=_UnavailableApi())
        assert manager.available is False
        with pytest.raises(StartupError, match="unavailable"):
            manager.enable()


@pytest.mark.unit
class TestStartupTools:
    def test_tools_registered_with_risks(self, tmp_path: Path) -> None:
        manager = StartupManager(tmp_path, registry_api=FakeRegistryApi())
        registry = ToolRegistry()
        register_startup_tools(registry, manager)
        risks = {t.name: t.risk for t in registry.list_tools()}
        assert risks == {
            "startup_status": "low",
            "startup_enable": "medium",
            "startup_disable": "medium",
        }

    def test_tools_roundtrip(self, tmp_path: Path) -> None:
        manager = StartupManager(tmp_path, registry_api=FakeRegistryApi())
        registry = ToolRegistry()
        register_startup_tools(registry, manager)
        enable = registry.execute("startup_enable", {})
        assert enable.success is True
        status = registry.execute("startup_status", {})
        assert "ENABLED" in status.output
        disable = registry.execute("startup_disable", {})
        assert disable.success is True

    def test_skipped_when_unavailable(self, tmp_path: Path) -> None:
        manager = StartupManager(tmp_path, registry_api=_UnavailableApi())
        registry = ToolRegistry()
        register_startup_tools(registry, manager)
        assert registry.list_tools() == ()
