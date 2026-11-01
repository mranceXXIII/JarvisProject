"""Tests for Phase 6: window manager, file manager, command runner, tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.command_runner import CommandNotAllowedError, CommandRunner
from automation.file_manager import FileSafetyError, FileManager
from automation.window_manager import WindowError, WindowManager
from core.config_loader import CommandRunnerConfig, FileAccessConfig
from core.tool_registry import ToolRegistry
from automation.window_manager import WindowInfo


class FakeWinApi:
    """In-memory window list mirroring the real API surface."""

    def __init__(self) -> None:
        self.windows = [
            (101, "Untitled - Notepad"),
            (102, "Command Prompt"),
        ]
        self.states = {
            101: {"iconic": False, "zoomed": False},
            102: {"iconic": True, "zoomed": False},
        }
        self.actions: list[tuple[int, str]] = []

    def enum_visible_windows(self):
        return list(self.windows)

    def set_foreground(self, hwnd):
        self.actions.append((hwnd, "foreground"))
        return True

    def show(self, hwnd, command):
        self.actions.append((hwnd, f"show{command}"))
        return True

    def close(self, hwnd):
        self.actions.append((hwnd, "close"))
        return True

    def is_iconic(self, hwnd):
        return self.states[hwnd]["iconic"]

    def is_zoomed(self, hwnd):
        return self.states[hwnd]["zoomed"]


@pytest.fixture
def file_manager(tmp_path: Path) -> FileManager:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "hello.txt").write_text("hello world", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    config = FileAccessConfig(allowed_roots=[str(root)], max_read_bytes=1000)
    return FileManager(config)


@pytest.mark.unit
class TestWindowManager:
    def test_lists_windows_with_states(self) -> None:
        manager = WindowManager(api=FakeWinApi())
        windows = manager.list_windows()
        assert {w.title for w in windows} == {"Untitled - Notepad", "Command Prompt"}
        assert windows[1].minimized is True

    def test_find_by_substring_case_insensitive(self) -> None:
        manager = WindowManager(api=FakeWinApi())
        assert manager._find("notepad").hwnd == 101

    def test_activate_and_minimize(self) -> None:
        api = FakeWinApi()
        manager = WindowManager(api=api)
        assert "activated" in manager.activate("notepad")
        assert "minimized" in manager.minimize("command prompt")
        assert (101, "foreground") in api.actions

    def test_close_sends_wm_close(self) -> None:
        api = FakeWinApi()
        manager = WindowManager(api=api)
        assert "close request" in manager.close("notepad")
        assert any(action == "close" for _hwnd, action in api.actions)

    def test_unknown_window_raises(self) -> None:
        manager = WindowManager(api=FakeWinApi())
        with pytest.raises(WindowError, match="no visible window"):
            manager.activate("does not exist")

    def test_window_info_model(self) -> None:
        info = WindowInfo(hwnd=1, title="x", minimized=False, maximized=True)
        assert info.maximized is True


@pytest.mark.unit
class TestFileManager:
    def test_allowed_root_operations(self, file_manager, tmp_path) -> None:
        listing = file_manager.list_directory(str(tmp_path / "root" / "sub"))
        assert "hello.txt" in listing
        content = file_manager.read_text(
            str(tmp_path / "root" / "sub" / "hello.txt")
        )
        assert content == "hello world"

    def test_outside_root_refused(self, file_manager, tmp_path) -> None:
        with pytest.raises(FileSafetyError, match="outside the allowed roots"):
            file_manager.read_text(str(tmp_path / "outside" / "secret.txt"))

    def test_traversal_refused(self, file_manager, tmp_path) -> None:
        sneaky = str(
            tmp_path / "root" / "sub" / ".." / ".." / "outside" / "secret.txt"
        )
        with pytest.raises(FileSafetyError):
            file_manager.read_text(sneaky)

    def test_write_creates_file(self, file_manager, tmp_path) -> None:
        target = str(tmp_path / "root" / "sub" / "new.txt")
        message = file_manager.write_text(target, "data")
        assert "wrote" in message
        assert Path(target).read_text(encoding="utf-8") == "data"

    def test_move_and_copy(self, file_manager, tmp_path) -> None:
        src = str(tmp_path / "root" / "sub" / "hello.txt")
        copy_dst = str(tmp_path / "root" / "sub" / "copy.txt")
        file_manager.copy_file(src, copy_dst)
        assert Path(copy_dst).exists()
        move_dst = str(tmp_path / "root" / "sub" / "moved.txt")
        file_manager.move_file(copy_dst, move_dst)
        assert not Path(copy_dst).exists()
        assert Path(move_dst).exists()

    def test_delete_file(self, file_manager, tmp_path) -> None:
        target = tmp_path / "root" / "sub" / "hello.txt"
        result = file_manager.delete_file(str(target))
        assert "deleted" in result
        assert not target.exists()

    def test_read_size_cap(self, file_manager, tmp_path) -> None:
        big = tmp_path / "root" / "big.txt"
        big.write_text("x" * 2000, encoding="utf-8")
        with pytest.raises(FileSafetyError, match="too large"):
            file_manager.read_text(str(big))


@pytest.mark.unit
class TestCommandRunner:
    def _runner(self, runner=None) -> CommandRunner:
        config = CommandRunnerConfig(
            allowed_executables=["ipconfig", "ping"],
            timeout_seconds=5,
            max_output_chars=100,
        )
        return CommandRunner(config, runner=runner)

    def test_allowlist_enforced(self) -> None:
        with pytest.raises(CommandNotAllowedError, match="not on the allowlist"):
            self._runner().run("format", ["c:"])

    def test_paths_rejected(self) -> None:
        with pytest.raises(CommandNotAllowedError, match="paths are not allowed"):
            self._runner().run("C:/Windows/System32/ipconfig.exe")

    def test_forbidden_characters_in_args(self) -> None:
        with pytest.raises(CommandNotAllowedError, match="forbidden characters"):
            self._runner().run("ping", ["localhost & format c:"])

    def test_successful_run(self) -> None:
        class FakeCompleted:
            returncode = 0
            stdout = "output text"
            stderr = ""

        result = self._runner(lambda *a, **k: FakeCompleted()).run("ipconfig")
        assert result.success is True
        assert result.output == "output text"
        assert result.return_code == 0

    def test_output_capped(self) -> None:
        class FakeCompleted:
            returncode = 0
            stdout = "x" * 5000
            stderr = ""

        result = self._runner(lambda *a, **k: FakeCompleted()).run("ipconfig")
        assert len(result.output) <= 100

    def test_nonzero_return_code_fails(self) -> None:
        class FakeCompleted:
            returncode = 2
            stdout = ""
            stderr = "error occurred"

        result = self._runner(lambda *a, **k: FakeCompleted()).run("ping", ["badhost"])
        assert result.success is False
        assert "error occurred" in result.output


@pytest.mark.unit
class TestAutomationToolRegistration:
    def test_tools_registered_with_risk_levels(self, tmp_path: Path) -> None:
        from core.automation_tools import register_automation_tools

        registry = ToolRegistry()
        register_automation_tools(
            registry, WindowManager(api=FakeWinApi()), None, None, tmp_path
        )
        risks = {t.name: t.risk for t in registry.list_tools()}
        assert risks["list_windows"] == "low"
        assert risks["close_window"] == "medium"
        assert "delete_file" not in risks  # file manager not provided

    def test_all_registered_with_all_components(self, tmp_path: Path) -> None:
        from core.automation_tools import register_automation_tools

        registry = ToolRegistry()
        register_automation_tools(
            registry,
            WindowManager(api=FakeWinApi()),
            FileManager(FileAccessConfig(allowed_roots=[str(tmp_path)])),
            CommandRunner(CommandRunnerConfig()),
            tmp_path,
        )
        names = {t.name for t in registry.list_tools()}
        assert {
            "list_windows", "activate_window", "close_window",
            "list_directory", "read_file", "write_file", "move_file",
            "copy_file", "delete_file", "run_command", "take_screenshot",
        } <= names
        risks = {t.name: t.risk for t in registry.list_tools()}
        assert risks["delete_file"] == "high"
        assert risks["run_command"] == "high"
        assert risks["write_file"] == "medium"

    def test_file_tool_execution_roundtrip(self, tmp_path: Path) -> None:
        from core.automation_tools import register_automation_tools

        registry = ToolRegistry()
        register_automation_tools(
            registry,
            None,
            FileManager(FileAccessConfig(allowed_roots=[str(tmp_path)])),
            None,
            tmp_path,
        )
        target = tmp_path / "note.txt"
        result = registry.execute(
            "write_file", {"path": str(target), "content": "hi"}
        )
        assert result.success is True
        assert target.read_text(encoding="utf-8") == "hi"

    def test_high_risk_tools_trigger_approval_flow(
        self, tmp_path: Path
    ) -> None:
        """delete_file and run_command are HIGH risk, so the permission
        checker always demands approval before they can execute."""
        from core.automation_tools import register_automation_tools
        from core.config_loader import PermissionPolicy
        from security.permission_checker import PermissionChecker

        registry = ToolRegistry()
        register_automation_tools(
            registry,
            None,
            FileManager(FileAccessConfig(allowed_roots=[str(tmp_path)])),
            CommandRunner(CommandRunnerConfig()),
            tmp_path,
        )
        checker = PermissionChecker(PermissionPolicy())
        for tool_name in ("delete_file", "run_command"):
            risk = registry.get(tool_name).risk
            assert checker.check(tool_name, risk).approval_required is True
