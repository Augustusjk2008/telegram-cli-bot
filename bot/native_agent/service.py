from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from bot.chat_identity import chat_session_user_id
from bot.models import (
    BotProfile,
    EXECUTION_MODE_CLI,
    EXECUTION_MODE_NATIVE_AGENT,
    UserSession,
    build_native_agent_model_id,
    normalize_execution_mode as _normalize_execution_mode,
    normalize_native_agent_config,
)
from bot.native_agent.ag_ui_mapper import (
    AgUiTurnState,
    build_run_error_event,
    build_run_finished_event,
    build_run_started_event,
    build_text_message_events,
    build_text_end_event,
    map_event as map_ag_ui_event,
    should_filter_event,
)
from bot.native_agent.aggregator import NativeAgentAggregator
from bot.native_agent.client import NativeAgentClient, NativeAgentClientError
from bot.native_agent.events import is_relevant_event, unwrap_event
from bot.native_agent.server_manager import SERVER_MANAGER, NativeAgentServerHandle
from bot.native_agent.turn_state import NativeAgentTurnState
from bot.web.chat_history_service import ChatHistoryService, StreamingPersistenceBuffer

NATIVE_AGENT_PROVIDER = EXECUTION_MODE_NATIVE_AGENT


def normalize_execution_mode(value: Any, profile: BotProfile | None = None) -> str:
    mode = _normalize_execution_mode(value, default="")
    if not mode and profile is not None:
        mode = _normalize_execution_mode(getattr(profile, "default_execution_mode", ""), default=EXECUTION_MODE_CLI)
    if not mode:
        mode = EXECUTION_MODE_CLI
    if profile is not None:
        supported_modes = list(getattr(profile, "supported_execution_modes", []) or [EXECUTION_MODE_CLI])
        supported = set(supported_modes)
        if mode not in supported:
            default_mode = _normalize_execution_mode(
                getattr(profile, "default_execution_mode", ""),
                default=supported_modes[0] if supported_modes else EXECUTION_MODE_CLI,
            )
            if default_mode in supported:
                return default_mode
            return supported_modes[0] if supported_modes else EXECUTION_MODE_CLI
    return mode


