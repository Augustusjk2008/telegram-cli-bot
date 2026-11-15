"""Durable cursor, conversation binding and text-delivery state for Weixin."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence


def _now() -> float:
    return time.time()


class WeixinState:
    """SQLite state that deliberately excludes the account authentication token."""

    def __init__(self, path: Path | str, account_id: str = "") -> None:
        self.path = Path(path)
        self.account_id = str(account_id or "").strip()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS weixin_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS weixin_messages (
                    message_id TEXT PRIMARY KEY,
                    peer_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'received',
                    alias TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT 'main',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    assistant_message_id TEXT NOT NULL DEFAULT '',
                    delivery_status TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS weixin_messages_peer
                    ON weixin_messages (peer_id, created_at);
                CREATE TABLE IF NOT EXISTS weixin_peers (
                    peer_id TEXT PRIMARY KEY,
                    context_token TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS weixin_bindings (
                    peer_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT 'main',
                    conversation_id TEXT NOT NULL,
                    shared_user_id TEXT NOT NULL DEFAULT '',
                    actor_id TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (peer_id, alias, agent_id)
                );
                CREATE INDEX IF NOT EXISTS weixin_bindings_lookup
                    ON weixin_bindings (alias, agent_id, conversation_id);
                CREATE TABLE IF NOT EXISTS weixin_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    peer_id TEXT NOT NULL,
                    alias TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT 'main',
                    conversation_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    assistant_message_id TEXT NOT NULL DEFAULT '',
                    parts_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS weixin_deliveries_recovery
                    ON weixin_deliveries (status, retry_at, created_at);
                """
            )

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def _meta(self, key: str, default: str = "") -> str:
        row = self._db.execute("SELECT value FROM weixin_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"] if row is not None else default)

    def _set_meta(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT INTO weixin_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value or "")),
        )

    def get_updates_buf(self) -> str:
        with self._lock:
            return self._meta("get_updates_buf")

    def set_updates_buf(self, value: str) -> None:
        with self._lock, self._db:
            self._set_meta("get_updates_buf", str(value or ""))

    get_cursor = get_updates_buf
    set_cursor = set_updates_buf
    get_update_cursor = get_updates_buf
    set_update_cursor = set_updates_buf

    def set_gateway_status(self, status: str, *, detail: str = "") -> None:
        with self._lock, self._db:
            self._set_meta("gateway_status", str(status or ""))
            self._set_meta("gateway_detail", str(detail or ""))

    def gateway_status(self) -> dict[str, str]:
        with self._lock:
            return {
                "status": self._meta("gateway_status", "stopped"),
                "detail": self._meta("gateway_detail"),
            }

    def claim_message(self, message_id: Any, *, peer_id: str = "", status: str = "received") -> bool:
        key = str(message_id or "").strip()
        if not key:
            return False
        now = _now()
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO weixin_messages "
                "(message_id, peer_id, status, created_at, updated_at) VALUES(?,?,?,?,?)",
                (key, str(peer_id or ""), str(status or "received"), now, now),
            )
            return cursor.rowcount == 1

    def is_duplicate(self, message_id: Any) -> bool:
        key = str(message_id or "").strip()
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM weixin_messages WHERE message_id=?", (key,)
            ).fetchone()
            return row is not None

    def mark_processed(self, message_id: Any, *, status: str = "completed", **fields: Any) -> None:
        status = str(fields.pop("status", status) or status)
        self.update_message(message_id, status=status, **fields)

    def update_message(self, message_id: Any, **fields: Any) -> None:
        key = str(message_id or "").strip()
        allowed = {
            "peer_id", "status", "alias", "agent_id", "conversation_id",
            "turn_id", "assistant_message_id", "delivery_status",
        }
        changes = {name: value for name, value in fields.items() if name in allowed}
        if not key or not changes:
            return
        changes["updated_at"] = _now()
        assignments = ", ".join(f"{name}=?" for name in changes)
        with self._lock, self._db:
            self._db.execute(
                f"UPDATE weixin_messages SET {assignments} WHERE message_id=?",
                (*[str(value or "") for value in changes.values()], key),
            )

    def get_message(self, message_id: Any) -> dict[str, Any] | None:
        key = str(message_id or "").strip()
        with self._lock:
            row = self._db.execute("SELECT * FROM weixin_messages WHERE message_id=?", (key,)).fetchone()
            return dict(row) if row is not None else None

    def set_context_token(self, peer_id: str, context_token: str) -> None:
        peer = str(peer_id or "").strip()
        if not peer:
            return
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO weixin_peers(peer_id,context_token,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(peer_id) DO UPDATE SET context_token=excluded.context_token, updated_at=excluded.updated_at",
                (peer, str(context_token or ""), _now()),
            )

    save_context_token = set_context_token
    save_context = set_context_token

    def get_context_token(self, peer_id: str) -> str:
        peer = str(peer_id or "").strip()
        with self._lock:
            row = self._db.execute(
                "SELECT context_token FROM weixin_peers WHERE peer_id=?", (peer,)
            ).fetchone()
            return str(row["context_token"] if row is not None else "")

    load_context = get_context_token

    def bind_conversation(
        self,
        *,
        peer_id: str,
        alias: str,
        agent_id: str = "main",
        conversation_id: str,
        shared_user_id: Any = "",
        actor_id: str = "",
    ) -> None:
        peer = str(peer_id or "").strip()
        normalized_alias = str(alias or "").strip().lower()
        normalized_agent = str(agent_id or "main").strip().lower() or "main"
        conversation = str(conversation_id or "").strip()
        if not peer or not normalized_alias or not conversation:
            return
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO weixin_bindings "
                "(peer_id,alias,agent_id,conversation_id,shared_user_id,actor_id,updated_at) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(peer_id,alias,agent_id) DO UPDATE SET "
                "conversation_id=excluded.conversation_id, shared_user_id=excluded.shared_user_id, "
                "actor_id=excluded.actor_id, updated_at=excluded.updated_at",
                (peer, normalized_alias, normalized_agent, conversation,
                 str(shared_user_id or ""), str(actor_id or ""), _now()),
            )

    save_binding = bind_conversation
    save_conversation_binding = bind_conversation

    def get_binding(self, peer_id: str, alias: str | None = None, agent_id: str = "main") -> dict[str, Any] | None:
        peer = str(peer_id or "").strip()
        normalized_agent = str(agent_id or "main").strip().lower() or "main"
        with self._lock:
            if alias:
                row = self._db.execute(
                    "SELECT * FROM weixin_bindings WHERE peer_id=? AND alias=? AND agent_id=?",
                    (peer, str(alias).strip().lower(), normalized_agent),
                ).fetchone()
            else:
                row = self._db.execute(
                    "SELECT * FROM weixin_bindings WHERE peer_id=? AND agent_id=? "
                    "ORDER BY updated_at DESC LIMIT 1", (peer, normalized_agent),
                ).fetchone()
            return dict(row) if row is not None else None

    get_conversation_binding = get_binding

    def list_bindings(self, peer_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if peer_id is None:
                rows = self._db.execute("SELECT * FROM weixin_bindings ORDER BY updated_at DESC").fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM weixin_bindings WHERE peer_id=? ORDER BY updated_at DESC",
                    (str(peer_id or "").strip(),),
                ).fetchall()
            return [dict(row) for row in rows]

    def list_bound_peers(self, alias: str, agent_id: str, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM weixin_bindings WHERE alias=? AND agent_id=? AND conversation_id=? "
                "ORDER BY updated_at ASC",
                (str(alias or "").strip().lower(), str(agent_id or "main").strip().lower() or "main", str(conversation_id or "")),
            ).fetchall()
            return [dict(row) for row in rows]

    list_bound_chats = list_bound_peers

    @staticmethod
    def _normalize_parts(parts: Iterable[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(parts):
            if isinstance(item, dict):
                text = str(item.get("text") or "")
            else:
                text = str(item or "")
            if not text:
                continue
            normalized.append({"part_index": index, "text": text, "status": "pending", "attempts": 0, "retry_at": 0})
        return normalized

    def create_delivery(
        self,
        delivery_id: str | None = None,
        peer_id: str = "",
        parts: Sequence[Any] = (),
        *,
        alias: str = "",
        agent_id: str = "main",
        conversation_id: str = "",
        turn_id: str = "",
        assistant_message_id: str = "",
    ) -> str:
        identifier = str(delivery_id or uuid.uuid4().hex).strip() or uuid.uuid4().hex
        records = self._normalize_parts(parts)
        now = _now()
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO weixin_deliveries "
                "(delivery_id,peer_id,alias,agent_id,conversation_id,turn_id,assistant_message_id,parts_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (identifier, str(peer_id or "").strip(), str(alias or ""), str(agent_id or "main"),
                 str(conversation_id or ""), str(turn_id or ""), str(assistant_message_id or ""),
                 json.dumps(records, ensure_ascii=False), now, now),
            )
        return identifier

    def get_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM weixin_deliveries WHERE delivery_id=?", (str(delivery_id or ""),)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            try:
                result["part_records"] = json.loads(result.get("parts_json") or "[]")
            except (TypeError, ValueError):
                result["part_records"] = []
            return result

    def list_incomplete_deliveries(self, *, due_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT delivery_id FROM weixin_deliveries WHERE status != 'sent'"
        args: tuple[Any, ...] = ()
        if due_only:
            query += " AND retry_at <= ?"
            args = (_now(),)
        query += " ORDER BY created_at ASC"
        with self._lock:
            ids = [str(row["delivery_id"]) for row in self._db.execute(query, args).fetchall()]
        return [item for identifier in ids if (item := self.get_delivery(identifier)) is not None]

    def _update_delivery_parts(self, delivery_id: str, parts: list[dict[str, Any]], *, status: str, retry_at: float = 0.0, error: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE weixin_deliveries SET parts_json=?,status=?,retry_at=?,last_error=?,updated_at=? WHERE delivery_id=?",
                (json.dumps(parts, ensure_ascii=False), status, float(retry_at or 0), str(error or ""), _now(), str(delivery_id or "")),
            )

    def mark_delivery_part_sent(self, delivery_id: str, part_index: int) -> None:
        record = self.get_delivery(delivery_id)
        if record is None:
            return
        parts = record.get("part_records") or []
        for part in parts:
            if int(part.get("part_index", -1)) == int(part_index):
                part["status"] = "sent"
                part["retry_at"] = 0
        status = "sent" if parts and all(part.get("status") == "sent" for part in parts) else "pending"
        self._update_delivery_parts(delivery_id, parts, status=status, retry_at=0)

    def mark_delivery_part_failed(self, delivery_id: str, part_index: int, error: str, *, retry_at: float) -> None:
        record = self.get_delivery(delivery_id)
        if record is None:
            return
        parts = record.get("part_records") or []
        for part in parts:
            if int(part.get("part_index", -1)) == int(part_index):
                part["status"] = "pending"
                part["attempts"] = int(part.get("attempts") or 0) + 1
                part["retry_at"] = float(retry_at)
        status = "failed" if retry_at == float("inf") else "pending"
        self._update_delivery_parts(delivery_id, parts, status=status, retry_at=retry_at, error=error)


__all__ = ["WeixinState"]
