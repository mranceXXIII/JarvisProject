"""Tests for built-in tools (Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.app_launcher import AppLauncher
from core.builtin_tools import register_builtin_tools
from core.config_loader import ApplicationConfig
from core.tool_registry import ToolRegistry
from memory.conversation_store import ConversationStore
from memory.database import MemoryDatabase


class FakePopen:
    pid = 1234

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        return self


def _make_populated(tmp_path: Path):
    app_dir = tmp_path / "apps"
    app_dir.mkdir()
    (app_dir / "tool.exe").write_bytes(b"MZ")
    fake = FakePopen()
    launcher = AppLauncher(
        (
            ApplicationConfig.model_validate(
                {"name": "tool", "directory": str(app_dir), "executable": "tool.exe"}
            ),
        ),
        popen=fake,
    )
    store = ConversationStore(MemoryDatabase(tmp_path / "mem.db"), use_fts=False)
    conv = store.create_conversation("History")
    store.add_message(conv, "user", "remember the blue key")
    return launcher, store, fake


@pytest.fixture
def populated(tmp_path: Path):
    return _make_populated(tmp_path)


@pytest.mark.unit
class TestBuiltinTools:
    def test_all_four_tools_registered(self, populated) -> None:
        launcher, store, _ = populated
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        names = {t.name for t in registry.list_tools()}
        assert names == {
            "open_application",
            "search_memory",
            "list_applications",
            "get_current_time",
        }
        assert all(t.risk == "low" for t in registry.list_tools())

    def test_open_application_executes_launcher(self, populated) -> None:
        launcher, store, fake = populated
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        result = registry.execute("open_application", {"app": "tool"})
        assert result.success is True
        assert fake.calls

    def test_open_application_missing_exe_fails(self, tmp_path: Path) -> None:
        launcher = AppLauncher(
            (
                ApplicationConfig.model_validate(
                    {
                        "name": "ghost",
                        "directory": str(tmp_path),
                        "executable": "ghost.exe",
                    }
                ),
            ),
            popen=FakePopen(),
        )
        store = ConversationStore(MemoryDatabase(tmp_path / "m.db"), use_fts=False)
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        result = registry.execute("open_application", {"app": "ghost"})
        assert result.success is False
        assert "not found" in result.output

    def test_search_memory_returns_matches(self, populated) -> None:
        launcher, store, _ = populated
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        result = registry.execute("search_memory", {"query": "blue key"})
        assert result.success is True
        assert "blue key" in result.output

    def test_search_memory_no_match(self, populated) -> None:
        launcher, store, _ = populated
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        result = registry.execute("search_memory", {"query": "zebra-xyz"})
        assert result.success is True
        assert "No matching" in result.output

    def test_list_applications(self, populated) -> None:
        launcher, store, _ = populated
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        result = registry.execute("list_applications", {})
        assert result.success is True
        assert "tool" in result.output

    def test_get_current_time(self, populated) -> None:
        launcher, store, _ = populated
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        result = registry.execute("get_current_time", {})
        assert result.success is True
        assert len(result.output) > 8

    def test_specs_usable_for_providers(self, populated) -> None:
        launcher, store, _ = populated
        registry = ToolRegistry()
        register_builtin_tools(registry, launcher, store)
        specs = registry.to_tool_specs()
        open_spec = next(s for s in specs if s.name == "open_application")
        assert open_spec.parameters["required"] == ["app"]
