from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from bot.runtime_paths import (
    get_chat_history_db_path,
    get_chat_workspace_key,
    get_chat_workspace_metadata_path,
    get_legacy_project_chat_db_path,
    normalize_workspace_dir,
)

LOCAL_HISTORY_BACKEND = "local_v1"
LEGACY_PROJECT_CHAT_DB_RELATIVE_PATH = Path(".tcb") / "state" / "chat.sqlite"
_STORE_PREPARE_LOCK = Lock()


@dataclass(frozen=True)
class ChatTurnHandle:
    conversation_id: str
    turn_id: str
    user_message_id: str
    assistant_message_id: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_json(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _row_text(row: sqlite3.Row, key: str) -> str:
    return str(row[key] or "")


class ChatStore:
    def __init__(self, workspace_dir: Path | str) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.workspace_key = get_chat_workspace_key(self.workspace_dir)
        self.db_path = get_chat_history_db_path(self.workspace_dir)
        self.metadata_path = get_chat_workspace_metadata_path(self.workspace_dir)
        self.legacy_db_path = get_legacy_project_chat_db_path(self.workspace_dir)

    def _db_exists(self) -> bool:
        return self.db_path.is_file()

    def _write_workspace_metadata(
        self,
        *,
        migrated_from_legacy_project_store: bool,
        legacy_project_db_path: Path | None = None,
    ) -> None:
        now = _utc_now()
        existing: dict[str, Any] = {}
        if self.metadata_path.is_file():
            existing = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        payload = {
            "workspace_key": self.workspace_key,
            "working_dir": str(self.workspace_dir),
            "normalized_working_dir": normalize_workspace_dir(self.workspace_dir),
            "created_at": existing.get("created_at") or now,
            "last_accessed_at": now,
            "store_backend": LOCAL_HISTORY_BACKEND,
            "migrated_from_legacy_project_store": bool(
                existing.get("migrated_from_legacy_project_store")
            )
            or migrated_from_legacy_project_store,
            "legacy_project_db_path": str(legacy_project_db_path or existing.get("legacy_project_db_path") or ""),
            "migration_completed_at": (
                now if migrated_from_legacy_project_store else existing.get("migration_completed_at")
            ),
        }
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _migrate_legacy_store(self) -> None:
        if self._db_exists() or not self.legacy_db_path.is_file():
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.legacy_db_path) as source, sqlite3.connect(self.db_path) as target:
            source.backup(target)
        self._write_workspace_metadata(
            migrated_from_legacy_project_store=True,
            legacy_project_db_path=self.legacy_db_path,
        )

    def _prepare_store(self, *, create: bool) -> bool:
        with _STORE_PREPARE_LOCK:
            if self._db_exists():
                self._write_workspace_metadata(migrated_from_legacy_project_store=False)
                return True
            if self.legacy_db_path.is_file():
                self._migrate_legacy_store()
                return True
            if not create:
                return False
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_workspace_metadata(migrated_from_legacy_project_store=False)
            return True

    def _connect(self, *, create: bool) -> sqlite3.Connection | None:
        if not self._prepare_store(create=create):
            return None
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema(conn)
        return conn

    def _connect_for_write(self) -> sqlite3.Connection:
        conn = self._connect(create=True)
        assert conn is not None
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                bot_id INTEGER NOT NULL,
                bot_alias TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                bot_mode TEXT NOT NULL,
                cli_type TEXT NOT NULL,
                working_dir TEXT NOT NULL,
                session_epoch INTEGER NOT NULL,
                status TEXT NOT NULL,
                native_provider TEXT,
                native_session_id TEXT,
                assistant_home TEXT,
                managed_prompt_hash TEXT,
                prompt_surface_version TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_identity
            ON conversations(bot_id, user_id, working_dir, session_epoch);

            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                user_message_id TEXT NOT NULL,
                assistant_message_id TEXT NOT NULL,
                assistant_state TEXT NOT NULL,
                completion_state TEXT NOT NULL,
                native_provider TEXT,
                native_session_id TEXT,
                managed_prompt_hash TEXT,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                error_code TEXT,
                error_message TEXT,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_conversation_seq
            ON turns(conversation_id, seq);

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                content_format TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY(turn_id) REFERENCES turns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS trace_events (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                kind TEXT NOT NULL,
                raw_type TEXT,
                title TEXT,
                tool_name TEXT,
                call_id TEXT,
                summary TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(turn_id) REFERENCES turns(id) ON DELETE CASCADE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_trace_events_turn_ordinal
            ON trace_events(turn_id, ordinal);
            """
        )

    def _next_turn_seq(self, conn: sqlite3.Connection, conversation_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM turns WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return int(row["next_seq"])

    def _get_active_conversation_id(
        self,
        conn: sqlite3.Connection,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
    ) -> str | None:
        row = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE bot_id = ? AND user_id = ? AND working_dir = ? AND session_epoch = ?
            """,
            (bot_id, user_id, working_dir, session_epoch),
        ).fetchone()
        if row is None:
            return None
        return str(row["id"])

    def _get_or_create_conversation(
        self,
        conn: sqlite3.Connection,
        *,
        bot_id: int,
        bot_alias: str,
        user_id: int,
        bot_mode: str,
        cli_type: str,
        working_dir: str,
        session_epoch: int,
        native_provider: str,
        assistant_home: str | None,
        managed_prompt_hash: str | None,
        prompt_surface_version: str | None,
    ) -> tuple[str, int]:
        now = _utc_now()
        row = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE bot_id = ? AND user_id = ? AND working_dir = ? AND session_epoch = ?
            """,
            (bot_id, user_id, working_dir, session_epoch),
        ).fetchone()

        if row is not None:
            conversation_id = str(row["id"])
            conn.execute(
                """
                UPDATE conversations
                SET bot_alias = ?,
                    bot_mode = ?,
                    cli_type = ?,
                    status = ?,
                    native_provider = ?,
                    assistant_home = ?,
                    managed_prompt_hash = ?,
                    prompt_surface_version = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    bot_alias,
                    bot_mode,
                    cli_type,
                    "active",
                    native_provider,
                    assistant_home,
                    managed_prompt_hash,
                    prompt_surface_version,
                    now,
                    conversation_id,
                ),
            )
            return conversation_id, self._next_turn_seq(conn, conversation_id)

        conversation_id = f"conv_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO conversations (
                id,
                bot_id,
                bot_alias,
                user_id,
                bot_mode,
                cli_type,
                working_dir,
                session_epoch,
                status,
                native_provider,
                native_session_id,
                assistant_home,
                managed_prompt_hash,
                prompt_surface_version,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                bot_id,
                bot_alias,
                user_id,
                bot_mode,
                cli_type,
                working_dir,
                session_epoch,
                "active",
                native_provider,
                None,
                assistant_home,
                managed_prompt_hash,
                prompt_surface_version,
                now,
                now,
            ),
        )
        return conversation_id, 1

    def begin_turn(
        self,
        *,
        bot_id: int,
        bot_alias: str,
        user_id: int,
        bot_mode: str,
        cli_type: str,
        working_dir: str,
        session_epoch: int,
        user_text: str,
        native_provider: str,
        assistant_home: str | None = None,
        managed_prompt_hash: str | None = None,
        prompt_surface_version: str | None = None,
    ) -> ChatTurnHandle:
        now = _utc_now()
        turn_id = f"turn_{uuid.uuid4().hex}"
        user_message_id = f"msg_{uuid.uuid4().hex}"
        assistant_message_id = f"msg_{uuid.uuid4().hex}"
        with self._connect_for_write() as conn:
            conversation_id, next_seq = self._get_or_create_conversation(
                conn,
                bot_id=bot_id,
                bot_alias=bot_alias,
                user_id=user_id,
                bot_mode=bot_mode,
                cli_type=cli_type,
                working_dir=working_dir,
                session_epoch=session_epoch,
                native_provider=native_provider,
                assistant_home=assistant_home,
                managed_prompt_hash=managed_prompt_hash,
                prompt_surface_version=prompt_surface_version,
            )
            conn.execute(
                """
                INSERT INTO turns (
                    id,
                    conversation_id,
                    seq,
                    user_message_id,
                    assistant_message_id,
                    assistant_state,
                    completion_state,
                    native_provider,
                    native_session_id,
                    managed_prompt_hash,
                    started_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    conversation_id,
                    next_seq,
                    user_message_id,
                    assistant_message_id,
                    "streaming",
                    "streaming",
                    native_provider,
                    None,
                    managed_prompt_hash,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO messages (
                    id,
                    conversation_id,
                    turn_id,
                    role,
                    content,
                    content_format,
                    state,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_message_id,
                    conversation_id,
                    turn_id,
                    "user",
                    user_text,
                    "markdown",
                    "done",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO messages (
                    id,
                    conversation_id,
                    turn_id,
                    role,
                    content,
                    content_format,
                    state,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assistant_message_id,
                    conversation_id,
                    turn_id,
                    "assistant",
                    "",
                    "markdown",
                    "streaming",
                    now,
                    now,
                ),
            )
        return ChatTurnHandle(
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        )

    def replace_assistant_content(self, handle: ChatTurnHandle, content: str, *, state: str = "streaming") -> None:
        now = _utc_now()
        with self._connect_for_write() as conn:
            conn.execute(
                "UPDATE messages SET content = ?, state = ?, updated_at = ? WHERE id = ?",
                (content, state, now, handle.assistant_message_id),
            )
            conn.execute(
                "UPDATE turns SET assistant_state = ?, updated_at = ? WHERE id = ?",
                (state, now, handle.turn_id),
            )

    def append_trace_event(
        self,
        turn_id: str,
        *,
        kind: str,
        summary: str,
        raw_type: str = "",
        title: str = "",
        tool_name: str = "",
        call_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now()
        trace_id = f"trace_{uuid.uuid4().hex}"
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        with self._connect_for_write() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 AS next_ordinal FROM trace_events WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO trace_events (
                    id,
                    turn_id,
                    ordinal,
                    kind,
                    raw_type,
                    title,
                    tool_name,
                    call_id,
                    summary,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    turn_id,
                    int(row["next_ordinal"]),
                    kind,
                    raw_type,
                    title,
                    tool_name,
                    call_id,
                    summary,
                    payload_json,
                    now,
                ),
            )
            conn.execute("UPDATE turns SET updated_at = ? WHERE id = ?", (now, turn_id))

    def complete_turn(
        self,
        handle: ChatTurnHandle,
        *,
        content: str,
        completion_state: str,
        native_session_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        message_state = "done" if completion_state == "completed" else "error"
        with self._connect_for_write() as conn:
            conn.execute(
                "UPDATE messages SET content = ?, state = ?, updated_at = ? WHERE id = ?",
                (content, message_state, now, handle.assistant_message_id),
            )
            conn.execute(
                """
                UPDATE turns
                SET assistant_state = ?,
                    completion_state = ?,
                    native_session_id = ?,
                    updated_at = ?,
                    completed_at = ?,
                    error_code = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    message_state,
                    completion_state,
                    native_session_id,
                    now,
                    now,
                    error_code,
                    error_message,
                    handle.turn_id,
                ),
            )
            if native_session_id:
                conn.execute(
                    "UPDATE conversations SET native_session_id = ?, updated_at = ? WHERE id = ?",
                    (native_session_id, now, handle.conversation_id),
                )
        return self.get_message(handle.assistant_message_id)

    def _message_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        trace_count = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM trace_events WHERE turn_id = ?",
                (row["turn_id"],),
            ).fetchone()["count"]
        )
        tool_call_count = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM trace_events WHERE turn_id = ? AND kind = ?",
                (row["turn_id"], "tool_call"),
            ).fetchone()["count"]
        )
        process_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM trace_events
                WHERE turn_id = ? AND kind NOT IN (?, ?)
                """,
                (row["turn_id"], "tool_call", "tool_result"),
            ).fetchone()["count"]
        )
        return {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "state": row["state"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "meta": {
                "completion_state": row["completion_state"],
                "native_provider": row["native_provider"],
                "native_session_id": row["native_session_id"],
                "trace_count": trace_count,
                "tool_call_count": tool_call_count,
                "process_count": process_count,
            },
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        conn = self._connect(create=False)
        if conn is None:
            raise KeyError(message_id)
        with conn:
            row = conn.execute(
                """
                SELECT
                    m.id,
                    m.turn_id,
                    m.role,
                    m.content,
                    m.state,
                    m.created_at,
                    m.updated_at,
                    t.completion_state,
                    t.native_provider,
                    t.native_session_id
                FROM messages AS m
                JOIN turns AS t ON t.id = m.turn_id
                WHERE m.id = ?
                """,
                (message_id,),
            ).fetchone()
            if row is None:
                raise KeyError(message_id)
            return self._message_from_row(conn, row)

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        conn = self._connect(create=False)
        if conn is None:
            return []
        with conn:
            rows = conn.execute(
                """
                SELECT
                    m.id,
                    m.turn_id,
                    m.role,
                    m.content,
                    m.state,
                    m.created_at,
                    m.updated_at,
                    t.seq,
                    t.completion_state,
                    t.native_provider,
                    t.native_session_id
                FROM messages AS m
                JOIN turns AS t ON t.id = m.turn_id
                WHERE m.conversation_id = ?
                ORDER BY
                    t.seq ASC,
                    CASE m.role WHEN 'user' THEN 0 ELSE 1 END ASC,
                    m.created_at ASC,
                    m.id ASC
                """,
                (conversation_id,),
            ).fetchall()
            return [self._message_from_row(conn, row) for row in rows]

    def list_active_history(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = self._connect(create=False)
        if conn is None:
            return []
        with conn:
            conversation_id = self._get_active_conversation_id(
                conn,
                bot_id=bot_id,
                user_id=user_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )
        if conversation_id is None:
            return []
        items = self.list_messages(conversation_id)
        return items[-max(1, limit):]

    def count_history(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
    ) -> int:
        conn = self._connect(create=False)
        if conn is None:
            return 0
        with conn:
            conversation_id = self._get_active_conversation_id(
                conn,
                bot_id=bot_id,
                user_id=user_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )
            if conversation_id is None:
                return 0
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            return int(row["count"])

    def get_running_reply(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
    ) -> dict[str, Any] | None:
        conn = self._connect(create=False)
        if conn is None:
            return None
        with conn:
            conversation_id = self._get_active_conversation_id(
                conn,
                bot_id=bot_id,
                user_id=user_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )
            if conversation_id is None:
                return None
            row = conn.execute(
                """
                SELECT
                    assistant.content AS preview_text,
                    assistant.created_at AS started_at,
                    assistant.updated_at AS updated_at,
                    user.content AS user_text
                FROM turns AS t
                JOIN messages AS assistant ON assistant.id = t.assistant_message_id
                JOIN messages AS user ON user.id = t.user_message_id
                WHERE t.conversation_id = ? AND assistant.state = ?
                ORDER BY t.seq DESC
                LIMIT 1
                """,
                (conversation_id, "streaming"),
            ).fetchone()
            if row is None:
                return None
            return {
                "user_text": row["user_text"] or "",
                "preview_text": row["preview_text"] or "",
                "started_at": row["started_at"],
                "updated_at": row["updated_at"] or row["started_at"],
            }

    def _turn_count(self, conn: sqlite3.Connection, conversation_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM turns WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    def _merge_conversation_metadata(
        self,
        conn: sqlite3.Connection,
        *,
        source: sqlite3.Row,
        target: sqlite3.Row,
        new_alias: str,
    ) -> None:
        conn.execute(
            """
            UPDATE conversations
            SET bot_alias = ?,
                bot_mode = ?,
                cli_type = ?,
                status = ?,
                native_provider = ?,
                native_session_id = ?,
                assistant_home = ?,
                managed_prompt_hash = ?,
                prompt_surface_version = ?,
                created_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_alias,
                _row_text(target, "bot_mode") or _row_text(source, "bot_mode"),
                _row_text(target, "cli_type") or _row_text(source, "cli_type"),
                "active"
                if _row_text(target, "status") == "active" or _row_text(source, "status") == "active"
                else _row_text(target, "status") or _row_text(source, "status") or "active",
                _row_text(target, "native_provider") or _row_text(source, "native_provider") or None,
                _row_text(target, "native_session_id") or _row_text(source, "native_session_id") or None,
                _row_text(target, "assistant_home") or _row_text(source, "assistant_home") or None,
                _row_text(target, "managed_prompt_hash") or _row_text(source, "managed_prompt_hash") or None,
                _row_text(target, "prompt_surface_version") or _row_text(source, "prompt_surface_version") or None,
                min(_row_text(source, "created_at"), _row_text(target, "created_at")),
                max(_row_text(source, "updated_at"), _row_text(target, "updated_at")),
                str(target["id"]),
            ),
        )

    def _merge_conversation_into_target(
        self,
        conn: sqlite3.Connection,
        *,
        source: sqlite3.Row,
        target: sqlite3.Row,
        new_alias: str,
    ) -> None:
        source_id = str(source["id"])
        target_id = str(target["id"])
        source_turns = self._turn_count(conn, source_id)
        target_turns = self._turn_count(conn, target_id)
        prepend_source = _row_text(source, "created_at") <= _row_text(target, "created_at")

        if prepend_source:
            conn.execute(
                "UPDATE turns SET seq = seq + ? WHERE conversation_id = ?",
                (source_turns, target_id),
            )
            conn.execute(
                "UPDATE turns SET conversation_id = ? WHERE conversation_id = ?",
                (target_id, source_id),
            )
        else:
            conn.execute(
                "UPDATE turns SET conversation_id = ?, seq = seq + ? WHERE conversation_id = ?",
                (target_id, target_turns, source_id),
            )

        conn.execute(
            "UPDATE messages SET conversation_id = ? WHERE conversation_id = ?",
            (target_id, source_id),
        )
        self._merge_conversation_metadata(conn, source=source, target=target, new_alias=new_alias)
        conn.execute("DELETE FROM conversations WHERE id = ?", (source_id,))

    def rename_bot_identity(self, *, old_bot_id: int, new_bot_id: int, old_alias: str, new_alias: str) -> int:
        conn = self._connect(create=False)
        if conn is None:
            return 0

        moved = 0
        with conn:
            if old_bot_id == new_bot_id:
                return conn.execute(
                    "UPDATE conversations SET bot_alias = ?, updated_at = ? WHERE bot_id = ? AND bot_alias = ?",
                    (new_alias, _utc_now(), new_bot_id, old_alias),
                ).rowcount

            rows = conn.execute(
                """
                SELECT *
                FROM conversations
                WHERE bot_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (old_bot_id,),
            ).fetchall()
            for source in rows:
                target = conn.execute(
                    """
                    SELECT *
                    FROM conversations
                    WHERE bot_id = ? AND user_id = ? AND working_dir = ? AND session_epoch = ?
                    """,
                    (
                        new_bot_id,
                        source["user_id"],
                        source["working_dir"],
                        source["session_epoch"],
                    ),
                ).fetchone()
                if target is None:
                    conn.execute(
                        "UPDATE conversations SET bot_id = ?, bot_alias = ?, updated_at = ? WHERE id = ?",
                        (new_bot_id, new_alias, _utc_now(), str(source["id"])),
                    )
                else:
                    self._merge_conversation_into_target(conn, source=source, target=target, new_alias=new_alias)
                moved += 1
        return moved

    def delete_conversation(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
    ) -> None:
        conn = self._connect(create=False)
        if conn is None:
            return
        with conn:
            conn.execute(
                """
                DELETE FROM conversations
                WHERE bot_id = ? AND user_id = ? AND working_dir = ? AND session_epoch = ?
                """,
                (bot_id, user_id, working_dir, session_epoch),
            )

    def get_message_trace(self, message_id: str) -> dict[str, Any]:
        conn = self._connect(create=False)
        if conn is None:
            raise KeyError(message_id)
        with conn:
            row = conn.execute(
                "SELECT turn_id FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise KeyError(message_id)
            turn_id = str(row["turn_id"])
            trace_rows = conn.execute(
                """
                SELECT
                    id,
                    ordinal,
                    kind,
                    raw_type,
                    title,
                    tool_name,
                    call_id,
                    summary,
                    payload_json,
                    created_at
                FROM trace_events
                WHERE turn_id = ?
                ORDER BY ordinal ASC, created_at ASC, id ASC
                """,
                (turn_id,),
            ).fetchall()
            trace = [
                {
                    "id": trace_row["id"],
                    "ordinal": int(trace_row["ordinal"]),
                    "kind": trace_row["kind"],
                    "raw_type": trace_row["raw_type"],
                    "title": trace_row["title"],
                    "tool_name": trace_row["tool_name"],
                    "call_id": trace_row["call_id"],
                    "summary": trace_row["summary"],
                    "payload": _parse_json(trace_row["payload_json"]),
                    "created_at": trace_row["created_at"],
                }
                for trace_row in trace_rows
            ]
            tool_call_count = sum(1 for item in trace if str(item["kind"] or "") == "tool_call")
            process_count = sum(1 for item in trace if str(item["kind"] or "") not in {"tool_call", "tool_result"})
            return {
                "message_id": message_id,
                "trace_count": len(trace),
                "tool_call_count": tool_call_count,
                "process_count": process_count,
                "trace": trace,
            }
