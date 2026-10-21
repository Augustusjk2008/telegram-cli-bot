"""Durable update claims; chat text and history live in the shared chat store."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence

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
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, token)
                )
            """)
            interaction_columns = {
                str(row[1]) for row in self._db.execute("PRAGMA table_info(interactions)").fetchall()
            }
            if "updated_at" not in interaction_columns:
                self._db.execute("ALTER TABLE interactions ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
                self._db.execute(
                    "UPDATE interactions SET updated_at = CURRENT_TIMESTAMP WHERE updated_at = ''"
                )
            self._db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS interaction_reply
                ON interactions (bot_id, chat_id, message_id) WHERE message_id IS NOT NULL
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    bot_id TEXT NOT NULL,
                    delivery_id TEXT NOT NULL,
                    update_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    alias TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    assistant_message_id TEXT NOT NULL DEFAULT '',
                    parts_json TEXT NOT NULL,
                    reply_markup_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_at REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, delivery_id),
                    UNIQUE (bot_id, update_id)
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS delivery_parts (
                    bot_id TEXT NOT NULL,
                    delivery_id TEXT NOT NULL,
                    part_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    message_id INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, delivery_id, part_index),
                    FOREIGN KEY (bot_id, delivery_id)
                        REFERENCES deliveries (bot_id, delivery_id)
                        ON DELETE CASCADE
                )
            """)
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS deliveries_recovery "
                "ON deliveries (bot_id, status, retry_at, created_at)"
            )
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS telegram_bindings (
                    bot_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    shared_user_id INTEGER NOT NULL,
                    alias TEXT NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT 'main',
                    conversation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, chat_id, alias, agent_id)
                )
            """)
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS telegram_bindings_lookup "
                "ON telegram_bindings (bot_id, alias, agent_id, conversation_id)"
            )
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS completion_notifications (
                    bot_id TEXT NOT NULL,
                    notification_key TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL DEFAULT 0,
                    shared_user_id INTEGER NOT NULL DEFAULT 0,
                    alias TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT 'main',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    assistant_message_id TEXT NOT NULL DEFAULT '',
                    parts_json TEXT NOT NULL,
                    reply_markup_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_at REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, notification_key),
                    UNIQUE (bot_id, turn_id, chat_id)
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS completion_notification_parts (
                    bot_id TEXT NOT NULL,
                    notification_key TEXT NOT NULL,
                    part_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    message_id INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bot_id, notification_key, part_index),
                    FOREIGN KEY (bot_id, notification_key)
                        REFERENCES completion_notifications (bot_id, notification_key)
                        ON DELETE CASCADE
                )
            """)
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS completion_notifications_recovery "
                "ON completion_notifications (bot_id, status, retry_at, created_at)"
            )

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
            # A duplicate update must not move a high-water mark backwards. A
            # newly claimed lower ID is kept as a Telegram reset epoch, which
            # preserves recovery after Telegram recreates its update sequence.
            if cursor.rowcount == 1:
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

    @staticmethod
    def _decode_delivery(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        record = dict(row)
        record["parts"] = json.loads(record.pop("parts_json"))
        markup = record.pop("reply_markup_json")
        record["reply_markup"] = json.loads(markup) if markup else None
        return record

    @staticmethod
    def _validate_parts(parts: Sequence[str]) -> list[str]:
        values = list(parts)
        if not values or any(not isinstance(part, str) or not part for part in values):
            raise ValueError("A delivery must contain at least one non-empty text part")
        return values

    def create_delivery(
        self,
        update_id: int,
        chat_id: int,
        alias: str,
        parts: Sequence[str],
        *,
        conversation_id: str | None = None,
        turn_id: str | None = None,
        assistant_message_id: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        retry_at: float | None = None,
        delivery_id: str | None = None,
    ) -> str:
        """Persist a result before its first Telegram send attempt.

        The update ID is the idempotency key for a result. Recreating an existing
        result returns the original delivery ID and leaves its sent parts intact.
        """
        values = self._validate_parts(parts)
        existing = self._db.execute(
            "SELECT delivery_id FROM deliveries WHERE bot_id = ? AND update_id = ?",
            (self.bot_id, update_id),
        ).fetchone()
        if existing is not None:
            return str(existing[0])

        identifier = delivery_id or secrets.token_urlsafe(18)
        due = time.time() if retry_at is None else float(retry_at)
        markup = json.dumps(reply_markup, ensure_ascii=False) if reply_markup is not None else None
        with self._db:
            try:
                self._db.execute(
                    "INSERT INTO deliveries "
                    "(bot_id, delivery_id, update_id, chat_id, alias, conversation_id, "
                    "turn_id, assistant_message_id, parts_json, reply_markup_json, retry_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.bot_id, identifier, update_id, chat_id, alias,
                        conversation_id or "", turn_id or "", assistant_message_id or "",
                        json.dumps(values, ensure_ascii=False), markup, due,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = self._db.execute(
                    "SELECT delivery_id FROM deliveries WHERE bot_id = ? AND update_id = ?",
                    (self.bot_id, update_id),
                ).fetchone()
                if existing is None:
                    raise
                return str(existing[0])
            self._db.executemany(
                "INSERT INTO delivery_parts (bot_id, delivery_id, part_index, text, retry_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [(self.bot_id, identifier, index, part, due) for index, part in enumerate(values)],
            )
            self._sync_update_delivery_status(identifier)
        return identifier

    def create_pending_delivery(self, *args: Any, **kwargs: Any) -> str:
        return self.create_delivery(*args, **kwargs)

    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        record = self._decode_delivery(self._db.execute(
            "SELECT * FROM deliveries WHERE bot_id = ? AND delivery_id = ?",
            (self.bot_id, delivery_id),
        ).fetchone())
        if record is not None:
            record["part_records"] = self.get_delivery_parts(delivery_id)
        return record

    def get_delivery_for_update(self, update_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM deliveries WHERE bot_id = ? AND update_id = ?",
            (self.bot_id, update_id),
        ).fetchone()
        return self.get_delivery(row["delivery_id"]) if row is not None else None

    def get_delivery_parts(self, delivery_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM delivery_parts WHERE bot_id = ? AND delivery_id = ? "
            "ORDER BY part_index",
            (self.bot_id, delivery_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_deliveries(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Return due, incomplete results for a post-restart delivery worker."""
        current = time.time() if now is None else float(now)
        rows = self._db.execute(
            "SELECT * FROM deliveries WHERE bot_id = ? AND status != 'sent' "
            "AND retry_at <= ? ORDER BY created_at, delivery_id",
            (self.bot_id, current),
        ).fetchall()
        return [self.get_delivery(row["delivery_id"]) for row in rows]

    def pending_deliveries(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Compatibility-friendly alias for restart recovery callers."""
        return self.list_pending_deliveries(now=now)

    def recover_pending_deliveries(self, *, now: float | None = None) -> list[dict[str, Any]]:
        return self.list_pending_deliveries(now=now)

    def delivery_parts(self, delivery_id: str) -> list[dict[str, Any]]:
        return self.get_delivery_parts(delivery_id)

    def recover_after_restart(self) -> list[dict[str, Any]]:
        """Close in-flight local records without replaying agent side effects.

        A completed delivery remains eligible for Telegram retry. An update
        without such a delivery has an execution outcome that cannot be known
        after a process crash, so it is marked interrupted for Web inspection.
        Callback operations left in ``processing`` are similarly made explicit
        instead of being retried blindly.
        """
        recovered: list[dict[str, Any]] = []
        with self._db:
            rows = self._db.execute(
                "SELECT * FROM updates WHERE bot_id = ? AND status IN ('received', 'running') "
                "ORDER BY update_id",
                (self.bot_id,),
            ).fetchall()
            for row in rows:
                delivery = self._db.execute(
                    "SELECT status FROM deliveries WHERE bot_id = ? AND update_id = ?",
                    (self.bot_id, row["update_id"]),
                ).fetchone()
                status = "completed" if delivery is not None else "interrupted"
                self._db.execute(
                    "UPDATE updates SET status = ?, delivery_status = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE bot_id = ? AND update_id = ?",
                    (status, delivery["status"] if delivery is not None else "", self.bot_id, row["update_id"]),
                )
                recovered.append({**dict(row), "status": status, "delivery_status": delivery["status"] if delivery is not None else ""})
            self._db.execute(
                "UPDATE interactions SET status = 'failed', result = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE bot_id = ? AND status = 'processing'",
                ("应用重启前操作未完成，请刷新面板后重试。", self.bot_id),
            )
        return recovered

    def mark_delivery_part_sent(self, delivery_id: str, part_index: int, message_id: int) -> None:
        """Record one Telegram message ID without changing an already sent part."""
        with self._db:
            part = self._db.execute(
                "SELECT status, message_id FROM delivery_parts "
                "WHERE bot_id = ? AND delivery_id = ? AND part_index = ?",
                (self.bot_id, delivery_id, part_index),
            ).fetchone()
            if part is None:
                raise KeyError(f"Unknown delivery part: {delivery_id}/{part_index}")
            if part["status"] != "sent":
                self._db.execute(
                    "UPDATE delivery_parts SET status = 'sent', message_id = ?, "
                    "attempts = attempts + 1, last_error = '', updated_at = CURRENT_TIMESTAMP "
                    "WHERE bot_id = ? AND delivery_id = ? AND part_index = ?",
                    (message_id, self.bot_id, delivery_id, part_index),
                )
            self._refresh_delivery_status(delivery_id)

    def mark_part_sent(self, delivery_id: str, part_index: int, message_id: int) -> None:
        self.mark_delivery_part_sent(delivery_id, part_index, message_id)

    def mark_delivery_part_failed(
        self,
        delivery_id: str,
        part_index: int,
        error: str = "",
        *,
        retry_at: float | None = None,
    ) -> None:
        """Record a failed attempt while keeping successfully sent parts durable."""
        due = time.time() if retry_at is None else float(retry_at)
        with self._db:
            part = self._db.execute(
                "SELECT status FROM delivery_parts WHERE bot_id = ? AND delivery_id = ? "
                "AND part_index = ?",
                (self.bot_id, delivery_id, part_index),
            ).fetchone()
            if part is None:
                raise KeyError(f"Unknown delivery part: {delivery_id}/{part_index}")
            if part["status"] != "sent":
                self._db.execute(
                    "UPDATE delivery_parts SET status = 'failed', retry_at = ?, "
                    "attempts = attempts + 1, last_error = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE bot_id = ? AND delivery_id = ? AND part_index = ?",
                    (due, str(error), self.bot_id, delivery_id, part_index),
                )
            self._refresh_delivery_status(delivery_id)

    def mark_part_failed(
        self, delivery_id: str, part_index: int, error: str = "", *, retry_at: float | None = None,
    ) -> None:
        self.mark_delivery_part_failed(delivery_id, part_index, error, retry_at=retry_at)

    def mark_delivery_failed(self, delivery_id: str, error: str = "", *, retry_at: float | None = None) -> None:
        """Record a delivery-level failure for results with no part-level attempt."""
        due = time.time() if retry_at is None else float(retry_at)
        with self._db:
            if self._db.execute(
                "SELECT 1 FROM deliveries WHERE bot_id = ? AND delivery_id = ?",
                (self.bot_id, delivery_id),
            ).fetchone() is None:
                raise KeyError(f"Unknown delivery: {delivery_id}")
            self._db.execute(
                "UPDATE deliveries SET status = 'failed', retry_at = ?, last_error = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND delivery_id = ? "
                "AND status != 'sent'",
                (due, str(error), self.bot_id, delivery_id),
            )
            self._sync_update_delivery_status(delivery_id)

    def _refresh_delivery_status(self, delivery_id: str) -> None:
        parts = self._db.execute(
            "SELECT status FROM delivery_parts WHERE bot_id = ? AND delivery_id = ?",
            (self.bot_id, delivery_id),
        ).fetchall()
        statuses = [row[0] for row in parts]
        if not statuses:
            return
        if all(status == "sent" for status in statuses):
            status = "sent"
        elif any(status == "sent" for status in statuses):
            status = "partial"
        elif any(status == "failed" for status in statuses):
            status = "failed"
        else:
            status = "pending"
        retry_row = self._db.execute(
            "SELECT retry_at, last_error FROM delivery_parts WHERE bot_id = ? AND delivery_id = ? "
            "AND status != 'sent' ORDER BY part_index LIMIT 1",
            (self.bot_id, delivery_id),
        ).fetchone()
        retry_at = retry_row[0] if retry_row and retry_row[0] is not None else time.time()
        last_error = retry_row[1] if retry_row else ""
        self._db.execute(
            "UPDATE deliveries SET status = ?, retry_at = ?, last_error = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE bot_id = ? AND delivery_id = ? AND status != 'sent'",
            (status, retry_at, last_error, self.bot_id, delivery_id),
        )
        self._sync_update_delivery_status(delivery_id)

    def _sync_update_delivery_status(self, delivery_id: str) -> None:
        row = self._db.execute(
            "SELECT update_id, status FROM deliveries WHERE bot_id = ? AND delivery_id = ?",
            (self.bot_id, delivery_id),
        ).fetchone()
        if row is not None:
            self._db.execute(
                "UPDATE updates SET delivery_status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE bot_id = ? AND update_id = ?",
                (row["status"], self.bot_id, row["update_id"]),
            )

    def bind_conversation(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        shared_user_id: int,
        alias: str,
        agent_id: str = "main",
        conversation_id: str,
    ) -> None:
        """Bind one Telegram private chat to one shared conversation.

        A chat has one current binding per Bot alias and agent. Updating it on
        an explicit Telegram panel/message action removes the old conversation
        from the recipient lookup, so delayed Web replies cannot follow a Web
        session switch automatically.
        """
        normalized_alias = str(alias or "").strip().lower()
        normalized_agent = str(agent_id or "main").strip() or "main"
        normalized_conversation = str(conversation_id or "").strip()
        if not normalized_alias or not normalized_conversation:
            return
        with self._db:
            self._db.execute(
                "INSERT INTO telegram_bindings "
                "(bot_id, chat_id, telegram_user_id, shared_user_id, alias, agent_id, conversation_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(bot_id, chat_id, alias, agent_id) DO UPDATE SET "
                "telegram_user_id = excluded.telegram_user_id, "
                "shared_user_id = excluded.shared_user_id, "
                "conversation_id = excluded.conversation_id, "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    self.bot_id,
                    int(chat_id),
                    int(telegram_user_id),
                    int(shared_user_id),
                    normalized_alias,
                    normalized_agent,
                    normalized_conversation,
                ),
            )

    def list_bound_chats(
        self,
        alias: str,
        agent_id: str = "main",
        conversation_id: str = "",
    ) -> list[dict[str, Any]]:
        normalized_alias = str(alias or "").strip().lower()
        normalized_agent = str(agent_id or "main").strip() or "main"
        normalized_conversation = str(conversation_id or "").strip()
        if not normalized_alias or not normalized_conversation:
            return []
        rows = self._db.execute(
            "SELECT * FROM telegram_bindings "
            "WHERE bot_id = ? AND alias = ? AND agent_id = ? AND conversation_id = ? "
            "ORDER BY chat_id",
            (self.bot_id, normalized_alias, normalized_agent, normalized_conversation),
        ).fetchall()
        return [dict(row) for row in rows]

    def is_conversation_bound(
        self,
        alias: str,
        agent_id: str = "main",
        conversation_id: str = "",
        *,
        chat_id: int | None = None,
    ) -> bool:
        normalized_alias = str(alias or "").strip().lower()
        normalized_agent = str(agent_id or "main").strip() or "main"
        normalized_conversation = str(conversation_id or "").strip()
        if not normalized_alias or not normalized_conversation:
            return False
        query = (
            "SELECT 1 FROM telegram_bindings "
            "WHERE bot_id = ? AND alias = ? AND agent_id = ? AND conversation_id = ?"
        )
        params: list[Any] = [self.bot_id, normalized_alias, normalized_agent, normalized_conversation]
        if chat_id is not None:
            query += " AND chat_id = ?"
            params.append(int(chat_id))
        query += " LIMIT 1"
        return self._db.execute(query, params).fetchone() is not None

    @staticmethod
    def _decode_completion_notification(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        record = dict(row)
        record["parts"] = json.loads(record.pop("parts_json"))
        markup = record.pop("reply_markup_json")
        record["reply_markup"] = json.loads(markup) if markup else None
        return record

    def create_completion_notification(
        self,
        notification_key: str,
        chat_id: int,
        alias: str,
        parts: Sequence[str],
        *,
        telegram_user_id: int = 0,
        shared_user_id: int = 0,
        agent_id: str = "main",
        conversation_id: str | None = None,
        turn_id: str | None = None,
        assistant_message_id: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        retry_at: float | None = None,
    ) -> str:
        """Persist one final-reply notification using a stable recipient key."""
        key = str(notification_key or "").strip()
        if not key:
            raise ValueError("A completion notification requires a notification key")
        values = self._validate_parts(parts)
        existing = self._db.execute(
            "SELECT notification_key FROM completion_notifications "
            "WHERE bot_id = ? AND notification_key = ?",
            (self.bot_id, key),
        ).fetchone()
        if existing is not None:
            return str(existing[0])

        due = time.time() if retry_at is None else float(retry_at)
        markup = json.dumps(reply_markup, ensure_ascii=False) if reply_markup is not None else None
        normalized_agent = str(agent_id or "main").strip() or "main"
        normalized_alias = str(alias or "").strip().lower()
        normalized_conversation = str(conversation_id or "")
        normalized_turn = str(turn_id or "")
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO completion_notifications "
                    "(bot_id, notification_key, chat_id, telegram_user_id, shared_user_id, alias, agent_id, "
                    "conversation_id, turn_id, assistant_message_id, parts_json, reply_markup_json, retry_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ",
                    (
                        self.bot_id,
                        key,
                        int(chat_id),
                        int(telegram_user_id),
                        int(shared_user_id),
                        normalized_alias,
                        normalized_agent,
                        normalized_conversation,
                        normalized_turn,
                        str(assistant_message_id or ""),
                        json.dumps(values, ensure_ascii=False),
                        markup,
                        due,
                    ),
                )
                self._db.executemany(
                    "INSERT INTO completion_notification_parts "
                    "(bot_id, notification_key, part_index, text, retry_at) VALUES (?, ?, ?, ?, ?)",
                    [(self.bot_id, key, index, part, due) for index, part in enumerate(values)],
                )
        except sqlite3.IntegrityError:
            existing = self._db.execute(
                "SELECT notification_key FROM completion_notifications "
                "WHERE bot_id = ? AND notification_key = ?",
                (self.bot_id, key),
            ).fetchone()
            if existing is None and normalized_turn:
                existing = self._db.execute(
                    "SELECT notification_key FROM completion_notifications "
                    "WHERE bot_id = ? AND turn_id = ? AND chat_id = ?",
                    (self.bot_id, normalized_turn, int(chat_id)),
                ).fetchone()
            if existing is None:
                raise
            return str(existing[0])
        return key

    def create_notification(self, *args: Any, **kwargs: Any) -> str:
        return self.create_completion_notification(*args, **kwargs)

    def create_pending_notification(self, *args: Any, **kwargs: Any) -> str:
        return self.create_completion_notification(*args, **kwargs)

    def get_completion_notification(self, notification_key: str) -> dict[str, Any] | None:
        record = self._decode_completion_notification(self._db.execute(
            "SELECT * FROM completion_notifications WHERE bot_id = ? AND notification_key = ?",
            (self.bot_id, str(notification_key)),
        ).fetchone())
        if record is not None:
            record["part_records"] = self.get_completion_notification_parts(notification_key)
        return record

    def get_notification(self, notification_key: str) -> dict[str, Any] | None:
        return self.get_completion_notification(notification_key)

    def get_completion_notification_parts(self, notification_key: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM completion_notification_parts "
            "WHERE bot_id = ? AND notification_key = ? ORDER BY part_index",
            (self.bot_id, str(notification_key)),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_notification_parts(self, notification_key: str) -> list[dict[str, Any]]:
        return self.get_completion_notification_parts(notification_key)

    def list_pending_completion_notifications(self, *, now: float | None = None) -> list[dict[str, Any]]:
        current = time.time() if now is None else float(now)
        rows = self._db.execute(
            "SELECT * FROM completion_notifications WHERE bot_id = ? AND status != 'sent' "
            "AND retry_at <= ? ORDER BY created_at, notification_key",
            (self.bot_id, current),
        ).fetchall()
        return [self.get_completion_notification(row["notification_key"]) for row in rows]

    def list_incomplete_completion_notifications(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM completion_notifications WHERE bot_id = ? AND status != 'sent' "
            "ORDER BY created_at, notification_key",
            (self.bot_id,),
        ).fetchall()
        return [self.get_completion_notification(row["notification_key"]) for row in rows]

    def incomplete_notifications(self) -> list[dict[str, Any]]:
        return self.list_incomplete_completion_notifications()

    def pending_notifications(self, *, now: float | None = None) -> list[dict[str, Any]]:
        return self.list_pending_completion_notifications(now=now)

    def recover_pending_notifications(self, *, now: float | None = None) -> list[dict[str, Any]]:
        return self.list_pending_completion_notifications(now=now)

    def mark_completion_notification_part_sent(
        self, notification_key: str, part_index: int, message_id: int,
    ) -> None:
        with self._db:
            part = self._db.execute(
                "SELECT status FROM completion_notification_parts "
                "WHERE bot_id = ? AND notification_key = ? AND part_index = ?",
                (self.bot_id, str(notification_key), int(part_index)),
            ).fetchone()
            if part is None:
                raise KeyError(f"Unknown completion notification part: {notification_key}/{part_index}")
            if part["status"] != "sent":
                self._db.execute(
                    "UPDATE completion_notification_parts SET status = 'sent', message_id = ?, "
                    "attempts = attempts + 1, last_error = '', updated_at = CURRENT_TIMESTAMP "
                    "WHERE bot_id = ? AND notification_key = ? AND part_index = ?",
                    (int(message_id), self.bot_id, str(notification_key), int(part_index)),
                )
            self._refresh_completion_notification_status(str(notification_key))

    def mark_notification_part_sent(self, *args: Any, **kwargs: Any) -> None:
        self.mark_completion_notification_part_sent(*args, **kwargs)

    def mark_completion_notification_part_failed(
        self,
        notification_key: str,
        part_index: int,
        error: str = "",
        *,
        retry_at: float | None = None,
    ) -> None:
        due = time.time() if retry_at is None else float(retry_at)
        with self._db:
            part = self._db.execute(
                "SELECT status FROM completion_notification_parts "
                "WHERE bot_id = ? AND notification_key = ? AND part_index = ?",
                (self.bot_id, str(notification_key), int(part_index)),
            ).fetchone()
            if part is None:
                raise KeyError(f"Unknown completion notification part: {notification_key}/{part_index}")
            if part["status"] != "sent":
                self._db.execute(
                    "UPDATE completion_notification_parts SET status = 'failed', retry_at = ?, "
                    "attempts = attempts + 1, last_error = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE bot_id = ? AND notification_key = ? AND part_index = ?",
                    (due, str(error), self.bot_id, str(notification_key), int(part_index)),
                )
                self._db.execute(
                    "UPDATE completion_notifications SET attempts = attempts + 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND notification_key = ?",
                    (self.bot_id, str(notification_key)),
                )
            self._refresh_completion_notification_status(str(notification_key))

    def mark_notification_part_failed(self, *args: Any, **kwargs: Any) -> None:
        self.mark_completion_notification_part_failed(*args, **kwargs)

    def _refresh_completion_notification_status(self, notification_key: str) -> None:
        parts = self._db.execute(
            "SELECT status FROM completion_notification_parts "
            "WHERE bot_id = ? AND notification_key = ?",
            (self.bot_id, str(notification_key)),
        ).fetchall()
        statuses = [row[0] for row in parts]
        if not statuses:
            return
        if all(status == "sent" for status in statuses):
            status = "sent"
        elif any(status == "sent" for status in statuses):
            status = "partial"
        elif any(status == "failed" for status in statuses):
            status = "failed"
        else:
            status = "pending"
        retry_row = self._db.execute(
            "SELECT retry_at, last_error FROM completion_notification_parts "
            "WHERE bot_id = ? AND notification_key = ? AND status != 'sent' "
            "ORDER BY part_index LIMIT 1",
            (self.bot_id, str(notification_key)),
        ).fetchone()
        retry_at = retry_row[0] if retry_row and retry_row[0] is not None else time.time()
        last_error = retry_row[1] if retry_row else ""
        self._db.execute(
            "UPDATE completion_notifications SET status = ?, retry_at = ?, last_error = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE bot_id = ? AND notification_key = ? "
            "AND status != 'sent'",
            (status, retry_at, last_error, self.bot_id, str(notification_key)),
        )

    def mark_completion_notification_failed(
        self, notification_key: str, error: str = "", *, retry_at: float | None = None,
    ) -> None:
        due = time.time() if retry_at is None else float(retry_at)
        with self._db:
            if self._db.execute(
                "SELECT 1 FROM completion_notifications WHERE bot_id = ? AND notification_key = ?",
                (self.bot_id, str(notification_key)),
            ).fetchone() is None:
                raise KeyError(f"Unknown completion notification: {notification_key}")
            self._db.execute(
                "UPDATE completion_notifications SET status = 'failed', retry_at = ?, last_error = ?, "
                "attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE bot_id = ? AND notification_key = ? AND status != 'sent'",
                (due, str(error), self.bot_id, str(notification_key)),
            )

    def mark_notification_failed(self, *args: Any, **kwargs: Any) -> None:
        self.mark_completion_notification_failed(*args, **kwargs)

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
                ", updated_at = CURRENT_TIMESTAMP "
                "WHERE bot_id = ? AND token = ? AND user_id = ? AND chat_id = ? "
                "AND status = 'pending' AND expires_at > ?",
                (self.bot_id, token, user_id, chat_id, time.time()),
            )
        return cursor.rowcount == 1

    def finish_interaction(self, token: str, result: str, *, status: str = "completed") -> None:
        with self._db:
            self._db.execute(
                "UPDATE interactions SET status = ?, result = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE bot_id = ? AND token = ?",
                (status, result, self.bot_id, token),
            )

    def close(self) -> None:
        self._db.close()
