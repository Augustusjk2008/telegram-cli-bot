from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from bot.cli import cli_data_provider
from bot.models import BotProfile, UserSession
from bot.web.async_chat_store import AsyncChatStore
from bot.web.chat_store import ChatStore, ChatTurnHandle
from bot.web.native_history_builder import resolve_native_trace_for_turn


def _session_epoch(session: UserSession) -> int:
    try:
        return max(0, int(getattr(session, "session_epoch", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _active_conversation_id(session: UserSession) -> str:
    return str(getattr(session, "active_conversation_id", "") or "").strip()


class StreamingPersistenceBuffer:
    def __init__(
        self,
        service: "ChatHistoryService",
        handle: ChatTurnHandle,
        *,
        loop,
        flush_interval_seconds: float = 0.25,
        preview_flush_interval_seconds: float = 2.0,
        max_batch_events: int = 32,
        max_batch_bytes: int = 16 * 1024,
    ) -> None:
        self._service = service
        self._handle = handle
        self._loop = loop
        self._loop_time = loop.time
        self._flush_interval_seconds = max(0.05, float(flush_interval_seconds))
        self._last_flush_at = float(self._loop_time())
        self._preview_flush_interval_seconds = max(
            self._flush_interval_seconds,
            float(preview_flush_interval_seconds),
        )
        self._last_preview_flush_at = self._last_flush_at
        self._max_batch_events = max(1, int(max_batch_events))
        self._max_batch_bytes = max(1024, int(max_batch_bytes))
        self._pending_preview: str | None = None
        self._last_persisted_preview: str | None = None
        self._pending_trace: list[dict[str, Any]] = []
        self._pending_trace_bytes = 0
        self._flush_task: asyncio.Task[None] | None = None
        self._closing = False
        self._lock = threading.Lock()
        self.flush_count = 0
        self.preview_flush_count = 0
        self.trace_flush_count = 0

    def queue_preview(self, preview_text: str) -> None:
        text = str(preview_text or "").strip()[-800:]
        if text:
            with self._lock:
                if text == self._pending_preview or (
                    self._pending_preview is None
                    and text == self._last_persisted_preview
                ):
                    return
                self._pending_preview = text[-800:]

    def queue_trace(self, event: dict[str, Any]) -> None:
        if isinstance(event, dict):
            payload = dict(event)
            payload_bytes = len(json.dumps(payload, ensure_ascii=False))
            with self._lock:
                self._pending_trace.append(payload)
                self._pending_trace_bytes += payload_bytes

    def maybe_flush(self) -> None:
        if self._should_flush():
            self.flush()

    def flush(self) -> None:
        self._schedule_flush(final=False)

    async def close(self) -> None:
        self._closing = True
        try:
            while True:
                task = self._schedule_flush(final=True)
                if task is None:
                    return
                await task
                with self._lock:
                    if self._flush_task is None and not self._pending_preview and not self._pending_trace:
                        return
        finally:
            self._closing = False

    def _should_flush(self) -> bool:
        with self._lock:
            if not self._pending_preview and not self._pending_trace:
                return False
            now = float(self._loop_time())
            return self._preview_is_due_locked(now) or self._trace_is_due_locked(now)

    def _preview_is_due_locked(self, now: float, *, final: bool = False) -> bool:
        return bool(
            self._pending_preview
            and (
                final
                or now - self._last_preview_flush_at >= self._preview_flush_interval_seconds
            )
        )

    def _trace_is_due_locked(self, now: float, *, final: bool = False) -> bool:
        if not self._pending_trace:
            return False
        return bool(
            final
            or len(self._pending_trace) >= self._max_batch_events
            or self._pending_trace_bytes >= self._max_batch_bytes
            or now - self._last_flush_at >= self._flush_interval_seconds
        )

    def _schedule_flush(self, *, final: bool) -> asyncio.Task[None] | None:
        with self._lock:
            if final:
                self._closing = True
            if self._flush_task is not None:
                return self._flush_task
            if not self._pending_preview and not self._pending_trace:
                return None
            self._flush_task = self._loop.create_task(self._run_flush())
            return self._flush_task

    async def _run_flush(self) -> None:
        try:
            while True:
                preview: str | None = None
                trace: list[dict[str, Any]] = []
                with self._lock:
                    now = float(self._loop_time())
                    final = self._closing
                    preview_due = self._preview_is_due_locked(now, final=final)
                    trace_due = self._trace_is_due_locked(now, final=final)
                    if not preview_due and not trace_due:
                        return
                    if preview_due:
                        preview = self._pending_preview
                        self._pending_preview = None
                    if trace_due:
                        trace = list(self._pending_trace)
                        self._pending_trace.clear()
                        self._pending_trace_bytes = 0
                if not preview and not trace:
                    return
                await asyncio.to_thread(self._flush_batch, preview, trace)
                with self._lock:
                    flushed_at = float(self._loop_time())
                    if preview:
                        self._last_persisted_preview = preview
                        self._last_preview_flush_at = flushed_at
                        if self._pending_preview == preview:
                            self._pending_preview = None
                    if trace:
                        self._last_flush_at = flushed_at
        finally:
            with self._lock:
                self._flush_task = None
                if not self._pending_preview and not self._pending_trace:
                    self._closing = False

    def _flush_batch(self, preview: str | None, trace: list[dict[str, Any]]) -> None:
        if preview:
            self._service.replace_assistant_preview(self._handle, preview)
            self.preview_flush_count += 1
        if trace:
            self._service.append_trace_events(self._handle, trace)
            self.trace_flush_count += 1
        self.flush_count += 1


class ChatHistoryService:
    def __init__(
        self,
        store: ChatStore,
        *,
        native_provider_filter: str | None = None,
        native_provider_exclude: str | None = None,
    ) -> None:
        self.store = store
        self.async_store = AsyncChatStore(store)
        self.native_provider_filter = str(native_provider_filter or "").strip() or None
        self.native_provider_exclude = str(native_provider_exclude or "").strip() or None

    def _matches_native_provider(self, native_provider: str | None) -> bool:
        provider = str(native_provider or "").strip()
        if self.native_provider_filter is not None and provider != self.native_provider_filter:
            return False
        if self.native_provider_exclude is not None and provider == self.native_provider_exclude:
            return False
        return True

    def reconcile_idle_streaming_turns(self, session: UserSession) -> int:
        with session._lock:
            is_processing = bool(session.is_processing)
        if is_processing:
            return 0
        return self.store.mark_stale_streaming_turns(
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
        )

    def _should_attempt_trace_recovery(self, context: dict[str, Any]) -> bool:
        if bool(context.get("is_voice")):
            return False
        if str(context.get("trace_recovery_status") or "") in {"no_trace", "recovered", "kept_existing"}:
            return False
        if str(context.get("role") or "") != "assistant":
            return False
        if str(context.get("completion_state") or "") not in {"completed", "cancelled"}:
            return False
        raw_provider = str(context.get("native_provider") or "").strip().lower()
        provider = raw_provider if raw_provider == "native_agent" else cli_data_provider(raw_provider)
        if provider not in {"codex", "claude"}:
            return False
        return bool(str(context.get("native_session_id") or "").strip())

    def ensure_voice_turn(
        self,
        session: UserSession,
        *,
        bot_alias: str,
        task_submission_key: str,
        codex_turn_id: str,
        realtime_session_id: str = "",
        actor: dict[str, Any] | None = None,
        conversation_id: str | None = None,
    ) -> ChatTurnHandle:
        active_conversation_id = str(
            conversation_id if conversation_id is not None else _active_conversation_id(session)
        ).strip()
        if active_conversation_id:
            try:
                active_provider = self.store.get_conversation_native_provider(active_conversation_id)
            except KeyError:
                active_provider = ""
            if str(active_provider or "").strip().lower() != "codex":
                with session._lock:
                    session.active_conversation_id = None
                session.persist()
                active_conversation_id = ""
        handle = self.store.ensure_voice_turn(
            bot_id=session.bot_id,
            bot_alias=bot_alias,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            task_submission_key=task_submission_key,
            codex_turn_id=codex_turn_id,
            realtime_session_id=realtime_session_id,
            actor=actor,
            conversation_id=active_conversation_id or None,
        )
        if _active_conversation_id(session) != handle.conversation_id:
            with session._lock:
                session.active_conversation_id = handle.conversation_id
            session.persist()
        return handle

    async def ensure_voice_turn_async(
        self,
        session: UserSession,
        *,
        bot_alias: str,
        task_submission_key: str,
        codex_turn_id: str,
        realtime_session_id: str = "",
        actor: dict[str, Any] | None = None,
        conversation_id: str | None = None,
    ) -> ChatTurnHandle:
        active_conversation_id = str(
            conversation_id if conversation_id is not None else _active_conversation_id(session)
        ).strip()
        if active_conversation_id:
            try:
                active_provider = self.store.get_conversation_native_provider(active_conversation_id)
            except KeyError:
                active_provider = ""
            if str(active_provider or "").strip().lower() != "codex":
                with session._lock:
                    session.active_conversation_id = None
                session.persist()
                active_conversation_id = ""
        handle = await self.async_store.ensure_voice_turn(
            bot_id=session.bot_id,
            bot_alias=bot_alias,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            task_submission_key=task_submission_key,
            codex_turn_id=codex_turn_id,
            realtime_session_id=realtime_session_id,
            actor=actor,
            conversation_id=active_conversation_id or None,
        )
        if _active_conversation_id(session) != handle.conversation_id:
            with session._lock:
                session.active_conversation_id = handle.conversation_id
            session.persist()
        return handle

    @staticmethod
    def _voice_event_args(
        handle_or_session: ChatTurnHandle | UserSession,
        event_or_handle: dict[str, Any] | ChatTurnHandle,
        event: dict[str, Any] | None,
    ) -> tuple[ChatTurnHandle, dict[str, Any]]:
        if event is None:
            if not isinstance(handle_or_session, ChatTurnHandle) or not isinstance(event_or_handle, dict):
                raise TypeError("record_voice_event expects (handle, event) or (session, handle, event)")
            return handle_or_session, event_or_handle
        if not isinstance(event_or_handle, ChatTurnHandle):
            raise TypeError("record_voice_event expects a ChatTurnHandle")
        return event_or_handle, event

    def record_voice_event(
        self,
        handle_or_session: ChatTurnHandle | UserSession,
        event_or_handle: dict[str, Any] | ChatTurnHandle,
        event: dict[str, Any] | None = None,
    ) -> bool:
        handle, payload = self._voice_event_args(handle_or_session, event_or_handle, event)
        return self.store.record_voice_event(handle, payload)

    async def record_voice_event_async(
        self,
        handle_or_session: ChatTurnHandle | UserSession,
        event_or_handle: dict[str, Any] | ChatTurnHandle,
        event: dict[str, Any] | None = None,
    ) -> bool:
        handle, payload = self._voice_event_args(handle_or_session, event_or_handle, event)
        return await self.async_store.record_voice_event(handle, payload)

    def get_voice_task(self, handle: ChatTurnHandle) -> dict[str, Any]:
        return self.store.get_voice_task(handle)

    async def get_voice_task_async(self, handle: ChatTurnHandle) -> dict[str, Any]:
        return await self.async_store.get_voice_task(handle)

    def find_voice_steer_request(
        self,
        turn_id: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        return self.store.find_voice_steer_request(turn_id, request_id)

    async def find_voice_steer_request_async(
        self,
        turn_id: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        return await self.async_store.find_voice_steer_request(turn_id, request_id)

    def update_voice_transcript(
        self,
        handle: ChatTurnHandle,
        *,
        role: str,
        transcript: str,
        is_final: bool = False,
        item_id: str = "",
    ) -> bool:
        return self.store.update_voice_transcript(
            handle,
            role=role,
            transcript=transcript,
            is_final=is_final,
            item_id=item_id,
        )

    async def update_voice_transcript_async(
        self,
        handle: ChatTurnHandle,
        *,
        role: str,
        transcript: str,
        is_final: bool = False,
        item_id: str = "",
    ) -> bool:
        return await self.async_store.update_voice_transcript(
            handle,
            role=role,
            transcript=transcript,
            is_final=is_final,
            item_id=item_id,
        )

    def append_voice_trace(self, handle: ChatTurnHandle, trace_events: list[dict[str, Any]]) -> bool:
        return self.store.append_voice_trace(handle, trace_events)

    async def append_voice_trace_async(self, handle: ChatTurnHandle, trace_events: list[dict[str, Any]]) -> bool:
        return await self.async_store.append_voice_trace(handle, trace_events)

    def complete_voice_turn(
        self,
        handle: ChatTurnHandle,
        *,
        content: str = "",
        completion_state: str = "completed",
        native_session_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        context_usage: dict[str, Any] | None = None,
        task_state: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        return self.store.complete_voice_turn(
            handle,
            content=content,
            completion_state=completion_state,
            native_session_id=native_session_id,
            error_code=error_code,
            error_message=error_message,
            context_usage=context_usage,
            task_state=task_state,
            state=state,
        )

    async def complete_voice_turn_async(
        self,
        handle: ChatTurnHandle,
        *,
        content: str = "",
        completion_state: str = "completed",
        native_session_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        context_usage: dict[str, Any] | None = None,
        task_state: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        return await self.async_store.complete_voice_turn(
            handle,
            content=content,
            completion_state=completion_state,
            native_session_id=native_session_id,
            error_code=error_code,
            error_message=error_message,
            context_usage=context_usage,
            task_state=task_state,
            state=state,
        )

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

        provider = cli_data_provider(str(context.get("native_provider") or ""))
        turn_id = str(context.get("turn_id") or "")
        recovered = resolve_native_trace_for_turn(
            provider,
            str(context.get("native_session_id") or ""),
            user_text=str(context.get("user_text") or ""),
            assistant_text=str(context.get("assistant_text") or ""),
            cwd_hint=str(context.get("working_dir") or "") or None,
        )
        if not self._should_replace_trace(context, recovered):
            status = "kept_existing" if int(context.get("trace_count") or 0) > 0 else "no_trace"
            self.store.mark_trace_recovery_attempted(turn_id, status=status)
            return False
        self.store.replace_trace_events(turn_id, recovered["trace"])
        self.store.mark_trace_recovery_attempted(turn_id, status="recovered")
        return True

    def start_turn(
        self,
        *,
        profile: BotProfile,
        session: UserSession,
        user_text: str,
        native_provider: str,
        actor: dict[str, Any] | None = None,
    ) -> ChatTurnHandle:
        active_conversation_id = _active_conversation_id(session)
        if active_conversation_id:
            try:
                active_provider = self.store.get_conversation_native_provider(active_conversation_id)
            except KeyError:
                active_provider = ""
            if str(active_provider or "").strip().lower() != str(native_provider or "").strip().lower():
                with session._lock:
                    session.active_conversation_id = None
                session.persist()
                active_conversation_id = ""
        had_active_conversation = bool(active_conversation_id)
        handle = self.store.begin_turn(
            bot_id=session.bot_id,
            bot_alias=session.bot_alias,
            user_id=session.user_id,
            agent_id=session.agent_id,
            cli_type=profile.cli_type,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            user_text=user_text,
            native_provider=native_provider,
            conversation_id=active_conversation_id or None,
            agent_prompt_hash=getattr(session, "agent_prompt_hash_seen", None),
            actor=actor,
        )
        if not had_active_conversation:
            with session._lock:
                session.active_conversation_id = handle.conversation_id
            session.persist()
        return handle

    def replace_assistant_preview(self, handle: ChatTurnHandle, preview_text: str) -> None:
        self.store.replace_assistant_content(handle, preview_text[-800:], state="streaming")

    def get_running_reply(self, session: UserSession) -> dict[str, Any] | None:
        return self.store.get_running_reply(
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
        )

    async def get_running_reply_async(self, session: UserSession) -> dict[str, Any] | None:
        return await self.async_store.get_running_reply(
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
        )

    def append_user_message_to_turn(
        self,
        session: UserSession,
        *,
        turn_id: str,
        conversation_id: str,
        user_text: str,
        agent_input_text: str | None = None,
        translation: dict[str, Any] | None = None,
        actor: dict[str, Any] | None = None,
        request_id: str | None = None,
        local_message_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        return self.store.append_user_message_to_turn(
            turn_id=turn_id,
            conversation_id=conversation_id,
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            user_text=user_text,
            agent_input_text=agent_input_text,
            translation=translation,
            actor=actor,
            request_id=request_id,
            local_message_id=local_message_id,
            message_id=message_id,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
        )

    async def append_user_message_to_turn_async(
        self,
        session: UserSession,
        *,
        turn_id: str,
        conversation_id: str,
        user_text: str,
        agent_input_text: str | None = None,
        translation: dict[str, Any] | None = None,
        actor: dict[str, Any] | None = None,
        request_id: str | None = None,
        local_message_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.async_store.run_write(
            self.append_user_message_to_turn,
            session,
            turn_id=turn_id,
            conversation_id=conversation_id,
            user_text=user_text,
            agent_input_text=agent_input_text,
            translation=translation,
            actor=actor,
            request_id=request_id,
            local_message_id=local_message_id,
            message_id=message_id,
        )

    def update_context_usage(self, handle: ChatTurnHandle, context_usage: dict[str, Any] | None) -> bool:
        return self.store.update_context_usage(handle.turn_id, context_usage)

    async def update_context_usage_async(self, handle: ChatTurnHandle, context_usage: dict[str, Any] | None) -> bool:
        return await asyncio.to_thread(self.update_context_usage, handle, context_usage)

    async def get_latest_native_session_context_usage_async(
        self,
        *,
        native_provider: str,
        native_session_id: str,
    ) -> dict[str, Any] | None:
        return await self.async_store.run_read(
            self.store.get_latest_native_session_context_usage,
            native_provider=native_provider,
            native_session_id=native_session_id,
        )

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

    def append_trace_events(self, handle: ChatTurnHandle, events: list[dict[str, Any]]) -> None:
        self.store.append_trace_events(handle.turn_id, events)

    def replace_assistant_content(self, handle: ChatTurnHandle, content: str, *, state: str = "streaming") -> None:
        self.store.replace_assistant_content(handle, content, state=state)

    def replace_message_content(self, message_id: str, content: str, *, state: str = "done") -> dict[str, Any]:
        return self.store.replace_message_content(message_id, content, state=state)

    def update_message_translation(
        self,
        message_id: str,
        *,
        source_digest: str,
        translation: dict[str, Any] | None,
        agent_input_text: str | None = None,
        retry_failed_answer: bool = False,
    ) -> bool:
        return self.store.update_message_translation(
            message_id,
            source_digest=source_digest,
            translation=translation,
            agent_input_text=agent_input_text,
            retry_failed_answer=retry_failed_answer,
        )

    def get_scoped_message(self, session: UserSession, message_id: str) -> dict[str, Any] | None:
        return self.store.get_scoped_message(
            message_id, bot_id=session.bot_id, user_id=session.user_id,
            agent_id=session.agent_id, working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
        )

    async def update_message_translation_async(
        self,
        message_id: str,
        *,
        source_digest: str,
        translation: dict[str, Any] | None,
        agent_input_text: str | None = None,
    ) -> bool:
        return await self.async_store.update_message_translation(
            message_id,
            source_digest=source_digest,
            translation=translation,
            agent_input_text=agent_input_text,
        )

    def complete_turn(
        self,
        handle: ChatTurnHandle,
        *,
        content: str,
        completion_state: str,
        native_session_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        context_usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.complete_turn(
            handle,
            content=content,
            completion_state=completion_state,
            native_session_id=native_session_id,
            error_code=error_code,
            error_message=error_message,
            context_usage=context_usage,
        )

    def list_history(self, profile: BotProfile, session: UserSession, limit: int = 50) -> list[dict[str, Any]]:
        self.reconcile_idle_streaming_turns(session)
        items = self.store.list_active_history(
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
            limit=limit,
        )
        if items and not _active_conversation_id(session):
            try:
                context = self.store.get_trace_recovery_context(str(items[-1].get("id") or ""))
            except KeyError:
                context = {}
            conversation_id = str(context.get("conversation_id") or "")
            if conversation_id:
                deepseek_conversation = None
                if cli_data_provider(profile.cli_type) == "deepseek" and context.get("native_provider") == "deepseek":
                    deepseek_conversation = self.store.get_conversation(conversation_id)
                with session._lock:
                    session.active_conversation_id = conversation_id
                    if deepseek_conversation is not None:
                        session.deepseek_session_id = str(deepseek_conversation.get("native_session_id") or "").strip() or None
                session.persist()
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
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
            limit=limit,
        )

    async def list_history_async(
        self,
        profile: BotProfile,
        session: UserSession,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return await self.async_store.run_write(
            self.list_history,
            profile,
            session,
            limit,
        )

    def list_history_delta(
        self,
        profile: BotProfile,
        session: UserSession,
        *,
        revision: int,
        cursor: str | int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self.reconcile_idle_streaming_turns(session)
        return self.store.get_scoped_history_delta(
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
            revision=revision,
            cursor=cursor,
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
        if not self._matches_native_provider(context.get("native_provider")):
            return None
        self._recover_trace_for_context(context)
        try:
            return self.store.get_message_trace(message_id)
        except KeyError:
            return None

    async def get_message_trace_async(
        self,
        profile: BotProfile,
        session: UserSession,
        message_id: str,
    ) -> dict[str, Any] | None:
        return await self.async_store.run_write(
            self.get_message_trace,
            profile,
            session,
            message_id,
        )

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
        try:
            if self.store.get_trace_recovery_context(handle.assistant_message_id).get("is_voice"):
                return False
        except KeyError:
            return False
        provider = cli_data_provider(getattr(profile, "cli_type", ""))
        session_id = str(native_session_id or "").strip()
        if provider not in {"codex", "claude"} or not session_id:
            return False

        try:
            current_trace = self.store.get_message_trace(handle.assistant_message_id)
            user_message = self.store.get_message(handle.user_message_id)
        except KeyError:
            return False

        input_text = user_message.get("agent_input_text")
        recovered = resolve_native_trace_for_turn(
            provider,
            session_id,
            user_text=input_text if input_text is not None else user_message["content"],
            assistant_text=assistant_text,
            cwd_hint=session.working_dir,
        )
        if not self._should_replace_trace(current_trace, recovered):
            return False
        self.store.replace_trace_events(handle.turn_id, recovered["trace"])
        return True

    def build_session_snapshot(self, profile: BotProfile, session: UserSession) -> dict[str, Any]:
        self.reconcile_idle_streaming_turns(session)
        with session._lock:
            is_processing = bool(session.is_processing)
        running_reply = self.store.get_running_reply(
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
            conversation_id=_active_conversation_id(session) or None,
            native_provider=self.native_provider_filter,
            native_provider_exclude=self.native_provider_exclude,
        )
        if not is_processing and not (running_reply and running_reply.get("voice")):
            running_reply = None
        return {
            "bot_alias": profile.alias,
            "cli_type": profile.cli_type,
            "cli_path": profile.cli_path,
            "working_dir": session.working_dir,
            "message_count": session.message_count,
            "history_count": self.store.count_history(
                bot_id=session.bot_id,
                user_id=session.user_id,
                agent_id=session.agent_id,
                working_dir=session.working_dir,
                session_epoch=_session_epoch(session),
                conversation_id=_active_conversation_id(session) or None,
                native_provider=self.native_provider_filter,
                native_provider_exclude=self.native_provider_exclude,
            ),
            "is_processing": is_processing,
            "running_reply": running_reply,
            "session_ids": {
                "codex_session_id": session.codex_session_id,
                "claude_session_id": session.claude_session_id,
                "antigravity_conversation_id": session.antigravity_conversation_id,
                "deepseek_session_id": getattr(session, "deepseek_session_id", None),
                "native_agent_session_id": session.native_agent_session_id,
                "claude_session_initialized": session.claude_session_initialized,
            },
            "active_conversation_id": _active_conversation_id(session),
        }

    async def build_session_snapshot_async(
        self,
        profile: BotProfile,
        session: UserSession,
    ) -> dict[str, Any]:
        return await self.async_store.run_write(
            self.build_session_snapshot,
            profile,
            session,
        )

    def summarize_active_conversation(self, session: UserSession) -> dict[str, Any]:
        return {
            "current_working_dir": session.working_dir,
            "history_count": self.store.count_history(
                bot_id=session.bot_id,
                user_id=session.user_id,
                agent_id=session.agent_id,
                working_dir=session.working_dir,
                session_epoch=_session_epoch(session),
                conversation_id=_active_conversation_id(session) or None,
                native_provider=self.native_provider_filter,
                native_provider_exclude=self.native_provider_exclude,
            ),
            "message_count": session.message_count,
        }

    async def summarize_active_conversation_async(
        self,
        session: UserSession,
    ) -> dict[str, Any]:
        return await self.async_store.run_read(
            self.summarize_active_conversation,
            session,
        )

    def has_active_conversation(self, session: UserSession) -> bool:
        return self.summarize_active_conversation(session)["history_count"] > 0

    def reset_active_conversation(self, session: UserSession) -> None:
        conversation_id = _active_conversation_id(session)
        if conversation_id:
            self.store.delete_conversation_by_id(conversation_id)
            with session._lock:
                session.active_conversation_id = None
            session.persist()
            return
        self.store.delete_conversation(
            bot_id=session.bot_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            working_dir=session.working_dir,
            session_epoch=_session_epoch(session),
        )

    async def reset_active_conversation_async(
        self,
        session: UserSession,
    ) -> None:
        await self.async_store.run_write(
            self.reset_active_conversation,
            session,
        )
