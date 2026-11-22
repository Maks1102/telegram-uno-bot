"""Хранение истории диалогов в SQLite — переживает перезапуск бота."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class HistoryStore:
    """Реплики диалогов: user_id -> последовательность сообщений (user/assistant)."""

    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id, id)"
        )
        self._conn.commit()

    def load(self, user_id: int, limit: int) -> list[dict[str, str]]:
        """Последние реплики пользователя в хронологическом порядке."""
        if limit <= 0:
            return []
        rows = self._conn.execute(
            "SELECT role, content FROM messages "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        messages = [{"role": role, "content": content} for role, content in reversed(rows)]
        # история не должна начинаться с ответа ассистента
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def append(self, user_id: int, role: str, content: str, limit: int) -> None:
        """Добавляет реплику и подрезает историю до limit сообщений."""
        if limit <= 0:
            self.clear(user_id)
            return
        self._conn.execute(
            "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, time.time()),
        )
        self._conn.execute(
            "DELETE FROM messages WHERE user_id = ? AND id NOT IN "
            "(SELECT id FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?)",
            (user_id, user_id, limit),
        )
        self._conn.commit()

    def clear(self, user_id: int) -> None:
        """Удаляет всю историю пользователя."""
        self._conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
