from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from bot.models import normalize_session_bot_alias
from bot.runtime_paths import get_chat_favorites_path


FAVORITES_SCHEMA_VERSION = 1
FAVORITE_ID_FIELDS = (
    "bot_id",
    "user_id",
    "agent_id",
    "execution_mode",
    "conversation_id",
    "message_id",
    "message_key",
)
_STORE_LOCKS: dict[Path, RLock] = {}
_STORE_LOCKS_GUARD = RLock()


@dataclass(frozen=True)
class FavoriteScope:
    bot_id: int
    user_id: int
    agent_id: str = "main"
    execution_mode: str = "cli"
    bot_alias: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_agent_id(value: Any) -> str:
    return str(value or "main").strip().lower() or "main"


def _normalize_execution_mode(value: Any) -> str:
    return str(value or "cli").strip().lower() or "cli"


def normalize_favorite_scope(scope: FavoriteScope) -> FavoriteScope:
    return FavoriteScope(
        bot_id=int(scope.bot_id),
        user_id=int(scope.user_id),
        agent_id=_normalize_agent_id(scope.agent_id),
        execution_mode=_normalize_execution_mode(scope.execution_mode),
        bot_alias=normalize_session_bot_alias(scope.bot_alias),
    )


def make_favorite_id(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("bot_id") or ""),
        str(payload.get("user_id") or ""),
        _normalize_agent_id(payload.get("agent_id")),
        _normalize_execution_mode(payload.get("execution_mode")),
        str(payload.get("conversation_id") or "").strip(),
        str(payload.get("message_id") or "").strip(),
        str(payload.get("message_key") or "").strip(),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"fav_{digest[:32]}"


def _trim_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


def build_favorite_item(
    *,
    scope: FavoriteScope,
    bot_alias: str,
    conversation_id: str,
    message_id: str,
    message_key: str,
    turn_id: str = "",
    title: str = "",
    preview: str = "",
    answer_text: str = "",
    created_at: str = "",
    favorited_at: str | None = None,
) -> dict[str, Any]:
    normalized_scope = normalize_favorite_scope(scope)
    bot_alias = normalize_session_bot_alias(bot_alias)
    if normalized_scope.bot_alias and normalized_scope.bot_alias != bot_alias:
        raise ValueError("favorite scope belongs to a different Bot")
    normalized_answer = str(answer_text or "")
    payload: dict[str, Any] = {
        "bot_id": normalized_scope.bot_id,
        "bot_alias": bot_alias,
        "user_id": normalized_scope.user_id,
        "agent_id": normalized_scope.agent_id,
        "execution_mode": normalized_scope.execution_mode,
        "conversation_id": str(conversation_id or "").strip(),
        "message_id": str(message_id or "").strip(),
        "message_key": str(message_key or "").strip(),
        "turn_id": str(turn_id or "").strip(),
        "title": _trim_text(title, 120),
        "preview": _trim_text(preview or normalized_answer, 240),
        "answer_text": normalized_answer,
        "created_at": str(created_at or "").strip(),
        "favorited_at": str(favorited_at or _utc_now()).strip(),
    }
    payload["id"] = make_favorite_id(payload)
    return payload


def _normalize_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        scope = FavoriteScope(
            bot_id=int(raw.get("bot_id")),
            user_id=int(raw.get("user_id")),
            agent_id=_normalize_agent_id(raw.get("agent_id")),
            execution_mode=_normalize_execution_mode(raw.get("execution_mode")),
        )
    except (TypeError, ValueError):
        return None
    conversation_id = str(raw.get("conversation_id") or "").strip()
    message_id = str(raw.get("message_id") or "").strip()
    message_key = str(raw.get("message_key") or "").strip()
    if not conversation_id or not message_id or not message_key:
        return None
    item = build_favorite_item(
        scope=scope,
        bot_alias=str(raw.get("bot_alias") or "").strip(),
        conversation_id=conversation_id,
        message_id=message_id,
        message_key=message_key,
        turn_id=str(raw.get("turn_id") or "").strip(),
        title=str(raw.get("title") or "").strip(),
        preview=str(raw.get("preview") or "").strip(),
        answer_text=str(raw.get("answer_text") or ""),
        created_at=str(raw.get("created_at") or "").strip(),
        favorited_at=str(raw.get("favorited_at") or "").strip() or _utc_now(),
    )
    item["id"] = str(raw.get("id") or item["id"]).strip() or item["id"]
    return item


