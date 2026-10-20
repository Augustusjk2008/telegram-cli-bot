"""Durable update claims; chat text and history live in the shared chat store."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class TelegramState:
    def __init__(self, path: Path, bot_id: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.bot_id = bot_id
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS updates (
                    bot_id TEXT NOT NULL,
                    update_id INTEGER NOT NULL,
                    user_id INTEGER,
                    chat_id INTEGER,
                    alias TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'received',
                    delivery_status TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    assistant_message_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, update_id)
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS polling_cursors (
                    bot_id TEXT PRIMARY KEY,
                    next_offset INTEGER NOT NULL
                )
            """)

    def next_offset(self) -> int:
        row = self._db.execute(
            "SELECT next_offset FROM polling_cursors WHERE bot_id = ?",
            (self.bot_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def claim(self, update_id: int, *, user_id: int | None, chat_id: int | None) -> bool:
        with self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO updates (bot_id, update_id, user_id, chat_id) VALUES (?, ?, ?, ?)",
                (self.bot_id, update_id, user_id, chat_id),
            )
            # Telegram may choose a smaller ID after a week without updates.
            # Persist the last received position, independently of claim history.
            self._db.execute(
                "INSERT INTO polling_cursors (bot_id, next_offset) VALUES (?, ?) "
                "ON CONFLICT(bot_id) DO UPDATE SET next_offset = excluded.next_offset",
                (self.bot_id, update_id + 1),
            )
        return cursor.rowcount == 1

    def update(self, update_id: int, **fields: str) -> None:
        allowed = {"alias", "status", "delivery_status", "conversation_id", "turn_id", "assistant_message_id"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid Telegram state fields")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._db:
            self._db.execute(
                f"UPDATE updates SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND update_id = ?",
                (*fields.values(), self.bot_id, update_id),
            )

    def get(self, update_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM updates WHERE bot_id = ? AND update_id = ?", (self.bot_id, update_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def close(self) -> None:
        self._db.close()
