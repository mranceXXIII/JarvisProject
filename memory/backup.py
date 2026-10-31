"""Backup and export controls for JARVIS memory (Phase 3, spec section 13).

- ``create_backup``: consistent SQLite backup into a timestamped file.
- ``export_json``: human-readable export of conversations and messages.
- Deletion controls (delete one conversation / purge all) live on
  :class:`~memory.conversation_store.ConversationStore`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from memory.conversation_store import ConversationStore

logger = logging.getLogger("jarvis.memory.backup")

DEFAULT_BACKUP_DIR = "data/backups"
DEFAULT_EXPORT_DIR = "data/exports"


def create_backup(store: ConversationStore, backup_dir: Path | str) -> Path:
    """Create a timestamped backup of the memory database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = Path(backup_dir) / f"jarvis_memory_{timestamp}.db"
    return store._db.backup_to(target)  # noqa: SLF001 - same package boundary


def export_json(store: ConversationStore, export_path: Path | str) -> Path:
    """Export every conversation with its messages to a JSON file."""
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "conversations": [],
    }
    for conversation in store.list_conversations(limit=10_000):
        messages = store.get_messages(conversation["id"])
        payload["conversations"].append(
            {
                "id": conversation["id"],
                "title": conversation["title"],
                "created_at": conversation["created_at"],
                "updated_at": conversation["updated_at"],
                "messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "provider": message.provider,
                        "model": message.model,
                        "created_at": message.created_at,
                    }
                    for message in messages
                ],
            }
        )
    path = Path(export_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("memory exported to %s", path)
    return path
