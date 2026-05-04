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
_PREPARED_STORES: set[Path] = set()
_SCHEMA_READY_STORES: set[Path] = set()


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


def clear_chat_store_prepare_cache() -> None:
    with _STORE_PREPARE_LOCK:
        _PREPARED_STORES.clear()
        _SCHEMA_READY_STORES.clear()


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
            if self.db_path in _PREPARED_STORES and self._db_exists():
                return True
            if self._db_exists():
                self._write_workspace_metadata(migrated_from_legacy_project_store=False)
                _PREPARED_STORES.add(self.db_path)
                return True
            if self.legacy_db_path.is_file():
                self._migrate_legacy_store()
                _PREPARED_STORES.add(self.db_path)
                return True
            if not create:
                return False
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_workspace_metadata(migrated_from_legacy_project_store=False)
            _PREPARED_STORES.add(self.db_path)
            return True

    def _connect(self, *, create: bool) -> sqlite3.Connection | None:
        if not self._prepare_store(create=create):
            return None
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema_once(conn)
        return conn

    def _connect_for_write(self) -> sqlite3.Connection:
        conn = self._connect(create=True)
        assert conn is not None
        return conn

    def _ensure_schema_once(self, conn: sqlite3.Connection) -> None:
        with _STORE_PREPARE_LOCK:
            if self.db_path in _SCHEMA_READY_STORES:
                return
            conn.execute("PRAGMA journal_mode=WAL")
            self._ensure_schema(conn)
            _SCHEMA_READY_STORES.add(self.db_path)

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row["name"]) for row in rows}

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column_name: str,
        column_type: str,
    ) -> None:
        if column_name in self._table_columns(conn, table):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                bot_id INTEGER NOT NULL,
                bot_alias TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                agent_id TEXT NOT NULL DEFAULT 'main',
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
                agent_prompt_hash TEXT,
                title TEXT,
                last_message_preview TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

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
                trace_recovery_attempted_at TEXT,
                trace_recovery_status TEXT,
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

            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id);

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
        conn.execute("DROP INDEX IF EXISTS idx_conversations_identity")
        self._ensure_column(conn, "conversations", "title", "TEXT")
        self._ensure_column(conn, "conversations", "agent_id", "TEXT NOT NULL DEFAULT 'main'")
        self._ensure_column(conn, "conversations", "agent_prompt_hash", "TEXT")
        self._ensure_column(conn, "conversations", "last_message_preview", "TEXT")
        self._ensure_column(conn, "conversations", "message_count", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(conn, "conversations", "pinned", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(conn, "conversations", "archived_at", "TEXT")
        self._ensure_column(conn, "turns", "trace_recovery_attempted_at", "TEXT")
        self._ensure_column(conn, "turns", "trace_recovery_status", "TEXT")
        conn.execute("DROP INDEX IF EXISTS idx_conversations_scope_updated")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversations_agent_scope_updated
            ON conversations(bot_id, user_id, agent_id, working_dir, archived_at, pinned, updated_at)
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
        agent_id: str = "main",
        working_dir: str,
        session_epoch: int,
    ) -> str | None:
        row = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE bot_id = ? AND user_id = ? AND agent_id = ? AND working_dir = ? AND session_epoch = ? AND archived_at IS NULL
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (bot_id, user_id, str(agent_id or "main"), working_dir, session_epoch),
        ).fetchone()
        if row is None:
            return None
        return str(row["id"])

    def _get_scoped_conversation_id(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str | None,
        bot_id: int,
        user_id: int,
        agent_id: str = "main",
        working_dir: str,
        session_epoch: int,
    ) -> str | None:
        normalized_id = str(conversation_id or "").strip()
        if not normalized_id:
            return self._get_active_conversation_id(
                conn,
                bot_id=bot_id,
                user_id=user_id,
                agent_id=agent_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )

        row = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE id = ? AND bot_id = ? AND user_id = ? AND agent_id = ? AND working_dir = ? AND archived_at IS NULL
            """,
            (normalized_id, bot_id, user_id, str(agent_id or "main"), working_dir),
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
        agent_id: str = "main",
        bot_mode: str,
        cli_type: str,
        working_dir: str,
        session_epoch: int,
        native_provider: str,
        assistant_home: str | None,
        managed_prompt_hash: str | None,
        prompt_surface_version: str | None,
        agent_prompt_hash: str | None = None,
    ) -> tuple[str, int]:
        now = _utc_now()
        row = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE bot_id = ? AND user_id = ? AND agent_id = ? AND working_dir = ? AND session_epoch = ? AND archived_at IS NULL
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (bot_id, user_id, str(agent_id or "main"), working_dir, session_epoch),
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
                    agent_prompt_hash = ?,
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
                    agent_prompt_hash,
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
                agent_id,
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
                agent_prompt_hash,
                title,
                last_message_preview,
                message_count,
                pinned,
                archived_at,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                bot_id,
                bot_alias,
                user_id,
                str(agent_id or "main"),
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
                agent_prompt_hash,
                "",
                "",
                0,
                0,
                None,
                now,
                now,
            ),
        )
        return conversation_id, 1

    def _conversation_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "bot_id": int(row["bot_id"]),
            "bot_alias": str(row["bot_alias"] or ""),
            "user_id": int(row["user_id"]),
            "agent_id": str(row["agent_id"] or "main"),
            "bot_mode": str(row["bot_mode"] or ""),
            "cli_type": str(row["cli_type"] or ""),
            "working_dir": str(row["working_dir"] or ""),
            "session_epoch": int(row["session_epoch"] or 0),
            "status": str(row["status"] or "active"),
            "native_provider": str(row["native_provider"] or ""),
            "native_session_id": str(row["native_session_id"] or ""),
            "agent_prompt_hash": str(row["agent_prompt_hash"] or ""),
            "title": str(row["title"] or ""),
            "last_message_preview": str(row["last_message_preview"] or ""),
            "message_count": int(row["message_count"] or 0),
            "pinned": bool(row["pinned"]),
            "archived_at": str(row["archived_at"] or ""),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }

    def create_conversation(
        self,
        *,
        bot_id: int,
        bot_alias: str,
        user_id: int,
        agent_id: str = "main",
        bot_mode: str,
        cli_type: str,
        working_dir: str,
        session_epoch: int,
        native_provider: str,
        title: str = "",
        assistant_home: str | None = None,
        managed_prompt_hash: str | None = None,
        prompt_surface_version: str | None = None,
        agent_prompt_hash: str | None = None,
    ) -> str:
        now = _utc_now()
        conversation_id = f"conv_{uuid.uuid4().hex}"
        normalized_title = str(title or "").strip()
        with self._connect_for_write() as conn:
            conn.execute(
                """
                INSERT INTO conversations (
                    id,
                    bot_id,
                    bot_alias,
                    user_id,
                    agent_id,
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
                    agent_prompt_hash,
                    title,
                    last_message_preview,
                    message_count,
                    pinned,
                    archived_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    bot_id,
                    bot_alias,
                    user_id,
                    str(agent_id or "main"),
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
                    agent_prompt_hash,
                    normalized_title,
                    "",
                    0,
                    0,
                    None,
                    now,
                    now,
                ),
            )
        return conversation_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        conn = self._connect(create=False)
        if conn is None:
            raise KeyError(conversation_id)
        with conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            return self._conversation_from_row(row)

    def list_conversations(
        self,
        *,
        bot_id: int,
        user_id: int,
        agent_id: str = "main",
        working_dir: str,
        limit: int = 50,
        query: str = "",
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        conn = self._connect(create=False)
        if conn is None:
            return []

        safe_limit = max(1, min(int(limit), 100))
        normalized_query = str(query or "").strip()
        archived_clause = "" if include_archived else "AND archived_at IS NULL"
        query_clause = ""
        params: list[Any] = [bot_id, user_id, str(agent_id or "main"), working_dir]
        if normalized_query:
            query_clause = "AND (title LIKE ? OR last_message_preview LIKE ?)"
            query_value = f"%{normalized_query}%"
            params.extend([query_value, query_value])
        params.append(safe_limit)

        with conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM conversations
                WHERE bot_id = ? AND user_id = ? AND agent_id = ? AND working_dir = ?
                {archived_clause}
                {query_clause}
                ORDER BY pinned DESC, updated_at DESC, created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._conversation_from_row(row) for row in rows]

    def begin_turn(
        self,
        *,
        bot_id: int,
        bot_alias: str,
        user_id: int,
        agent_id: str = "main",
        bot_mode: str,
        cli_type: str,
        working_dir: str,
        session_epoch: int,
        user_text: str,
        native_provider: str,
        conversation_id: str | None = None,
        assistant_home: str | None = None,
        managed_prompt_hash: str | None = None,
        prompt_surface_version: str | None = None,
        agent_prompt_hash: str | None = None,
    ) -> ChatTurnHandle:
        now = _utc_now()
        turn_id = f"turn_{uuid.uuid4().hex}"
        user_message_id = f"msg_{uuid.uuid4().hex}"
        assistant_message_id = f"msg_{uuid.uuid4().hex}"
        with self._connect_for_write() as conn:
            normalized_conversation_id = str(conversation_id or "").strip()
            if normalized_conversation_id:
                row = conn.execute(
                    """
                    SELECT id
                    FROM conversations
                    WHERE id = ? AND bot_id = ? AND user_id = ? AND agent_id = ? AND working_dir = ? AND archived_at IS NULL
                    """,
                    (normalized_conversation_id, bot_id, user_id, str(agent_id or "main"), working_dir),
                ).fetchone()
                if row is None:
                    raise KeyError(normalized_conversation_id)
                resolved_conversation_id = str(row["id"])
                next_seq = self._next_turn_seq(conn, resolved_conversation_id)
            else:
                resolved_conversation_id, next_seq = self._get_or_create_conversation(
                    conn,
                    bot_id=bot_id,
                    bot_alias=bot_alias,
                    user_id=user_id,
                    agent_id=agent_id,
                    bot_mode=bot_mode,
                    cli_type=cli_type,
                    working_dir=working_dir,
                    session_epoch=session_epoch,
                    native_provider=native_provider,
                    assistant_home=assistant_home,
                    managed_prompt_hash=managed_prompt_hash,
                    prompt_surface_version=prompt_surface_version,
                    agent_prompt_hash=agent_prompt_hash,
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
                    resolved_conversation_id,
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
                    resolved_conversation_id,
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
                    resolved_conversation_id,
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
            conversation_id=resolved_conversation_id,
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
        self.append_trace_events(
            turn_id,
            [
                {
                    "kind": kind,
                    "summary": summary,
                    "raw_type": raw_type,
                    "title": title,
                    "tool_name": tool_name,
                    "call_id": call_id,
                    "payload": payload,
                }
            ],
        )

    def append_trace_events(self, turn_id: str, events: list[dict[str, Any]]) -> None:
        normalized_events = [dict(event) for event in events if isinstance(event, dict)]
        if not normalized_events:
            return
        now = _utc_now()
        with self._connect_for_write() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 AS next_ordinal FROM trace_events WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
            next_ordinal = int(row["next_ordinal"])
            for offset, event in enumerate(normalized_events):
                payload = event.get("payload")
                payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
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
                        f"trace_{uuid.uuid4().hex}",
                        turn_id,
                        next_ordinal + offset,
                        str(event.get("kind") or "unknown"),
                        str(event.get("raw_type") or ""),
                        str(event.get("title") or ""),
                        str(event.get("tool_name") or ""),
                        str(event.get("call_id") or ""),
                        str(event.get("summary") or ""),
                        payload_json,
                        now,
                    ),
                )
            conn.execute("UPDATE turns SET updated_at = ? WHERE id = ?", (now, turn_id))

    def mark_trace_recovery_attempted(self, turn_id: str, *, status: str) -> None:
        now = _utc_now()
        normalized_status = str(status or "").strip() or "attempted"
        with self._connect_for_write() as conn:
            result = conn.execute(
                """
                UPDATE turns
                SET trace_recovery_attempted_at = ?,
                    trace_recovery_status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, normalized_status, now, turn_id),
            )
            if result.rowcount == 0:
                raise KeyError(turn_id)

    def replace_trace_events(self, turn_id: str, trace: list[dict[str, Any]] | None) -> None:
        now = _utc_now()
        normalized_trace = [dict(item) for item in (trace or []) if isinstance(item, dict)]
        with self._connect_for_write() as conn:
            existing_turn = conn.execute(
                "SELECT id FROM turns WHERE id = ?",
                (turn_id,),
            ).fetchone()
            if existing_turn is None:
                raise KeyError(turn_id)

            conn.execute("DELETE FROM trace_events WHERE turn_id = ?", (turn_id,))
            for ordinal, item in enumerate(normalized_trace, start=1):
                payload = item.get("payload")
                payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
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
                        f"trace_{uuid.uuid4().hex}",
                        turn_id,
                        ordinal,
                        str(item.get("kind") or "unknown"),
                        str(item.get("raw_type") or ""),
                        str(item.get("title") or ""),
                        str(item.get("tool_name") or ""),
                        str(item.get("call_id") or ""),
                        str(item.get("summary") or ""),
                        payload_json,
                        str(item.get("created_at") or now),
                    ),
                )
            conn.execute("UPDATE turns SET updated_at = ? WHERE id = ?", (now, turn_id))

    def _derive_title(self, conn: sqlite3.Connection, conversation_id: str) -> str:
        row = conn.execute(
            """
            SELECT content
            FROM messages
            WHERE conversation_id = ? AND role = 'user'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
        text = " ".join(str(row["content"] or "").strip().split()) if row is not None else ""
        if not text:
            return "新会话"
        return text if len(text) <= 32 else f"{text[:29].rstrip()}..."

    def _summarize_preview(self, content: str) -> str:
        preview = " ".join(str(content or "").strip().split())
        if len(preview) > 160:
            return f"{preview[:157].rstrip()}..."
        return preview

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
            title = self._derive_title(conn, handle.conversation_id)
            conn.execute(
                """
                UPDATE conversations
                SET native_session_id = COALESCE(NULLIF(?, ''), native_session_id),
                    title = CASE WHEN COALESCE(title, '') = '' THEN ? ELSE title END,
                    last_message_preview = ?,
                    message_count = (SELECT COUNT(*) FROM messages WHERE conversation_id = ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    native_session_id or "",
                    title,
                    self._summarize_preview(content),
                    handle.conversation_id,
                    now,
                    handle.conversation_id,
                ),
            )
        return self.get_message(handle.assistant_message_id)

    def _load_trace_stats(
        self,
        conn: sqlite3.Connection,
        turn_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        normalized_turn_ids = [str(turn_id) for turn_id in turn_ids if turn_id]
        if not normalized_turn_ids:
            return {}

        placeholders = ", ".join("?" for _ in normalized_turn_ids)
        rows = conn.execute(
            f"""
            SELECT
                turn_id,
                COUNT(*) AS trace_count,
                SUM(CASE WHEN kind = ? THEN 1 ELSE 0 END) AS tool_call_count,
                SUM(CASE WHEN kind NOT IN (?, ?) THEN 1 ELSE 0 END) AS process_count
            FROM trace_events
            WHERE turn_id IN ({placeholders})
            GROUP BY turn_id
            """,
            ("tool_call", "tool_call", "tool_result", *normalized_turn_ids),
        ).fetchall()

        stats: dict[str, dict[str, int]] = {}
        for item in rows:
            turn_id = str(item["turn_id"])
            stats[turn_id] = {
                "trace_count": int(item["trace_count"] or 0),
                "tool_call_count": int(item["tool_call_count"] or 0),
                "process_count": int(item["process_count"] or 0),
            }
        return stats

    def _message_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        trace_stats_by_turn: dict[str, dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        turn_id = str(row["turn_id"])
        if trace_stats_by_turn is None:
            trace_stats_by_turn = self._load_trace_stats(conn, [turn_id])
        trace_stats = trace_stats_by_turn.get(turn_id, {})
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
                "trace_count": int(trace_stats.get("trace_count", 0) or 0),
                "tool_call_count": int(trace_stats.get("tool_call_count", 0) or 0),
                "process_count": int(trace_stats.get("process_count", 0) or 0),
            },
        }

    def _list_message_rows(
        self,
        conn: sqlite3.Connection,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        if limit is None:
            return conn.execute(
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

        safe_limit = max(1, int(limit))
        return conn.execute(
            """
            SELECT
                recent.id,
                recent.turn_id,
                recent.role,
                recent.content,
                recent.state,
                recent.created_at,
                recent.updated_at,
                recent.seq,
                recent.completion_state,
                recent.native_provider,
                recent.native_session_id,
                recent.role_order
            FROM (
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
                    t.native_session_id,
                    CASE m.role WHEN 'user' THEN 0 ELSE 1 END AS role_order
                FROM messages AS m
                JOIN turns AS t ON t.id = m.turn_id
                WHERE m.conversation_id = ?
                ORDER BY
                    t.seq DESC,
                    role_order DESC,
                    m.created_at DESC,
                    m.id DESC
                LIMIT ?
            ) AS recent
            ORDER BY
                recent.seq ASC,
                recent.role_order ASC,
                recent.created_at ASC,
                recent.id ASC
            """,
            (conversation_id, safe_limit),
        ).fetchall()

    def _messages_from_rows(self, conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        if not rows:
            return []
        trace_stats_by_turn = self._load_trace_stats(conn, [str(row["turn_id"]) for row in rows])
        return [self._message_from_row(conn, row, trace_stats_by_turn) for row in rows]

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
            return self._messages_from_rows(conn, [row])[0]

    def list_messages(self, conversation_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        conn = self._connect(create=False)
        if conn is None:
            return []
        with conn:
            rows = self._list_message_rows(conn, conversation_id, limit=limit)
            return self._messages_from_rows(conn, rows)

    def list_active_history(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
        agent_id: str = "main",
        conversation_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = self._connect(create=False)
        if conn is None:
            return []
        with conn:
            resolved_conversation_id = self._get_scoped_conversation_id(
                conn,
                conversation_id=conversation_id,
                bot_id=bot_id,
                user_id=user_id,
                agent_id=agent_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )
        if resolved_conversation_id is None:
            return []
        return self.list_messages(resolved_conversation_id, limit=max(1, limit))

    def count_history(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
        agent_id: str = "main",
        conversation_id: str | None = None,
    ) -> int:
        conn = self._connect(create=False)
        if conn is None:
            return 0
        with conn:
            resolved_conversation_id = self._get_scoped_conversation_id(
                conn,
                conversation_id=conversation_id,
                bot_id=bot_id,
                user_id=user_id,
                agent_id=agent_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )
            if resolved_conversation_id is None:
                return 0
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ?",
                (resolved_conversation_id,),
            ).fetchone()
            return int(row["count"])

    def mark_stale_streaming_turns(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
        agent_id: str = "main",
        conversation_id: str | None = None,
        error_code: str = "stale_stream_recovered",
        fallback_content: str = "上次运行未正常结束，已停止显示正在输出。",
    ) -> int:
        conn = self._connect(create=False)
        if conn is None:
            return 0
        now = _utc_now()
        with conn:
            resolved_conversation_id = self._get_scoped_conversation_id(
                conn,
                conversation_id=conversation_id,
                bot_id=bot_id,
                user_id=user_id,
                agent_id=agent_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )
            if resolved_conversation_id is None:
                return 0
            rows = conn.execute(
                """
                SELECT
                    t.id AS turn_id,
                    t.assistant_message_id AS assistant_message_id,
                    m.content AS assistant_content
                FROM turns AS t
                JOIN messages AS m ON m.id = t.assistant_message_id
                WHERE t.conversation_id = ? AND m.role = ? AND m.state = ?
                """,
                (resolved_conversation_id, "assistant", "streaming"),
            ).fetchall()
            for row in rows:
                content = str(row["assistant_content"] or "").strip() or fallback_content
                conn.execute(
                    "UPDATE messages SET content = ?, state = ?, updated_at = ? WHERE id = ?",
                    (content, "error", now, row["assistant_message_id"]),
                )
                conn.execute(
                    """
                    UPDATE turns
                    SET assistant_state = ?,
                        completion_state = ?,
                        completed_at = ?,
                        updated_at = ?,
                        error_code = ?,
                        error_message = ?
                    WHERE id = ?
                    """,
                    ("error", error_code, now, now, error_code, content, row["turn_id"]),
                )
            return len(rows)

    def get_running_reply(
        self,
        *,
        bot_id: int,
        user_id: int,
        working_dir: str,
        session_epoch: int,
        agent_id: str = "main",
        conversation_id: str | None = None,
    ) -> dict[str, Any] | None:
        conn = self._connect(create=False)
        if conn is None:
            return None
        with conn:
            resolved_conversation_id = self._get_scoped_conversation_id(
                conn,
                conversation_id=conversation_id,
                bot_id=bot_id,
                user_id=user_id,
                agent_id=agent_id,
                working_dir=working_dir,
                session_epoch=session_epoch,
            )
            if resolved_conversation_id is None:
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
                (resolved_conversation_id, "streaming"),
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
                    WHERE bot_id = ? AND user_id = ? AND agent_id = ? AND working_dir = ? AND session_epoch = ?
                    """,
                    (
                        new_bot_id,
                        source["user_id"],
                        source["agent_id"],
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
        agent_id: str = "main",
    ) -> None:
        conn = self._connect(create=False)
        if conn is None:
            return
        with conn:
            conn.execute(
                """
                DELETE FROM conversations
                WHERE bot_id = ? AND user_id = ? AND agent_id = ? AND working_dir = ? AND session_epoch = ?
                """,
                (bot_id, user_id, str(agent_id or "main"), working_dir, session_epoch),
            )

    def delete_conversation_by_id(self, conversation_id: str) -> None:
        conn = self._connect(create=False)
        if conn is None:
            return
        with conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

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

    def get_trace_recovery_context(self, message_id: str) -> dict[str, Any]:
        conn = self._connect(create=False)
        if conn is None:
            raise KeyError(message_id)
        with conn:
            row = conn.execute(
                """
                SELECT
                    assistant.id AS message_id,
                    assistant.turn_id AS turn_id,
                    assistant.conversation_id AS conversation_id,
                    assistant.role AS role,
                    assistant.content AS assistant_text,
                    user.content AS user_text,
                    conversation.working_dir AS working_dir,
                    turn.native_provider AS native_provider,
                    turn.native_session_id AS native_session_id,
                    turn.completion_state AS completion_state,
                    turn.trace_recovery_attempted_at AS trace_recovery_attempted_at,
                    turn.trace_recovery_status AS trace_recovery_status
                FROM messages AS assistant
                JOIN turns AS turn ON turn.id = assistant.turn_id
                JOIN conversations AS conversation ON conversation.id = assistant.conversation_id
                JOIN messages AS user ON user.id = turn.user_message_id
                WHERE assistant.id = ?
                """,
                (message_id,),
            ).fetchone()
            if row is None:
                raise KeyError(message_id)
            trace_stats = self._load_trace_stats(conn, [str(row["turn_id"])]).get(str(row["turn_id"]), {})
            return {
                "message_id": str(row["message_id"]),
                "turn_id": str(row["turn_id"]),
                "conversation_id": str(row["conversation_id"]),
                "role": str(row["role"] or ""),
                "assistant_text": str(row["assistant_text"] or ""),
                "user_text": str(row["user_text"] or ""),
                "working_dir": str(row["working_dir"] or ""),
                "native_provider": str(row["native_provider"] or ""),
                "native_session_id": str(row["native_session_id"] or ""),
                "completion_state": str(row["completion_state"] or ""),
                "trace_recovery_attempted_at": str(row["trace_recovery_attempted_at"] or ""),
                "trace_recovery_status": str(row["trace_recovery_status"] or ""),
                "trace_count": int(trace_stats.get("trace_count", 0) or 0),
                "tool_call_count": int(trace_stats.get("tool_call_count", 0) or 0),
                "process_count": int(trace_stats.get("process_count", 0) or 0),
            }
