"""Safe file operations with path containment (spec sections 9, 16).

All paths must resolve inside one of the configured allowed roots; path
traversal outside the roots is refused no matter what any approval says.
Reads are size-capped, listings are entry-capped, and every mutating
operation is registered as a medium/high risk tool so the approval system
gates it.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from core.config_loader import FileAccessConfig

logger = logging.getLogger("jarvis.automation.files")


class FileSafetyError(RuntimeError):
    """Raised when a path is outside allowed roots or a limit is exceeded."""


class FileManager:
    """Contained file operations for the file tools."""

    def __init__(self, config: FileAccessConfig) -> None:
        self._config = config
        self._roots = [
            Path(root).expanduser().resolve() for root in config.allowed_roots
        ]

    @property
    def allowed_roots(self) -> list[Path]:
        return list(self._roots)

    def _resolve(self, raw: str) -> Path:
        if not raw or not raw.strip():
            raise FileSafetyError("empty path")
        candidate = Path(raw).expanduser()
        resolved = candidate.resolve()
        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return resolved
        raise FileSafetyError(
            f"path '{raw}' is outside the allowed roots "
            f"({', '.join(str(r) for r in self._roots)})"
        )

    def list_directory(self, raw_path: str) -> str:
        """List a directory's entries (capped)."""
        directory = self._resolve(raw_path)
        if not directory.is_dir():
            raise FileSafetyError(f"not a directory: '{raw_path}'")
        entries = sorted(
            directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
        lines: list[str] = []
        for entry in entries[: self._config.max_list_entries]:
            kind = "dir " if entry.is_dir() else "file"
            lines.append(f"[{kind}] {entry.name}")
        total = len(entries)
        header = f"{total} entries in {directory}"
        if total > self._config.max_list_entries:
            header += f" (showing first {self._config.max_list_entries})"
        return "\n".join([header, *lines])

    def read_text(self, raw_path: str) -> str:
        """Read a text file (size-capped)."""
        file_path = self._resolve(raw_path)
        if not file_path.is_file():
            raise FileSafetyError(f"not a file: '{raw_path}'")
        size = file_path.stat().st_size
        if size > self._config.max_read_bytes:
            raise FileSafetyError(
                f"file too large to read ({size} > {self._config.max_read_bytes} bytes)"
            )
        return file_path.read_text(encoding="utf-8", errors="replace")

    def write_text(self, raw_path: str, content: str) -> str:
        """Create or overwrite a text file inside an allowed root."""
        file_path = self._resolve(raw_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        logger.info("wrote %d bytes to %s", len(content), file_path)
        return f"wrote {len(content)} characters to {file_path}"

    def move_file(self, raw_source: str, raw_destination: str) -> str:
        source = self._resolve(raw_source)
        destination = self._resolve(raw_destination)
        if not source.is_file():
            raise FileSafetyError(f"source is not a file: '{raw_source}'")
        moved = shutil.move(str(source), str(destination))
        return f"moved to {moved}"

    def copy_file(self, raw_source: str, raw_destination: str) -> str:
        source = self._resolve(raw_source)
        destination = self._resolve(raw_destination)
        if not source.is_file():
            raise FileSafetyError(f"source is not a file: '{raw_source}'")
        destination.parent.mkdir(parents=True, exist_ok=True)
        copied = shutil.copy2(str(source), str(destination))
        return f"copied to {copied}"

    def delete_file(self, raw_path: str) -> str:
        """Permanently delete a file (high risk; approval required)."""
        file_path = self._resolve(raw_path)
        if not file_path.is_file():
            raise FileSafetyError(f"not a file: '{raw_path}'")
        file_path.unlink()
        logger.warning("deleted file %s", file_path)
        return f"deleted {file_path}"
