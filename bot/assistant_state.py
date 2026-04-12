from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.assistant_home import AssistantHome

logger = logging.getLogger(__name__)


def _user_state_path(home: AssistantHome, user_id: int) -> Path:
    return home.root / "state" / "users" / f"{user_id}.json"


def load_assistant_runtime_state(home: AssistantHome, user_id: int) -> dict[str, Any]:
    path = _user_state_path(home, user_id)
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("加载 assistant 私有状态失败 path=%s error=%s", path, exc)
        return {}

    if isinstance(data, dict):
        return data
    return {}


def save_assistant_runtime_state(home: AssistantHome, user_id: int, payload: dict[str, Any]) -> None:
    path = _user_state_path(home, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_assistant_runtime_state(home: AssistantHome, user_id: int) -> bool:
    path = _user_state_path(home, user_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def attach_assistant_persist_hook(session, home: AssistantHome, user_id: int) -> None:
    def _persist(current) -> None:
        save_assistant_runtime_state(
            home,
            user_id,
            {
                "working_dir": current.working_dir,
                "browse_dir": current.browse_dir or "",
                "history": [dict(item) for item in current.history],
                "codex_session_id": current.codex_session_id,
                "kimi_session_id": current.kimi_session_id,
                "claude_session_id": current.claude_session_id,
                "claude_session_initialized": current.claude_session_initialized,
                "message_count": current.message_count,
                "managed_prompt_hash_seen": current.managed_prompt_hash_seen,
                "last_activity": current.last_activity.isoformat(),
                "running_user_text": current.running_user_text,
                "running_preview_text": current.running_preview_text,
                "running_started_at": current.running_started_at,
                "running_updated_at": current.running_updated_at,
            },
        )

    session.persist_hook = _persist


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _normalize_optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def restore_assistant_runtime_state(session, home: AssistantHome, user_id: int) -> None:
    state = load_assistant_runtime_state(home, user_id)
    if not state:
        return

    with session._lock:
        history = state.get("history")
        if isinstance(history, list):
            session.history = [dict(item) for item in history if isinstance(item, dict)][-100:]

        browse_dir = state.get("browse_dir")
        if isinstance(browse_dir, str) and browse_dir.strip():
            session.browse_dir = browse_dir

        session.codex_session_id = _normalize_optional_str(state.get("codex_session_id"))
        session.kimi_session_id = _normalize_optional_str(state.get("kimi_session_id"))
        session.claude_session_id = _normalize_optional_str(state.get("claude_session_id"))
        session.claude_session_initialized = bool(
            state.get("claude_session_initialized") or session.claude_session_id
        )

        try:
            message_count = int(state.get("message_count", session.message_count) or 0)
        except (TypeError, ValueError):
            message_count = session.message_count
        session.message_count = max(0, message_count)

        last_activity = _parse_datetime(state.get("last_activity"))
        if last_activity is not None:
            session.last_activity = last_activity

        session.running_user_text = _normalize_optional_str(state.get("running_user_text"))
        session.running_preview_text = state.get("running_preview_text") or ""
        session.running_started_at = _normalize_optional_str(state.get("running_started_at"))
        session.running_updated_at = _normalize_optional_str(state.get("running_updated_at"))
        session.managed_prompt_hash_seen = _normalize_optional_str(state.get("managed_prompt_hash_seen"))


def record_assistant_capture(home: AssistantHome, user_id: int, user_text: str, assistant_text: str) -> dict[str, Any]:
    capture = {
        "id": f"cap_{uuid.uuid4().hex[:12]}",
        "source": "chat",
        "user_id": user_id,
        "created_at": datetime.now(UTC).isoformat(),
        "user_text": user_text,
        "assistant_text": assistant_text,
    }
    path = home.root / "inbox" / "captures" / f"{capture['id']}.json"
    path.write_text(
        json.dumps(capture, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return capture
