"""Windows startup management (spec section 17).

Registers/unregisters JARVIS under the per-user Run key
(HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run), so no admin
rights are needed. The registry access layer is injectable for tests; when
not on Windows (or winreg unavailable) the manager reports unavailable
honestly.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger("jarvis.startup")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "JARVIS"


class StartupError(RuntimeError):
    """Raised when a startup registry operation fails."""


class _RealRegistryApi:
    """winreg-backed registry access (Windows only)."""

    def __init__(self) -> None:
        import winreg  # Windows only

        self._winreg = winreg

    def set_value(self, name: str, command: str) -> None:
        with self._winreg.OpenKey(
            self._winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            self._winreg.KEY_SET_VALUE,
        ) as key:
            self._winreg.SetValueEx(key, name, 0, self._winreg.REG_SZ, command)

    def get_value(self, name: str) -> str | None:
        try:
            with self._winreg.OpenKey(
                self._winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                self._winreg.KEY_QUERY_VALUE,
            ) as key:
                value, _type = self._winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def delete_value(self, name: str) -> None:
        try:
            with self._winreg.OpenKey(
                self._winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                self._winreg.KEY_SET_VALUE,
            ) as key:
                self._winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return  # already gone - idempotent


class _UnavailableApi:
    def set_value(self, name: str, command: str) -> None:
        raise StartupError("startup registry unavailable on this platform")

    def get_value(self, name: str) -> str | None:
        return None

    def delete_value(self, name: str) -> None:
        raise StartupError("startup registry unavailable on this platform")


class StartupManager:
    """Enables/disables JARVIS launch at Windows sign-in (per-user)."""

    def __init__(self, project_root: Path, registry_api=None) -> None:
        self._project_root = project_root
        if registry_api is not None:
            self._api = registry_api
        elif sys.platform == "win32":
            try:
                self._api = _RealRegistryApi()
            except Exception as exc:  # pragma: no cover
                logger.warning("winreg unavailable: %s", exc)
                self._api = _UnavailableApi()
        else:
            self._api = _UnavailableApi()

    @property
    def available(self) -> bool:
        return not isinstance(self._api, _UnavailableApi)

    def _command(self) -> str:
        """Command that starts JARVIS: venv pythonw + main.py when present."""
        venv_pythonw = self._project_root / ".venv" / "Scripts" / "pythonw.exe"
        venv_python = self._project_root / ".venv" / "Scripts" / "python.exe"
        main_py = self._project_root / "main.py"
        if venv_pythonw.is_file():
            return f'"{venv_pythonw}" "{main_py}"'
        if venv_python.is_file():
            return f'"{venv_python}" "{main_py}"'
        return f'"{sys.executable}" "{main_py}"'

    def is_enabled(self) -> bool:
        return self._api.get_value(RUN_VALUE_NAME) is not None

    def get_command(self) -> str | None:
        return self._api.get_value(RUN_VALUE_NAME)

    def enable(self) -> str:
        command = self._command()
        try:
            self._api.set_value(RUN_VALUE_NAME, command)
        except OSError as exc:
            raise StartupError(f"could not enable startup: {exc}") from exc
        logger.info("startup enabled: %s", command)
        return f"JARVIS will start at sign-in: {command}"

    def disable(self) -> str:
        try:
            self._api.delete_value(RUN_VALUE_NAME)
        except OSError as exc:
            raise StartupError(f"could not disable startup: {exc}") from exc
        logger.info("startup disabled")
        return "JARVIS will no longer start at sign-in."
