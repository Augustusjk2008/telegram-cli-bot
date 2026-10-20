"""Durable update claims; chat text and history live in the shared chat store."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

CONFIRM_TTL = 5 * 60
REPLY_TTL = 30 * 60
NAVIGATION_TTL = 24 * 60 * 60


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
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS selected_targets (
                    bot_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    alias TEXT NOT NULL,
                    PRIMARY KEY (bot_id, user_id, chat_id)
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    bot_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    conversation_id TEXT,
                    control TEXT NOT NULL DEFAULT '{}',
                    message_id INTEGER,
                    expires_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (bot_id, token)
                )
            """)
            self._db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS interaction_reply
                ON interactions (bot_id, chat_id, message_id) WHERE message_id IS NOT NULL
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

    def select_target(self, user_id: int, chat_id: int, alias: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO selected_targets VALUES (?, ?, ?, ?) "
                "ON CONFLICT(bot_id, user_id, chat_id) DO UPDATE SET alias = excluded.alias",
                (self.bot_id, user_id, chat_id, alias),
            )

    def selected_target(self, user_id: int, chat_id: int) -> str | None:
        row = self._db.execute(
            "SELECT alias FROM selected_targets WHERE bot_id = ? AND user_id = ? AND chat_id = ?",
            (self.bot_id, user_id, chat_id),
        ).fetchone()
        return row[0] if row else None

    def new_interaction(
        self, action: str, user_id: int, chat_id: int, alias: str,
        conversation_id: str | None, *, ttl: int = NAVIGATION_TTL,
        control: dict[str, Any] | None = None,
    ) -> str:
        token = secrets.token_urlsafe(18)
        with self._db:
            self._db.execute(
                "INSERT INTO interactions "
                "(bot_id, token, user_id, chat_id, action, alias, conversation_id, control, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.bot_id, token, user_id, chat_id, action, alias, conversation_id,
                 json.dumps(control or {}, ensure_ascii=False), time.time() + ttl),
            )
        return token

    @staticmethod
    def _interaction(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        record = dict(row)
        record["control"] = json.loads(record["control"])
        return record

    def get_interaction(self, token: str) -> dict[str, Any] | None:
        return self._interaction(self._db.execute(
            "SELECT * FROM interactions WHERE bot_id = ? AND token = ?", (self.bot_id, token),
        ).fetchone())

    def get_reply(self, chat_id: int, message_id: int) -> dict[str, Any] | None:
        return self._interaction(self._db.execute(
            "SELECT * FROM interactions WHERE bot_id = ? AND chat_id = ? AND message_id = ?",
            (self.bot_id, chat_id, message_id),
        ).fetchone())

    def bind_reply(self, token: str, message_id: int) -> None:
        with self._db:
            self._db.execute(
                "UPDATE interactions SET message_id = ? WHERE bot_id = ? AND token = ? AND action = 'reply'",
                (message_id, self.bot_id, token),
            )

    def claim_interaction(self, token: str, user_id: int, chat_id: int) -> bool:
        with self._db:
            cursor = self._db.execute(
                "UPDATE interactions SET status = 'processing' "
                "WHERE bot_id = ? AND token = ? AND user_id = ? AND chat_id = ? "
                "AND status = 'pending' AND expires_at > ?",
                (self.bot_id, token, user_id, chat_id, time.time()),
            )
        return cursor.rowcount == 1

    def finish_interaction(self, token: str, result: str, *, status: str = "completed") -> None:
        with self._db:
            self._db.execute(
                "UPDATE interactions SET status = ?, result = ? WHERE bot_id = ? AND token = ?",
                (status, result, self.bot_id, token),
            )

    def close(self) -> None:
        self._db.close()
