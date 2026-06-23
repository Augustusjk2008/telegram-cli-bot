from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from bot.runtime_paths import get_chat_workspace_key, get_pi_session_store_path

STORE_VERSION = 1


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _binding_status(value: Any, pi_session_id: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"bound", "missing"}:
        return normalized
    return "bound" if str(pi_session_id or "").strip() else "missing"


def pi_session_key(*, cwd: str, bot_id: int, user_id: int, conversation_id: str) -> str:
    return f"{get_chat_workspace_key(cwd)}:{int(bot_id)}:{int(user_id)}:{str(conversation_id or '').strip()}"


@dataclass
class PiSessionTurnRecord:
    turn_id: str
    linear_index: int
    workspace_history_head: str
    status: str = "active"
    discarded_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PiSessionTurnRecord":
        return cls(
            turn_id=str(payload.get("turn_id") or ""),
            linear_index=max(0, int(payload.get("linear_index") or 0)),
            workspace_history_head=str(payload.get("workspace_history_head") or ""),
            status=str(payload.get("status") or "active"),
            discarded_at=str(payload.get("discarded_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "linear_index": int(self.linear_index),
            "workspace_history_head": self.workspace_history_head,
            "status": self.status,
            "discarded_at": self.discarded_at,
        }


@dataclass
class PiSessionRecord:
    key: str = ""
    cwd: str = ""
    conversation_id: str = ""
    pi_session_id: str = ""
    session_binding_status: str = ""
    session_meta: dict[str, str] = field(default_factory=dict)
    linear_index: int = 0
    workspace_history_head: str = ""
    last_turn_id: str = ""
    degraded: bool = False
    degraded_reason: str = ""
    updated_at: str = ""
    turns: list[PiSessionTurnRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, key: str = "") -> "PiSessionRecord":
        turns = [
            PiSessionTurnRecord.from_dict(item)
            for item in payload.get("turns", [])
            if isinstance(item, dict)
        ]
        raw_meta = payload.get("session_meta")
        session_meta = {}
        if isinstance(raw_meta, dict):
            session_meta = {
                str(meta_key): str(meta_value or "").strip()
                for meta_key, meta_value in raw_meta.items()
            }
        pi_session_id = str(payload.get("pi_session_id") or "")
        return cls(
            key=str(payload.get("key") or key or ""),
            cwd=str(payload.get("cwd") or ""),
            conversation_id=str(payload.get("conversation_id") or ""),
            pi_session_id=pi_session_id,
            session_binding_status=_binding_status(payload.get("session_binding_status"), pi_session_id),
            session_meta=session_meta,
            linear_index=max(0, int(payload.get("linear_index") or 0)),
            workspace_history_head=str(payload.get("workspace_history_head") or ""),
            last_turn_id=str(payload.get("last_turn_id") or ""),
            degraded=bool(payload.get("degraded", False)),
            degraded_reason=str(payload.get("degraded_reason") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            turns=turns,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cwd": self.cwd,
            "conversation_id": self.conversation_id,
            "pi_session_id": self.pi_session_id,
            "session_binding_status": _binding_status(self.session_binding_status, self.pi_session_id),
            "session_meta": {
                str(key): str(value or "").strip()
                for key, value in self.session_meta.items()
                if str(key or "").strip()
            },
            "linear_index": int(self.linear_index),
            "workspace_history_head": self.workspace_history_head,
            "last_turn_id": self.last_turn_id,
            "degraded": bool(self.degraded),
            "degraded_reason": self.degraded_reason,
            "updated_at": self.updated_at,
            "turns": [turn.to_dict() for turn in self.turns],
        }

    def safe_meta(self) -> dict[str, Any]:
        return {
            "workspace_history_head": self.workspace_history_head,
            "linear_index": int(self.linear_index),
            "rollback_supported": bool(self.workspace_history_head and not self.degraded),
            "degraded": bool(self.degraded),
            "degraded_reason": self.degraded_reason,
            "session_binding_status": _binding_status(self.session_binding_status, self.pi_session_id),
        }


class PiSessionStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else get_pi_session_store_path()
        self._lock = RLock()

    def get(self, key: str) -> PiSessionRecord | None:
        normalized = str(key or "").strip()
        if not normalized:
            return None
        with self._lock:
            payload = self._read_payload()
            item = payload["sessions"].get(normalized)
            if not isinstance(item, dict):
                return None
            return PiSessionRecord.from_dict(item, key=normalized)

    def upsert(self, record: PiSessionRecord) -> PiSessionRecord:
        if not record.key:
            raise ValueError("Pi session record key is required")
        with self._lock:
            payload = self._read_payload()
            stored = PiSessionRecord.from_dict(record.to_dict(), key=record.key)
            stored.updated_at = _utc_now()
            payload["sessions"][record.key] = stored.to_dict()
            self._write_payload(payload)
            return stored

    def update_after_completed_turn(
        self,
        key: str,
        *,
        pi_session_id: str,
        turn_id: str,
        workspace_history_head: str,
    ) -> PiSessionRecord:
        normalized_key = str(key or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_key or not normalized_turn_id:
            raise ValueError("Pi session key and turn_id are required")
        with self._lock:
            payload = self._read_payload()
            record = PiSessionRecord.from_dict(payload["sessions"].get(normalized_key, {}), key=normalized_key)
            existing = next((turn for turn in record.turns if turn.turn_id == normalized_turn_id), None)
            head = str(workspace_history_head or "").strip()
            if existing is None:
                record.linear_index = max(0, int(record.linear_index or 0)) + 1
                existing = PiSessionTurnRecord(
                    turn_id=normalized_turn_id,
                    linear_index=record.linear_index,
                    workspace_history_head=head,
                )
                record.turns.append(existing)
            else:
                record.linear_index = max(record.linear_index, existing.linear_index)
                existing.workspace_history_head = head
            record.pi_session_id = str(pi_session_id or record.pi_session_id or "").strip()
            record.session_binding_status = _binding_status("", record.pi_session_id)
            record.workspace_history_head = head
            record.last_turn_id = normalized_turn_id
            record.degraded = False
            record.degraded_reason = ""
            record.updated_at = _utc_now()
            payload["sessions"][normalized_key] = record.to_dict()
            self._write_payload(payload)
            return record

    def mark_degraded(self, key: str, reason: str) -> PiSessionRecord:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("Pi session key is required")
        with self._lock:
            payload = self._read_payload()
            record = PiSessionRecord.from_dict(payload["sessions"].get(normalized_key, {}), key=normalized_key)
            record.degraded = True
            record.degraded_reason = str(reason or "").strip() or "workspace history unavailable"
            record.updated_at = _utc_now()
            payload["sessions"][normalized_key] = record.to_dict()
            self._write_payload(payload)
            return record

    def invalidate_binding(self, key: str, reason: str) -> PiSessionRecord:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("Pi session key is required")
        now = _utc_now()
        with self._lock:
            payload = self._read_payload()
            record = PiSessionRecord.from_dict(payload["sessions"].get(normalized_key, {}), key=normalized_key)
            for turn in record.turns:
                if turn.discarded_at:
                    continue
                turn.status = "discarded"
                turn.discarded_at = now
            record.pi_session_id = ""
            record.session_binding_status = "missing"
            record.linear_index = 0
            record.workspace_history_head = ""
            record.last_turn_id = ""
            record.degraded = False
            record.degraded_reason = ""
            record.updated_at = now
            payload["sessions"][normalized_key] = record.to_dict()
            self._write_payload(payload)
            return record

    def mark_discarded_after(self, key: str, target_turn_id: str) -> PiSessionRecord:
        normalized_key = str(key or "").strip()
        normalized_turn_id = str(target_turn_id or "").strip()
        with self._lock:
            payload = self._read_payload()
            item = payload["sessions"].get(normalized_key)
            if not isinstance(item, dict):
                raise KeyError(normalized_key)
            record = PiSessionRecord.from_dict(item, key=normalized_key)
            target = next((turn for turn in record.turns if turn.turn_id == normalized_turn_id), None)
            if target is None or target.discarded_at:
                raise KeyError(normalized_turn_id)
            now = _utc_now()
            for turn in record.turns:
                if int(turn.linear_index or 0) > int(target.linear_index or 0) and not turn.discarded_at:
                    turn.status = "discarded"
                    turn.discarded_at = now
            record.linear_index = int(target.linear_index or 0)
            record.workspace_history_head = target.workspace_history_head
            record.last_turn_id = target.turn_id
            record.updated_at = now
            payload["sessions"][normalized_key] = record.to_dict()
            self._write_payload(payload)
            return record

    def delete(self, key: str) -> bool:
        normalized = str(key or "").strip()
        if not normalized:
            return False
        with self._lock:
            payload = self._read_payload()
            existed = normalized in payload["sessions"]
            if existed:
                payload["sessions"].pop(normalized, None)
                self._write_payload(payload)
            return existed

    def delete_conversation(
        self,
        *,
        cwd: str,
        bot_id: int,
        user_id: int,
        conversation_id: str,
    ) -> bool:
        return self.delete(pi_session_key(cwd=cwd, bot_id=bot_id, user_id=user_id, conversation_id=conversation_id))

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": STORE_VERSION, "sessions": {}}
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Pi session store JSON 损坏: {self.path}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Pi session store 格式无效: {self.path}")
        sessions = parsed.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        return {"version": STORE_VERSION, "sessions": dict(sessions)}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": STORE_VERSION,
            "sessions": payload.get("sessions") if isinstance(payload.get("sessions"), dict) else {},
        }
        tmp = self.path.with_name(f"{self.path.name}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
