"""Append-only audit trail for consequential actions (spec section 16).

Records proposed actions, approval decisions, and outcomes as JSON lines.
Every string value is passed through secret redaction before writing, so
credentials never enter the audit file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging_setup import redact_text

logger = logging.getLogger("jarvis.security.audit")


class AuditLogger:
    """Writes JSON-lines audit events to a file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def log(self, event: str, **details: Any) -> None:
        """Append one audit event; string values are secret-redacted."""
        safe_details = {
            key: (
                redact_text(value)
                if isinstance(value, str)
                else (
                    {
                        k: redact_text(v) if isinstance(v, str) else v
                        for k, v in value.items()
                    }
                    if isinstance(value, dict)
                    else value
                )
            )
            for key, value in details.items()
        }
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            **safe_details,
        }
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            # Audit failures must be visible but never crash the caller.
            logger.error("failed to write audit event '%s': %s", event, exc)

    def read_events(self) -> list[dict]:
        """Return all audit events (for diagnostics and tests)."""
        if not self._path.exists():
            return []
        events: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events
