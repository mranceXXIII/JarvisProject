"""JARVIS launcher: convenient entry point for shortcuts and startup.

Finds the project virtual-environment Python and re-executes ``main.py``
with all arguments. Used by the Windows startup entry so sign-in launches
run with the correct interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def find_python() -> Path | None:
    """Prefer pythonw (no console), then python, then the current one."""
    for name in ("pythonw.exe", "python.exe"):
        candidate = PROJECT_ROOT / ".venv" / "Scripts" / name
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def main() -> int:
    python = find_python()
    main_py = PROJECT_ROOT / "main.py"
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [str(python), str(main_py), *sys.argv[1:]],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
