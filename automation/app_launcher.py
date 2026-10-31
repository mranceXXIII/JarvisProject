"""Application launcher with a user-editable app registry (spec section 9).

JARVIS opens ONLY applications registered in ``config/applications.yaml``.
Each entry points either directly at an executable path or at a directory +
executable pair, so lookup is restricted to the folder the user configured.

Security rules enforced here:
- Launches always use an argument list via ``subprocess.Popen``; the shell is
  never involved (``shell=False``), so no arbitrary command chaining or
  injection is possible.
- Unregistered names are refused; the launcher never falls back to searching
  the whole system or executing AI-generated command strings.
- The executable must exist at the configured location before launch.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from core.config_loader import ApplicationConfig, load_application_configs

logger = logging.getLogger("jarvis.automation.launcher")


class LauncherError(RuntimeError):
    """Raised when an application cannot be resolved or launched."""


@dataclass(frozen=True)
class LaunchResult:
    """Outcome of one launch attempt."""

    app_name: str
    success: bool
    message: str
    executable: str
    pid: int | None = None


class AppLauncher:
    """Resolves registered applications and launches them safely."""

    def __init__(
        self,
        applications: tuple[ApplicationConfig, ...] = (),
        popen: subprocess.Popen | None = None,
    ) -> None:
        self._apps: dict[str, ApplicationConfig] = {}
        self._alias_owner: dict[str, str] = {}
        for app in applications:
            key = app.name.lower()
            if key in self._apps:
                raise LauncherError(f"duplicate application name: '{app.name}'")
            self._apps[key] = app
            for alias in app.aliases:
                if alias in self._alias_owner:
                    raise LauncherError(
                        f"duplicate alias '{alias}' between "
                        f"'{self._alias_owner[alias]}' and '{app.name}'"
                    )
                self._alias_owner[alias] = app.name
        self._popen = popen if popen is not None else subprocess.Popen

    @classmethod
    def from_config_dir(cls, config_dir: Path | str) -> "AppLauncher":
        return cls(load_application_configs(config_dir))

    def list_apps(self) -> tuple[ApplicationConfig, ...]:
        """All registered applications, in configuration order."""
        return tuple(self._apps.values())

    def resolve(self, name: str) -> ApplicationConfig:
        """Resolve *name* (or alias, case-insensitive) to a registration."""
        key = name.strip().lower()
        key = self._alias_owner.get(key, key)
        app = self._apps.get(key)
        if app is None:
            known = ", ".join(sorted(self._apps)) or "<none registered>"
            raise LauncherError(
                f"application '{name}' is not registered (registered: {known})"
            )
        return app

    def executable_path(self, app: ApplicationConfig) -> Path:
        """Return the validated executable path for *app*.

        For the directory form, only the configured directory is searched.
        """
        if app.path:
            exe_path = Path(app.path)
        else:
            exe_path = Path(app.directory or "") / (app.executable or "")
        if not exe_path.is_file():
            raise LauncherError(
                f"executable for '{app.name}' not found at '{exe_path}'"
            )
        return exe_path

    def open(self, name: str) -> LaunchResult:
        """Launch a registered application by name or alias."""
        try:
            app = self.resolve(name)
            exe_path = self.executable_path(app)
        except LauncherError as exc:
            logger.warning("launch refused: %s", exc)
            return LaunchResult(
                app_name=name, success=False, message=str(exc), executable=""
            )

        command = [str(exe_path), *app.args]
        working_dir = app.working_dir or app.directory
        try:
            process = self._popen(
                command,
                cwd=working_dir,
                shell=False,
                close_fds=True,
            )
        except OSError as exc:
            logger.error("failed to launch '%s': %s", app.name, exc)
            return LaunchResult(
                app_name=app.name,
                success=False,
                message=f"failed to launch '{app.name}': {exc}",
                executable=str(exe_path),
            )
        logger.info(
            "launched '%s' (pid %s) from %s",
            app.name,
            process.pid,
            working_dir or exe_path.parent,
        )
        return LaunchResult(
            app_name=app.name,
            success=True,
            message=f"launched '{app.display_name or app.name}'",
            executable=str(exe_path),
            pid=process.pid,
        )


def main(argv: list[str] | None = None) -> int:
    """CLI for manual testing: list or open registered applications."""
    parser = argparse.ArgumentParser(
        description="Launch applications registered in config/applications.yaml"
    )
    parser.add_argument("command", choices=["list", "open"])
    parser.add_argument("name", nargs="?", help="application name or alias")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "config",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    launcher = AppLauncher.from_config_dir(args.config_dir)
    if args.command == "list":
        apps = launcher.list_apps()
        if not apps:
            print("No applications registered in applications.yaml")
            return 0
        for app in apps:
            alias_note = f" (aliases: {', '.join(app.aliases)})" if app.aliases else ""
            print(f"- {app.name}{alias_note}: {app.display_name or app.name}")
        return 0

    if not args.name:
        parser.error("'open' requires an application name")
    result = launcher.open(args.name)
    print(result.message)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