class ChatFavoriteStore:
    def __init__(self, working_dir: str | Path) -> None:
        self.working_dir = Path(working_dir)
        self.path = get_chat_favorites_path(self.working_dir)
        resolved_path = self.path.expanduser().resolve()
        with _STORE_LOCKS_GUARD:
            self._lock = _STORE_LOCKS.setdefault(resolved_path, RLock())

    def _backup_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
        try:
            self.path.replace(backup)
        except OSError:
            pass

    def _read_payload(self, *, strict: bool = False) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": FAVORITES_SCHEMA_VERSION, "items": []}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            if strict:
                raise
            self._backup_corrupt_file()
            return {"version": FAVORITES_SCHEMA_VERSION, "items": []}
        if not isinstance(payload, dict):
            if strict:
                raise ValueError("invalid chat favorite store")
            self._backup_corrupt_file()
            return {"version": FAVORITES_SCHEMA_VERSION, "items": []}
        items = payload.get("items")
        if not isinstance(items, list):
            if strict:
                raise ValueError("invalid chat favorite list")
            return {"version": FAVORITES_SCHEMA_VERSION, "items": []}
        normalized = [item for item in (_normalize_item(raw) for raw in items) if item is not None]
        if strict and len(normalized) != len(items):
            raise ValueError("invalid chat favorite")
        return {"version": FAVORITES_SCHEMA_VERSION, "items": normalized}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp():.6f}")
        data = {
            "version": FAVORITES_SCHEMA_VERSION,
            "items": list(payload.get("items") or []),
        }
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _matches_owner(item: dict[str, Any], bot_id: int, bot_alias: str) -> bool:
        if int(item.get("bot_id") or 0) != int(bot_id):
            return False
        if bot_alias:
            return normalize_session_bot_alias(item.get("bot_alias")) == bot_alias
        return not _normalize_agent_id(item.get("agent_id")).startswith("@")

    @staticmethod
    def _matches_scope(item: dict[str, Any], scope: FavoriteScope) -> bool:
        normalized_scope = normalize_favorite_scope(scope)
        return (
            ChatFavoriteStore._matches_owner(item, normalized_scope.bot_id, normalized_scope.bot_alias)
            and int(item.get("user_id") or 0) == normalized_scope.user_id
            and _normalize_agent_id(item.get("agent_id")) == normalized_scope.agent_id
            and _normalize_execution_mode(item.get("execution_mode")) == normalized_scope.execution_mode
        )

    def list_favorites(self, scope: FavoriteScope, query: str = "") -> list[dict[str, Any]]:
        normalized_query = " ".join(str(query or "").strip().lower().split())
        with self._lock:
            items = [
                item
                for item in self._read_payload()["items"]
                if self._matches_scope(item, scope)
            ]
        if normalized_query:
            items = [
                item
                for item in items
                if normalized_query in " ".join([
                    str(item.get("title") or ""),
                    str(item.get("preview") or ""),
                    str(item.get("answer_text") or ""),
                ]).lower()
            ]
        return sorted(items, key=lambda item: str(item.get("favorited_at") or ""), reverse=True)

    def upsert_favorite(self, item: dict[str, Any]) -> dict[str, Any]:
        normalized = _normalize_item(item)
        if normalized is None:
            raise ValueError("invalid favorite item")
        favorite_id = make_favorite_id(normalized)
        normalized["id"] = favorite_id
        with self._lock:
            payload = self._read_payload()
            existing_items = list(payload["items"])
            created_at = normalized["favorited_at"]
            next_items: list[dict[str, Any]] = []
            for existing in existing_items:
                existing_id = make_favorite_id(existing)
                if existing["bot_alias"] == normalized["bot_alias"] and (
                    existing_id == favorite_id or str(existing.get("id") or "") == favorite_id
                ):
                    created_at = str(existing.get("favorited_at") or created_at)
                    continue
                next_items.append(existing)
            normalized["favorited_at"] = created_at
            next_items.append(normalized)
            payload["items"] = sorted(next_items, key=lambda value: str(value.get("favorited_at") or ""), reverse=True)
            self._write_payload(payload)
            return dict(normalized)

    def rename_bot(self, old_bot_id: int, new_bot_id: int, old_alias: str, new_alias: str) -> int:
        old_alias = normalize_session_bot_alias(old_alias)
        new_alias = normalize_session_bot_alias(new_alias)
        if not old_alias or not new_alias:
            raise ValueError("missing Bot alias for favorites rename")
        if (old_bot_id, old_alias) == (new_bot_id, new_alias):
            return 0
        with self._lock:
            payload = self._read_payload(strict=True)
            kept = []
            moved = []
            for item in payload["items"]:
                if self._matches_owner(item, old_bot_id, old_alias):
                    updated = {**item, "bot_id": new_bot_id, "bot_alias": new_alias}
                    updated["id"] = make_favorite_id(updated)
                    moved.append(updated)
                else:
                    kept.append(item)
            if moved:
                # A destination favorite can already exist if a user saved the answer again.
                destination_ids = {
                    make_favorite_id(item) for item in kept if self._matches_owner(item, new_bot_id, new_alias)
                }
                for updated in moved:
                    if updated["id"] not in destination_ids:
                        kept.append(updated)
                        destination_ids.add(updated["id"])
                payload["items"] = kept
                self._write_payload(payload)
            return len(moved)

    def delete_favorite(self, favorite_id: str, scope: FavoriteScope) -> bool:
        normalized_id = str(favorite_id or "").strip()
        if not normalized_id:
            return False
        with self._lock:
            payload = self._read_payload()
            previous_items = list(payload["items"])
            next_items = [
                item
                for item in previous_items
                if not (str(item.get("id") or "") == normalized_id and self._matches_scope(item, scope))
            ]
            if len(next_items) == len(previous_items):
                return False
            payload["items"] = next_items
            self._write_payload(payload)
            return True

    def delete_favorites_for_conversations(
        self,
        conversation_ids: list[str] | set[str] | tuple[str, ...],
        scope: FavoriteScope,
    ) -> int:
        normalized_ids = {str(conversation_id or "").strip() for conversation_id in conversation_ids}
        normalized_ids.discard("")
        if not normalized_ids:
            return 0
        with self._lock:
            payload = self._read_payload()
            previous_items = list(payload["items"])
            next_items = [
                item
                for item in previous_items
                if not (
                    str(item.get("conversation_id") or "").strip() in normalized_ids
                    and self._matches_scope(item, scope)
                )
            ]
            deleted_count = len(previous_items) - len(next_items)
            if deleted_count <= 0:
                return 0
            payload["items"] = next_items
            self._write_payload(payload)
            return deleted_count

    def delete_favorites_for_conversations_any_scope(
        self,
        conversation_ids: list[str] | set[str] | tuple[str, ...],
        *,
        bot_id: int,
        user_id: int,
        bot_alias: str = "",
    ) -> int:
        bot_alias = normalize_session_bot_alias(bot_alias)
        normalized_ids = {str(conversation_id or "").strip() for conversation_id in conversation_ids}
        normalized_ids.discard("")
        if not normalized_ids:
            return 0
        with self._lock:
            payload = self._read_payload()
            previous_items = list(payload["items"])
            next_items = [
                item
                for item in previous_items
                if not (
                    str(item.get("conversation_id") or "").strip() in normalized_ids
                    and self._matches_owner(item, bot_id, bot_alias)
                    and int(item.get("user_id") or 0) == int(user_id)
                )
            ]
            deleted_count = len(previous_items) - len(next_items)
            if deleted_count <= 0:
                return 0
            payload["items"] = next_items
            self._write_payload(payload)
            return deleted_count

    def delete_favorites_for_scope(self, scope: FavoriteScope) -> int:
        with self._lock:
            payload = self._read_payload()
            previous_items = list(payload["items"])
            next_items = [item for item in previous_items if not self._matches_scope(item, scope)]
            deleted_count = len(previous_items) - len(next_items)
            if deleted_count <= 0:
                return 0
            payload["items"] = next_items
            self._write_payload(payload)
            return deleted_count

    def delete_favorites_for_bot(self, *, bot_id: int, bot_alias: str = "") -> int:
        bot_alias = normalize_session_bot_alias(bot_alias)
        with self._lock:
            payload = self._read_payload()
            previous_items = list(payload["items"])
            next_items = [item for item in previous_items if not self._matches_owner(item, bot_id, bot_alias)]
            deleted_count = len(previous_items) - len(next_items)
            if deleted_count <= 0:
                return 0
            payload["items"] = next_items
            self._write_payload(payload)
            return deleted_count
