"""Logging setup with secret redaction for JARVIS.

Every handler receives a :class:`SecretRedactingFilter`, so registered
credentials and common token patterns never reach log files or the console
(JARVIS_Project_Context.md 5.9, acceptance criterion 6).
"""

from __future__ import annotations

import logging
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable, Pattern

from core.config_loader import LoggingSettings

MASK = "***REDACTED***"

# Common API-token shapes. Kept conservative to limit false positives.
_TOKEN_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),          # OpenAI-style keys
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),           # GitHub personal tokens
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),         # Google API keys
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),   # Bearer headers
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot tokens
)


class SecretRegistry:
    """Thread-safe registry of secret values that must be redacted."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secrets: set[str] = set()

    def register(self, secret: str) -> None:
        """Register a secret value for redaction."""
        if not secret or len(secret) < 8:
            return  # too short to redact reliably; skip to avoid noise
        with self._lock:
            self._secrets.add(secret)

    def snapshot(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._secrets)

    def clear(self) -> None:
        with self._lock:
            self._secrets.clear()


# Global registry used by the credential manager and the log filter.
secret_registry = SecretRegistry()


def redact_text(text: str, secrets: Iterable[str] | None = None) -> str:
    """Return *text* with registered secrets and known token patterns masked."""
    known = tuple(secrets) if secrets is not None else secret_registry.snapshot()
    for secret in known:
        text = text.replace(secret, MASK)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


class SecretRedactingFilter(logging.Filter):
    """Logging filter that masks secrets in every emitted record.

    Optionally accepts an explicit collection of secrets; by default it
    redacts values registered in the global ``secret_registry``.
    """

    def __init__(self, secrets: Iterable[str] | None = None) -> None:
        super().__init__()
        self._secrets = tuple(secrets) if secrets is not None else None

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_text(message, self._secrets)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(config: LoggingSettings, project_root: Path | None = None) -> logging.Logger:
    """Configure the root JARVIS logger and return it.

    Installs a rotating file handler and a console handler, both protected by
    :class:`SecretRedactingFilter`.
    """
    root = logging.getLogger("jarvis")
    root.setLevel(config.level)
    root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = Path(config.file)
    if not log_path.is_absolute():
        base = project_root if project_root is not None else Path.cwd()
        log_path = base / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretRedactingFilter())
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(SecretRedactingFilter())
    root.addHandler(console_handler)

    return root
