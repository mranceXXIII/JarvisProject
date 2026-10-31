"""SQLite storage for JARVIS (Phase 3).

Owns the connection and schema for local durable memory. One database file
per JARVIS instance (default ``data/jarvis.db``). Connections are opened per
operation, which keeps the store safe to use from UI threads and background
threads alike.

The store never receives secret values: conversation content and task
outcomes only (JARVIS_Project_Context.md 13).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("jarvis.memory.database")

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id)
        ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS task_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'cancelled')),
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_task_outcomes_created
    ON task_outcomes(created_at);
"""


class MemoryDatabase:
    """SQLite database wrapper for JARVIS memory."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
        logger.info("memory database ready at %s", self._path)

    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        """Run a write statement in a transaction and return the cursor."""
        connection = self._connect()
        try:
            cursor = connection.execute(sql, parameters)
            connection.commit()
            return cursor
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def query_all(self, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        """Run a read statement and return all rows."""
        connection = self._connect()
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(sql, parameters).fetchall()
        finally:
            connection.close()

    def query_one(self, sql: str, parameters: tuple = ()) -> sqlite3.Row | None:
        """Run a read statement and return the first row, if any."""
        rows = self.query_all(sql, parameters)
        return rows[0] if rows else None

    def backup_to(self, target: Path | str) -> Path:
        """Create a consistent backup using the SQLite backup API."""
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source = self._connect()
        try:
            destination = sqlite3.connect(target_path)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        logger.info("memory backed up to %s", target_path)
        return target_path
