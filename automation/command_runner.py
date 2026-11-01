"""Allowlisted command runner (spec sections 9, 16).

HIGH RISK. Rules enforced here:
- Only executables on the configured allowlist can ever run (exact name,
  case-insensitive; no paths, no shell).
- Commands always run as an argv list with shell=False.
- Timeout and output cap apply; stderr is captured separately.
- The tool registration marks this high risk, so the approval dialog always
  asks before anything runs.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from core.config_loader import CommandRunnerConfig

logger = logging.getLogger("jarvis.automation.commands")

_FORBIDDEN_CHARS = set("\"'`|&;<>(){}[]!$")


class CommandNotAllowedError(RuntimeError):
    """Raised when an executable is not on the allowlist."""


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one allowlisted command."""

    executable: str
    success: bool
    output: str
    return_code: int | None
    duration_seconds: float


class CommandRunner:
    """Runs allowlisted executables without a shell."""

    def __init__(self, config: CommandRunnerConfig, runner=None) -> None:
        self._config = config
        self._allowed = {name.lower() for name in config.allowed_executables}
        self._runner = runner if runner is not None else subprocess.run

    @property
    def allowed_executables(self) -> tuple[str, ...]:
        return tuple(sorted(self._allowed))

    def _validate(self, executable: str, args: list[str]) -> str | None:
        name = executable.strip().lower()
        if not name:
            return "empty executable name"
        if Path(executable).name != executable:
            return f"paths are not allowed in the allowlist; got '{executable}'"
        if name not in self._allowed:
            return (
                f"executable '{executable}' is not on the allowlist "
                f"({', '.join(sorted(self._allowed))})"
            )
        for arg in args:
            if not isinstance(arg, str):
                return "all arguments must be strings"
            if any(ch in arg for ch in _FORBIDDEN_CHARS):
                return f"argument contains forbidden characters: {arg!r}"
        return None

    def run(self, executable: str, args: list[str] | None = None) -> CommandResult:
        """Run an allowlisted executable; never uses a shell."""
        args = list(args or [])
        problem = self._validate(executable, args)
        if problem:
            logger.warning("command refused: %s", problem)
            raise CommandNotAllowedError(problem)

        argv = [executable, *args]
        started = time.monotonic()
        try:
            completed = self._runner(
                argv,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("command '%s' timed out", executable)
            return CommandResult(
                executable=executable,
                success=False,
                output=f"timed out after {self._config.timeout_seconds}s",
                return_code=None,
                duration_seconds=time.monotonic() - started,
            )
        except OSError as exc:
            logger.error("command '%s' failed to start: %s", executable, exc)
            return CommandResult(
                executable=executable,
                success=False,
                output=f"failed to start: {exc}",
                return_code=None,
                duration_seconds=time.monotonic() - started,
            )

        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        output = output[: self._config.max_output_chars]
        success = completed.returncode == 0
        duration = time.monotonic() - started
        logger.info(
            "command '%s' finished rc=%s (%.1fs)", executable,
            completed.returncode, duration,
        )
        return CommandResult(
            executable=executable,
            success=success,
            output=output or "(no output)",
            return_code=completed.returncode,
            duration_seconds=duration,
        )
