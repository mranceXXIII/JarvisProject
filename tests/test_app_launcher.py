"""Tests for the application registry and launcher (spec section 9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.app_launcher import AppLauncher, LauncherError
from core.config_loader import ApplicationConfig


class FakePopen:
    """Records launch calls instead of starting real processes."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.pid = 4242

    def __call__(self, command, **kwargs):
        self.calls.append({"command": command, **kwargs})
        return self


def _make_exe(directory: Path, filename: str = "tool.exe") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / filename
    exe.write_bytes(b"MZ")  # placeholder bytes; existence is what matters
    return exe


def _path_app(name: str, path: Path, **kwargs) -> ApplicationConfig:
    return ApplicationConfig.model_validate({"name": name, "path": str(path), **kwargs})


def _dir_app(name: str, directory: Path, executable: str, **kwargs) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {"name": name, "directory": str(directory), "executable": executable, **kwargs}
    )


@pytest.mark.unit
class TestRegistryValidation:
    def test_path_form_valid(self) -> None:
        app = _path_app("notepad", Path("C:/Windows/System32/notepad.exe"))
        assert app.display_name == "notepad"

    def test_directory_form_valid(self, tmp_path: Path) -> None:
        app = _dir_app("myapp", tmp_path, "myapp.exe")
        assert app.directory == str(tmp_path)
        assert app.executable == "myapp.exe"

    def test_both_forms_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(Exception, match="not both"):
            ApplicationConfig.model_validate(
                {
                    "name": "bad",
                    "path": str(tmp_path / "a.exe"),
                    "directory": str(tmp_path),
                    "executable": "b.exe",
                }
            )

    def test_neither_form_rejected(self) -> None:
        with pytest.raises(Exception, match="provide 'path'"):
            ApplicationConfig.model_validate({"name": "bad"})

    def test_directory_without_executable_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(Exception):
            ApplicationConfig.model_validate(
                {"name": "bad", "directory": str(tmp_path)}
            )

    def test_invalid_name_rejected(self) -> None:
        with pytest.raises(Exception):
            ApplicationConfig.model_validate(
                {"name": "bad name!", "path": "C:/x.exe"}
            )

    def test_invalid_alias_rejected(self) -> None:
        with pytest.raises(Exception, match="alias"):
            ApplicationConfig.model_validate(
                {"name": "app", "path": "C:/x.exe", "aliases": ["bad alias"]}
            )

    def test_duplicate_names_rejected(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path)
        with pytest.raises(LauncherError, match="duplicate application name"):
            AppLauncher((_path_app("same", exe), _path_app("same", exe)))

    def test_duplicate_aliases_rejected(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path)
        with pytest.raises(LauncherError, match="duplicate alias"):
            AppLauncher(
                (
                    _path_app("one", exe, aliases=["dup"]),
                    _path_app("two", exe, aliases=["dup"]),
                )
            )

    def test_real_project_config_loads(self) -> None:
        from core.config_loader import load_application_configs

        apps = load_application_configs()
        names = {app.name for app in apps}
        assert {"cmd", "powershell", "notepad"} <= names


@pytest.mark.unit
class TestResolution:
    def test_resolve_by_name_case_insensitive(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path)
        launcher = AppLauncher((_path_app("Notepad", exe),))
        assert launcher.resolve("NOTEPAD").name == "Notepad"

    def test_resolve_by_alias(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path)
        launcher = AppLauncher((_path_app("powershell", exe, aliases=["pwsh"]),))
        assert launcher.resolve("pwsh").name == "powershell"

    def test_unknown_name_refused(self) -> None:
        launcher = AppLauncher()
        with pytest.raises(LauncherError, match="not registered"):
            launcher.resolve("definitely-not-registered")


@pytest.mark.unit
class TestLaunching:
    def test_launch_path_form(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path)
        fake = FakePopen()
        launcher = AppLauncher((_path_app("tool", exe),), popen=fake)
        result = launcher.open("tool")
        assert result.success is True
        assert result.pid == 4242
        call = fake.calls[0]
        assert call["command"] == [str(exe)]
        assert call["shell"] is False

    def test_launch_directory_form_searches_only_that_directory(
        self, tmp_path: Path
    ) -> None:
        app_dir = tmp_path / "MyAppDir"
        exe = _make_exe(app_dir, "myapp.exe")
        fake = FakePopen()
        launcher = AppLauncher((_dir_app("myapp", app_dir, "myapp.exe"),), popen=fake)
        result = launcher.open("myapp")
        assert result.success is True
        call = fake.calls[0]
        assert call["command"] == [str(exe)]
        assert call["cwd"] == str(app_dir)

    def test_launch_uses_configured_args_and_working_dir(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path)
        work = tmp_path / "work"
        work.mkdir()
        fake = FakePopen()
        launcher = AppLauncher(
            (
                _path_app(
                    "tool", exe, args=["--flag", "value"], working_dir=str(work)
                ),
            ),
            popen=fake,
        )
        launcher.open("tool")
        call = fake.calls[0]
        assert call["command"] == [str(exe), "--flag", "value"]
        assert call["cwd"] == str(work)

    def test_missing_executable_refused(self, tmp_path: Path) -> None:
        launcher = AppLauncher(
            (_dir_app("ghost", tmp_path, "ghost.exe"),), popen=FakePopen()
        )
        result = launcher.open("ghost")
        assert result.success is False
        assert "not found" in result.message

    def test_os_error_reported_honestly(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path)

        def failing_popen(*args, **kwargs):
            raise OSError("access denied")

        launcher = AppLauncher((_path_app("tool", exe),), popen=failing_popen)
        result = launcher.open("tool")
        assert result.success is False
        assert "access denied" in result.message

    def test_unregistered_launch_refused(self) -> None:
        launcher = AppLauncher(popen=FakePopen())
        result = launcher.open("cmd")
        assert result.success is False


@pytest.mark.unit
def test_launcher_never_uses_shell(tmp_path: Path) -> None:
    """Guard: launch calls must always pass shell=False."""
    exe = _make_exe(tmp_path)
    fake = FakePopen()
    launcher = AppLauncher((_path_app("tool", exe),), popen=fake)
    launcher.open("tool")
    assert fake.calls[0]["shell"] is False


@pytest.mark.integration
def test_cli_list_real_config(capsys: pytest.CaptureFixture) -> None:
    from automation.app_launcher import main

    exit_code = main(["list"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "powershell" in output
    assert "cmd" in output
