"""Tests for SQLite memory: persistence, search, backup, export, deletion."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from memory.backup import create_backup, export_json
from memory.conversation_store import ConversationStore, fts5_available
from memory.database import MemoryDatabase


def _fresh_store(tmp_path: Path, name: str = "jarvis.db", use_fts: bool | None = None):
    return ConversationStore(MemoryDatabase(tmp_path / name), use_fts=use_fts)


def _seed(store: ConversationStore) -> int:
    conv = store.create_conversation("Test chat")
    store.add_message(conv, "user", "What is the launch code?")
    store.add_message(
        conv, "assistant", "The launch code is red-42.", provider="primary", model="m"
    )
    return conv


@pytest.mark.unit
class TestPersistence:
    def test_database_file_created(self, tmp_path: Path) -> None:
        db = MemoryDatabase(tmp_path / "jarvis.db")
        assert db.path.exists()

    def test_persists_across_reopen(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path, "persist.db")
        conv = _seed(store)

        reopened = _fresh_store(tmp_path, "persist.db")
        conversations = reopened.list_conversations()
        assert len(conversations) == 1
        assert conversations[0]["title"] == "Test chat"
        messages = reopened.get_messages(conv)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[1].provider == "primary"
        assert messages[1].content == "The launch code is red-42."

    def test_message_order_and_recent(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        conv = store.create_conversation()
        for index in range(5):
            store.add_message(conv, "user", f"message {index}")
        recent = store.recent_messages(conv, 2)
        assert [m.content for m in recent] == ["message 3", "message 4"]

    def test_conversation_updated_at_bumps(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        conv = store.create_conversation("t")
        before = store.list_conversations()[0]["updated_at"]
        store.add_message(conv, "user", "hi")
        after = store.list_conversations()[0]["updated_at"]
        assert after >= before


@pytest.mark.unit
class TestSearch:
    def test_fts_search_finds_message(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        _seed(store)
        results = store.search("launch code")
        assert len(results) == 2  # both user question and assistant answer match
        assert any("red-42" in r.snippet for r in results)
        assert all(r.conversation_title == "Test chat" for r in results)

    def test_fts_query_syntax_is_escaped(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        _seed(store)
        # FTS operators and quotes must not crash or inject syntax.
        assert isinstance(store.search('"launch" OR *'), list)
        assert isinstance(store.search("NOT AND NEAR"), list)

    def test_like_fallback_search(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path, use_fts=False)
        _seed(store)
        results = store.search("launch code")
        assert len(results) == 2
        assert any("red-42" in r.snippet for r in results)

    def test_like_fallback_escapes_wildcards(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path, use_fts=False)
        conv = store.create_conversation()
        store.add_message(conv, "user", "100% done")
        assert len(store.search("100%")) == 1
        assert store.search("100x") == []

    def test_empty_query_returns_empty(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        _seed(store)
        assert store.search("") == []
        assert store.search("   ") == []

    def test_no_results(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        _seed(store)
        assert store.search("zebra-unicorn-xyz") == []


@pytest.mark.unit
class TestTaskOutcomes:
    def test_record_and_list(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        store.record_task_outcome("chat", "failed", "all providers down")
        outcomes = store.list_task_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0].task_type == "chat"
        assert outcomes[0].status == "failed"

    def test_outcomes_survive_reopen(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path, "outcomes.db")
        store.record_task_outcome("chat", "success", "ok")
        reopened = _fresh_store(tmp_path, "outcomes.db")
        assert len(reopened.list_task_outcomes()) == 1

    def test_invalid_status_rejected(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        with pytest.raises(sqlite3.IntegrityError):
            store.record_task_outcome("chat", "bogus", "")


@pytest.mark.unit
class TestBackupExportDeletion:
    def test_backup_creates_independent_copy(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        conv = _seed(store)
        backup_path = create_backup(store, tmp_path / "backups")
        assert backup_path.exists()

        backup_store = ConversationStore(MemoryDatabase(backup_path))
        assert len(backup_store.get_messages(conv)) == 2

    def test_export_json_structure(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        _seed(store)
        export_path = export_json(store, tmp_path / "exports" / "memory.json")
        data = json.loads(export_path.read_text(encoding="utf-8"))
        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["title"] == "Test chat"
        assert data["conversations"][0]["messages"][1]["provider"] == "primary"

    def test_delete_conversation_removes_messages(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        conv = _seed(store)
        assert store.delete_conversation(conv) is True
        assert store.get_messages(conv) == []
        assert store.list_conversations() == []
        assert store.delete_conversation(conv) is False

    def test_delete_keeps_fts_consistent(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        conv = _seed(store)
        store.delete_conversation(conv)
        assert store.search("launch code") == []

    def test_purge_all_clears_everything(self, tmp_path: Path) -> None:
        store = _fresh_store(tmp_path)
        conv = _seed(store)
        store.record_task_outcome("chat", "success", "ok")
        store.purge_all()
        assert store.list_conversations() == []
        assert store.list_task_outcomes() == []
        assert store.search("launch") == []


@pytest.mark.unit
def test_fts5_availability_probe() -> None:
    assert isinstance(fts5_available(), bool)
