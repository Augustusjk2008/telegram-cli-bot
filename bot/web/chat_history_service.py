from __future__ import annotations

from typing import Any

from bot.cli import normalize_cli_type
from bot.models import BotProfile, UserSession
from bot.web.chat_store import ChatStore, ChatTurnHandle
from bot.web.native_history_builder import resolve_native_trace_for_turn


def _session_epoch(session: UserSession) -> int:
    try:
        return max(0, int(getattr(session, "session_epoch", 0) or 0))
    except (TypeError, ValueError):
        return 0


class ChatHistoryService:
    def __init__(self, store: ChatStore) -> None:
        self.store = store

    def _should_attempt_trace_recovery(self, context: dict[str, Any]) -> bool:
        if str(context.get("role") or "") != "assistant":
            return False
        if str(context.get("completion_state") or "") != "completed":
            return False
        provider = normalize_cli_type(str(context.get("native_provider") or ""))
        if provider not in {"codex", "claude"}:
            return False
        return bool(str(context.get("native_session_id") or "").strip())

    def _should_replace_trace(
        self,
        current: dict[str, Any],
        recovered: dict[str, Any] | None,
    ) -> bool:
        if not recovered:
            return False
        recovered_trace_count = int(recovered.get("trace_count") or 0)
        recovered_tool_call_count = int(recovered.get("tool_call_count") or 0)
        if recovered_trace_count <= 0:
            return False

        current_trace_count = int(current.get("trace_count") or 0)
        current_tool_call_count = int(current.get("tool_call_count") or 0)
        if current_trace_count == 0:
            return True
        if recovered_tool_call_count > current_tool_call_count:
            return True
        return recovered_trace_count > current_trace_count

    def _recover_trace_for_context(self, context: dict[str, Any]) -> bool:
        if not self._should_attempt_trace_recovery(context):
            return False

        provider = normalize_cli_type(str(context.get("native_provider") or ""))
        recovered = resolve_native_trace_for_turn(
            provider,
            str(context.get("native_session_id") or ""),
            user_text=str(context.get("user_text") or ""),
            assistant_text=str(context.get("assistant_text") or ""),
            cwd_hint=str(context.get("working_dir") or "") or None,
        )
        if not self._should_replace_trace(context, recovered):
            return False
        self.store.replace_trace_events(str(context.get("turn_id") or ""), recovered["trace"])
        return True

    def start_turn(
        self,
        *,
        profile: BotProfile,
        session: UserSession,
        user_text: str,
        native_provider: str,
        assistant_home: str | None = None,
        managed_prompt_hash: str | None = None,
        prompt_surface_version: str | None = None,
    ) -> ChatTurnHandle:
        return self.store.begin_turn(
            bot_id=session.bot_id,
            bot_alias=session.bot_alias,
            user_id=session.user_id,
            bot_mode=profile.bot_mode,
            cli_type=profile.cli_type,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            user_text=user_text,
            native_provider=native_provider,
            assistant_home=assistant_home,
            managed_prompt_hash=managed_prompt_hash,
            prompt_surface_version=prompt_surface_version,
        )

    def replace_assistant_preview(self, handle: ChatTurnHandle, preview_text: str) -> None:
        self.store.replace_assistant_content(handle, preview_text[-800:], state="streaming")

    def append_trace_event(self, handle: ChatTurnHandle, event: dict[str, Any]) -> None:
        self.store.append_trace_event(
            handle.turn_id,
            kind=str(event.get("kind") or "unknown"),
            raw_type=str(event.get("raw_type") or ""),
            title=str(event.get("title") or ""),
            tool_name=str(event.get("tool_name") or ""),
            call_id=str(event.get("call_id") or ""),
            summary=str(event.get("summary") or ""),
            payload=event.get("payload"),
        )

    def replace_assistant_content(self, handle: ChatTurnHandle, content: str, *, state: str = "streaming") -> None:
        self.store.replace_assistant_content(handle, content, state=state)

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
        return self.store.complete_turn(
            handle,
            content=content,
            completion_state=completion_state,
            native_session_id=native_session_id,
            error_code=error_code,
            error_message=error_message,
        )

    def list_history(self, profile: BotProfile, session: UserSession, limit: int = 50) -> list[dict[str, Any]]:
        items = self.store.list_active_history(
            bot_id=session.bot_id,
            user_id=session.user_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            limit=limit,
        )
        recovered = False
        for item in items:
            if str(item.get("role") or "") != "assistant":
                continue
            try:
                context = self.store.get_trace_recovery_context(str(item.get("id") or ""))
            except KeyError:
                continue
            if self._recover_trace_for_context(context):
                recovered = True
        if not recovered:
            return items
        return self.store.list_active_history(
            bot_id=session.bot_id,
            user_id=session.user_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            limit=limit,
        )

    def get_message_trace(
        self,
        profile: BotProfile,
        session: UserSession,
        message_id: str,
    ) -> dict[str, Any] | None:
        try:
            context = self.store.get_trace_recovery_context(message_id)
        except KeyError:
            return None
        self._recover_trace_for_context(context)
        try:
            return self.store.get_message_trace(message_id)
        except KeyError:
            return None

    def reconcile_turn_trace(
        self,
        handle: ChatTurnHandle,
        *,
        profile: BotProfile,
        session: UserSession,
        user_text: str,
        assistant_text: str,
        native_session_id: str | None = None,
    ) -> bool:
        provider = normalize_cli_type(getattr(profile, "cli_type", ""))
        session_id = str(native_session_id or "").strip()
        if provider not in {"codex", "claude"} or not session_id:
            return False

        try:
            current_trace = self.store.get_message_trace(handle.assistant_message_id)
        except KeyError:
            return False

        recovered = resolve_native_trace_for_turn(
            provider,
            session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            cwd_hint=session.working_dir,
        )
        if not self._should_replace_trace(current_trace, recovered):
            return False
        self.store.replace_trace_events(handle.turn_id, recovered["trace"])
        return True

    def build_session_snapshot(self, profile: BotProfile, session: UserSession) -> dict[str, Any]:
        return {
            "bot_alias": profile.alias,
            "bot_mode": profile.bot_mode,
            "cli_type": profile.cli_type,
            "cli_path": profile.cli_path,
            "working_dir": session.working_dir,
            "message_count": session.message_count,
            "history_count": self.store.count_history(
                bot_id=session.bot_id,
                user_id=session.user_id,
                working_dir=session.working_dir,
                session_epoch=_session_epoch(session),
            ),
            "is_processing": session.is_processing,
            "running_reply": self.store.get_running_reply(
                bot_id=session.bot_id,
                user_id=session.user_id,
                working_dir=session.working_dir,
                session_epoch=_session_epoch(session),
            ),
            "session_ids": {
                "codex_session_id": session.codex_session_id,
                "claude_session_id": session.claude_session_id,
                "claude_session_initialized": session.claude_session_initialized,
            },
        }

    def summarize_active_conversation(self, profile: BotProfile, session: UserSession) -> dict[str, Any]:
        return {
            "current_working_dir": session.working_dir,
            "history_count": self.store.count_history(
                bot_id=session.bot_id,
                user_id=session.user_id,
                working_dir=session.working_dir,
                session_epoch=_session_epoch(session),
            ),
            "message_count": session.message_count,
            "bot_mode": profile.bot_mode,
        }

    def has_active_conversation(self, profile: BotProfile, session: UserSession) -> bool:
        return self.summarize_active_conversation(profile, session)["history_count"] > 0

    def reset_active_conversation(self, profile: BotProfile, session: UserSession) -> None:
        self.store.delete_conversation(
            bot_id=session.bot_id,
            user_id=session.user_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
        )
