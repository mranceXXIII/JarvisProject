"""Conversation and task-outcome storage with full-text search (Phase 3).

FTS5 is used when the bundled SQLite provides it; otherwise search falls
back to a case-insensitive LIKE scan. Search queries are escaped so user
input cannot inject FTS syntax (treat input as untrusted data).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from memory.database import MemoryDatabase

logger = logging.getLogger("jarvis.memory.conversation_store")

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


def fts5_available() -> bool:
    """True when the runtime SQLite build supports FTS5."""
    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            return True
        finally:
            connection.close()
    except sqlite3.Error:
        return False


@dataclass(frozen=True)
class Message:
    """One stored conversation message."""

    id: int
    conversation_id: int
    role: str
    content: str
    provider: str | None
    model: str | None
    created_at: str


@dataclass(frozen=True)
class SearchResult:
    """One full-text search hit."""

    message_id: int
    conversation_id: int
    role: str
    snippet: str
    created_at: str
    conversation_title: str = ""


@dataclass(frozen=True)
class TaskOutcome:
    """One recorded task outcome."""

    id: int
    conversation_id: int | None
    task_type: str
    status: str
    detail: str
    created_at: str


def _escape_fts_query(query: str) -> str:
    """Turn raw user input into a safe FTS5 phrase query."""
    return '"' + query.replace('"', '""') + '"'


class ConversationStore:
    """Persists conversations, messages, and task outcomes."""

    def __init__(self, database: MemoryDatabase, use_fts: bool | None = None) -> None:
        self._db = database
        self._fts = fts5_available() if use_fts is None else use_fts
        if self._fts:
            with self._db._connect() as connection:  # noqa: SLF001 - owned instance
                connection.executescript(FTS_SCHEMA)
        logger.info(
            "conversation store ready (full-text search: %s)",
            "FTS5" if self._fts else "LIKE fallback",
        )

    @property
    def full_text_search_enabled(self) -> bool:
        return self._fts

    # -- conversations -------------------------------------------------

    def create_conversation(self, title: str = "") -> int:
        cursor = self._db.execute(
            "INSERT INTO conversations (title) VALUES (?)", (title,)
        )
        return int(cursor.lastrowid)

    def rename_conversation(self, conversation_id: int, title: str) -> None:
        self._db.execute(
            "UPDATE conversations SET title = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (title, conversation_id),
        )

    def list_conversations(self, limit: int = 50) -> list[dict]:
        rows = self._db.query_all(
            "SELECT id, title, created_at, updated_at, "
            "(SELECT COUNT(*) FROM messages WHERE conversation_id = conversations.id) "
            "AS message_count "
            "FROM conversations ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    # -- messages ------------------------------------------------------

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> int:
        """Store one message; returns its id. Persistence is committed
        before the id is returned."""
        cursor = self._db.execute(
            "INSERT INTO messages (conversation_id, role, content, provider, model) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, provider, model),
        )
        self._db.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        return int(cursor.lastrowid)

    def get_messages(self, conversation_id: int) -> list[Message]:
        rows = self._db.query_all(
            "SELECT id, conversation_id, role, content, provider, model, created_at "
            "FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        )
        return [Message(**dict(row)) for row in rows]

    def recent_messages(self, conversation_id: int, count: int) -> list[Message]:
        """The most recent *count* messages in chronological order."""
        rows = self._db.query_all(
            "SELECT id, conversation_id, role, content, provider, model, created_at "
            "FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, count),
        )
        return [Message(**dict(row)) for row in reversed(rows)]

    # -- search --------------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Full-text search across all stored messages."""
        query = query.strip()
        if not query:
            return []
        if self._fts:
            return self._search_fts(query, limit)
        return self._search_like(query, limit)

    def _search_fts(self, query: str, limit: int) -> list[SearchResult]:
        try:
            rows = self._db.query_all(
                "SELECT m.id AS message_id, m.conversation_id, m.role, m.created_at, "
                "snippet(messages_fts, 0, '[', ']', '…', 12) AS snippet, "
                "COALESCE(c.title, '') AS conversation_title "
                "FROM messages_fts "
                "JOIN messages m ON m.id = messages_fts.rowid "
                "LEFT JOIN conversations c ON c.id = m.conversation_id "
                "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
                (_escape_fts_query(query), limit),
            )
        except sqlite3.OperationalError as exc:
            logger.warning("FTS query failed (%s); falling back to LIKE", exc)
            return self._search_like(query, limit)
        return [SearchResult(**dict(row)) for row in rows]

    def _search_like(self, query: str, limit: int) -> list[SearchResult]:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%") + "%"
        rows = self._db.query_all(
            "SELECT m.id AS message_id, m.conversation_id, m.role, m.created_at, "
            "m.content AS snippet, COALESCE(c.title, '') AS conversation_title "
            "FROM messages m LEFT JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.content LIKE ? ESCAPE '\\' ORDER BY m.id DESC LIMIT ?",
            (pattern, limit),
        )
        return [SearchResult(**dict(row)) for row in rows]

    # -- task outcomes ---------------------------------------------------

    def record_task_outcome(
        self,
        task_type: str,
        status: str,
        detail: str = "",
        conversation_id: int | None = None,
    ) -> int:
        cursor = self._db.execute(
            "INSERT INTO task_outcomes (conversation_id, task_type, status, detail) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, task_type, status, detail),
        )
        return int(cursor.lastrowid)

    def list_task_outcomes(self, limit: int = 50) -> list[TaskOutcome]:
        rows = self._db.query_all(
            "SELECT id, conversation_id, task_type, status, detail, created_at "
            "FROM task_outcomes ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [TaskOutcome(**dict(row)) for row in rows]

    # -- deletion --------------------------------------------------------

    def delete_conversation(self, conversation_id: int) -> bool:
        """Delete a conversation and its messages (task outcome links are
        nulled, not lost). Returns True when a conversation was removed."""
        cursor = self._db.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("deleted conversation %d", conversation_id)
        return deleted

    def purge_all(self) -> None:
        """Erase all conversations, messages, and task outcomes."""
        self._db.execute("DELETE FROM messages")
        self._db.execute("DELETE FROM task_outcomes")
        self._db.execute("DELETE FROM conversations")
        logger.warning("all memory purged at user request")