class NativeAgentService:
    def __init__(self) -> None:
        self._server_manager = SERVER_MANAGER

    async def _server_for(self, profile: BotProfile) -> NativeAgentServerHandle:
        try:
            return await self._server_manager.ensure_started(profile)
        except TypeError:
            return await self._server_manager.ensure_started()

    async def _client_for_active_run(self, session: UserSession) -> NativeAgentClient | None:
        with session._lock:
            server_key = str(getattr(session, "native_agent_server_key", "") or "").strip()
        handle = None
        get_existing_by_key = getattr(self._server_manager, "get_existing_by_key", None)
        if server_key and callable(get_existing_by_key):
            handle = await get_existing_by_key(server_key)
        get_existing_for = getattr(self._server_manager, "get_existing_for", None)
        if callable(get_existing_for):
            profile = BotProfile(alias=session.bot_alias, working_dir=session.working_dir)
            handle = handle or await get_existing_for(profile)
        get_existing_for_alias = getattr(self._server_manager, "get_existing_for_alias", None)
        has_alias_lookup = callable(get_existing_for_alias)
        if has_alias_lookup:
            handle = handle or await get_existing_for_alias(session.bot_alias)
        if handle is None and not has_alias_lookup:
            handle = await self._server_manager.get_existing()
        return handle.client() if handle is not None else None

    def _prompt_options(self, profile: BotProfile) -> tuple[str, str]:
        native_agent = normalize_native_agent_config(getattr(profile, "native_agent", {}))
        return (
            build_native_agent_model_id(native_agent),
            str(native_agent.get("opencode_agent") or "").strip(),
        )

    async def _ensure_session_id(self, client: NativeAgentClient, session: UserSession) -> str:
        with session._lock:
            native_session_id = str(session.native_agent_session_id or "").strip()
        if native_session_id:
            try:
                await client.get_session(native_session_id)
            except NativeAgentClientError:
                with session._lock:
                    session.native_agent_session_id = None
                session.persist()
                native_session_id = ""
        if not native_session_id:
            created = await client.create_session(cwd=session.working_dir)
            native_session_id = _extract_session_id(created)
            with session._lock:
                session.native_agent_session_id = native_session_id
            session.persist()
        return native_session_id

    async def abort(self, session: UserSession) -> bool:
        with session._lock:
            session_id = str(session.native_agent_session_id or "").strip()
            if not session.is_processing or not session_id:
                return False
            session.stop_requested = True
        client = await self._client_for_active_run(session)
        if client is None:
            return False
        await client.abort(session_id)
        return True

    async def reply_permission(
        self,
        session: UserSession,
        permission_id: str,
        *,
        approved: bool,
        message: str = "",
    ) -> dict[str, Any]:
        with session._lock:
            session_id = str(session.native_agent_session_id or "").strip()
        if not session_id:
            raise RuntimeError("当前没有原生 agent 会话")
        client = await self._client_for_active_run(session)
        if client is None:
            raise RuntimeError("原生 agent 服务未运行")
        return await client.reply_permission(session_id, permission_id, approved=approved, message=message)

    async def stream_chat(
        self,
        *,
        profile: BotProfile,
        session: UserSession,
        user_text: str,
        prompt_text: str,
        history_service: ChatHistoryService,
        actor: dict[str, Any] | None = None,
        protocol: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        total_started = time.perf_counter()
        user_id = chat_session_user_id(session.user_id)
        with session._lock:
            if session.is_processing:
                raise RuntimeError("当前会话正在处理上一条消息")
            session.native_agent_run_id = f"nar_{uuid.uuid4().hex[:12]}"
            session.stop_requested = False
            session.is_processing = True
            run_id = str(session.native_agent_run_id or "")
        session.touch()
        session.persist()

        turn_handle = None
        live_trace: list[dict[str, Any]] = []
        returncode = 0
        completion_state = "completed"
        error_message = ""
        last_status_signature = ""
        final_text = ""
        reader_task: asyncio.Task[None] | None = None
        wants_ag_ui = str(protocol or "").strip().lower() == "ag-ui"

        try:
            turn_handle = history_service.start_turn(
                profile=profile,
                session=session,
                user_text=user_text,
                native_provider=NATIVE_AGENT_PROVIDER,
                actor=actor,
            )
            server = await self._server_for(profile)
            with session._lock:
                session.native_agent_server_key = str(getattr(server, "key", "") or "")
            client = server.client()
            native_session_id = await self._ensure_session_id(client, session)
            model_id, agent_id = self._prompt_options(profile)
            baseline_message_count = 0
            baseline_known = False
            try:
                baseline_messages = await asyncio.wait_for(client.list_messages(native_session_id), timeout=1.0)
                if isinstance(baseline_messages, list):
                    baseline_message_count = len(baseline_messages)
                    baseline_known = True
            except Exception:
                baseline_message_count = 0
                baseline_known = False

            aggregator = NativeAgentAggregator(user_message_id=f"msg_{uuid.uuid4().hex[:12]}")
            turn_state = NativeAgentTurnState(
                native_session_id=native_session_id,
                user_message_id=aggregator.user_message_id,
                assistant_message_id=turn_handle.assistant_message_id,
                baseline_message_count=baseline_message_count,
                baseline_known=baseline_known,
            )
            persistence_buffer = StreamingPersistenceBuffer(history_service, turn_handle, loop_time=loop.time)
            ag_ui_state = AgUiTurnState(
                thread_id=turn_handle.conversation_id,
                run_id=run_id,
                user_message_id=turn_handle.user_message_id,
                assistant_message_id=turn_handle.assistant_message_id,
            )

            yield {
                "type": "meta",
                "alias": profile.alias,
                "cli_type": profile.cli_type,
                "execution_mode": EXECUTION_MODE_NATIVE_AGENT,
                "native_provider": NATIVE_AGENT_PROVIDER,
                "native_session_id": native_session_id,
                "working_dir": session.working_dir,
            }
            if wants_ag_ui:
                yield {
                    "type": "ag_ui",
                    "event": build_run_started_event(state=ag_ui_state, user_text=user_text),
                }

            event_queue: asyncio.Queue[dict[str, Any] | BaseException | None] = asyncio.Queue()
            event_ready = asyncio.Event()

            async def read_events() -> None:
                try:
                    try:
                        async for raw_event in client.events(global_events=True, ready_event=event_ready):
                            await event_queue.put(raw_event)
                    except TypeError:
                        event_ready.set()
                        async for raw_event in client.events(global_events=True):
                            await event_queue.put(raw_event)
                    await event_queue.put(None)
                except asyncio.CancelledError:
                    raise
                except BaseException as exc:
                    event_ready.set()
                    await event_queue.put(exc)

            reader_task = asyncio.create_task(read_events())
            await event_ready.wait()
            await client.prompt_async(
                native_session_id,
                prompt_text,
                message_id=aggregator.user_message_id,
                model=model_id or None,
                agent=agent_id or None,
            )
            while True:
                try:
                    queued_event = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if turn_state.should_reconcile(now=loop.time(), force=True):
                        try:
                            reconciled = await turn_state.maybe_reconcile(client.list_messages, aggregator, now=loop.time())
                        except Exception:
                            reconciled = {"done": False, "text": ""}
                        reconciled_text = str(reconciled.get("text") or "")
                        if reconciled_text:
                            final_text = reconciled_text
                            history_service.replace_assistant_content(turn_handle, final_text, state="streaming")
                        if reconciled.get("done"):
                            break
                    continue
                if queued_event is None:
                    break
                if isinstance(queued_event, BaseException):
                    raise queued_event
                raw_event = queued_event
                event = unwrap_event(raw_event)
                if event is None:
                    continue
                if event.transport:
                    if turn_state.should_reconcile(now=loop.time()):
                        try:
                            reconciled = await turn_state.maybe_reconcile(client.list_messages, aggregator, now=loop.time())
                        except Exception:
                            reconciled = {"done": False, "text": ""}
                        reconciled_text = str(reconciled.get("text") or "")
                        if reconciled_text:
                            final_text = reconciled_text
                            history_service.replace_assistant_content(turn_handle, final_text, state="streaming")
                        if reconciled.get("done"):
                            break
                    continue
                if not is_relevant_event(event, session_id=native_session_id, cwd=session.working_dir):
                    continue
                result = aggregator.apply(event)
                turn_state.observe(event, result, now=loop.time())
                if wants_ag_ui and not should_filter_event(event):
                    for ag_ui_event in map_ag_ui_event(event=event, result=result, state=ag_ui_state):
                        yield {"type": "ag_ui", "event": ag_ui_event}
                if result.assistant_message_id:
                    ag_ui_state.assistant_message_id = result.assistant_message_id
                    yield {
                        "type": "meta",
                        "native_session_id": native_session_id,
                        "assistant_message_id": result.assistant_message_id,
                    }
                if result.delta:
                    final_text = aggregator.text()
                    history_service.replace_assistant_content(turn_handle, final_text, state="streaming")
                    yield {"type": "delta", "text": result.delta}
                if result.snapshot:
                    final_text = result.snapshot
                    history_service.replace_assistant_content(turn_handle, final_text, state="streaming")
                    yield {"type": "status", "elapsed_seconds": int(loop.time() - started_at), "preview_text": final_text[-800:]}
                for trace_event in result.trace:
                    live_trace.append(trace_event)
                    persistence_buffer.queue_trace(trace_event)
                    persistence_buffer.maybe_flush()
                    yield {"type": "trace", "event": trace_event}
                if result.status:
                    signature = f"{int(loop.time() - started_at)}:{result.status}"
                    if signature != last_status_signature:
                        last_status_signature = signature
                        yield {
                            "type": "status",
                            "elapsed_seconds": int(loop.time() - started_at),
                            "preview_text": result.status[-800:],
                        }
                if result.error:
                    error_message = result.error
                    completion_state = "error"
                    returncode = 1
                    if wants_ag_ui:
                        text_end = build_text_end_event(state=ag_ui_state)
                        if text_end is not None:
                            yield {"type": "ag_ui", "event": text_end}
                        yield {"type": "ag_ui", "event": build_run_error_event(error_message)}
                    break
                with session._lock:
                    stop_requested = bool(session.stop_requested)
                if stop_requested:
                    completion_state = "cancelled"
                    break
                if result.done:
                    break

            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass

            try:
                messages = await client.list_messages(native_session_id)
                reconciled = aggregator.reconcile_messages(turn_state.current_turn_messages(messages))
                if reconciled:
                    final_text = reconciled
            except Exception:
                pass
            final_text = final_text or aggregator.text()
            if completion_state == "cancelled":
                live_trace.append({"kind": "cancelled", "source": "native_agent", "summary": "用户终止输出"})
            if not final_text and completion_state == "completed":
                final_text = "原生 agent 未返回内容"
            if completion_state == "error" and not final_text:
                final_text = error_message or "原生 agent 执行失败"
            persistence_buffer.flush()
            for trace_event in live_trace:
                if trace_event.get("kind") == "cancelled":
                    history_service.append_trace_event(turn_handle, trace_event)
            done_message = history_service.complete_turn(
                turn_handle,
                content=final_text,
                completion_state=completion_state,
                native_session_id=native_session_id,
                error_code=None if completion_state == "completed" else completion_state,
                error_message=None if completion_state == "completed" else (error_message or final_text),
            )
            if wants_ag_ui:
                if final_text and not ag_ui_state.text_started:
                    for ag_ui_event in build_text_message_events(state=ag_ui_state, content=final_text):
                        yield {"type": "ag_ui", "event": ag_ui_event}
                text_end = build_text_end_event(state=ag_ui_state)
                if text_end is not None:
                    yield {"type": "ag_ui", "event": text_end}
                yield {
                    "type": "ag_ui",
                    "event": build_run_finished_event(
                        state=ag_ui_state,
                        completion_state=completion_state,
                        content=final_text,
                    ),
                }
            elapsed_seconds = int(loop.time() - started_at)
            yield {
                "type": "done",
                "output": final_text,
                "message": done_message,
                "elapsed_seconds": elapsed_seconds,
                "returncode": returncode,
                "session": {
                    "bot_alias": profile.alias,
                    "bot_mode": profile.bot_mode,
                    "cli_type": profile.cli_type,
                    "working_dir": session.working_dir,
                    "is_processing": False,
                    "session_ids": {
                        "native_agent_session_id": native_session_id,
                    },
                },
            }
        except asyncio.CancelledError:
            with session._lock:
                session.stop_requested = True
            try:
                if "client" in locals() and "native_session_id" in locals():
                    await client.abort(native_session_id)
            except Exception:
                pass
            raise
        except Exception as exc:
            error_message = str(exc) or "原生 agent 执行失败"
            if turn_handle is not None:
                history_service.complete_turn(
                    turn_handle,
                    content=error_message,
                    completion_state="error",
                    native_session_id=locals().get("native_session_id", ""),
                    error_code="native_agent_error",
                    error_message=error_message,
                )
            if wants_ag_ui:
                yield {"type": "ag_ui", "event": build_run_error_event(error_message)}
            yield {"type": "error", "code": "native_agent_error", "message": f"原生 agent 执行失败: {error_message}"}
        finally:
            if reader_task is not None and not reader_task.done():
                reader_task.cancel()
                try:
                    await reader_task
                except asyncio.CancelledError:
                    pass
            with session._lock:
                session.native_agent_run_id = None
                session.native_agent_server_key = None
                session.is_processing = False
                session.stop_requested = False
                session.process = None
            session.persist()
            _ = user_id, run_id, total_started

    async def run_chat(self, **kwargs: Any) -> dict[str, Any]:
        last_event: dict[str, Any] | None = None
        async for event in self.stream_chat(**kwargs):
            if event.get("type") == "done":
                last_event = event
                break
            if event.get("type") == "error":
                raise RuntimeError(str(event.get("message") or "原生 agent 执行失败"))
        if last_event is None:
            raise RuntimeError("原生 agent 未返回结果")
        return {
            "output": str(last_event.get("output") or ""),
            "message": last_event.get("message"),
            "elapsed_seconds": last_event.get("elapsed_seconds", 0),
            "returncode": last_event.get("returncode", 0),
            "session": last_event.get("session"),
        }


def _extract_session_id(payload: dict[str, Any]) -> str:
    candidates = [payload]
    if isinstance(payload.get("data"), dict):
        candidates.append(payload["data"])
    if isinstance(payload.get("session"), dict):
        candidates.append(payload["session"])
    for item in candidates:
        for key in ("id", "sessionID", "session_id", "sessionId"):
            value = item.get(key)
            if value:
                return str(value)
    raise RuntimeError("原生 agent 未返回 session id")


_SERVICE = NativeAgentService()


def get_native_agent_service() -> NativeAgentService:
    return _SERVICE
