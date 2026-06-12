from __future__ import annotations

import asyncio
from contextlib import suppress
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from bot.chat_identity import chat_session_user_id
from bot import config
from bot.models import (
    BotProfile,
    EXECUTION_MODE_CLI,
    EXECUTION_MODE_NATIVE_AGENT,
    UserSession,
    build_native_agent_model_id,
    normalize_execution_mode as _normalize_execution_mode,
)
from bot.native_agent.configuration import effective_native_agent_config, validate_native_agent_model_config
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
from bot.native_agent.context_usage import resolve_native_agent_context_usage
from bot.native_agent.events import is_relevant_event, unwrap_event
from bot.native_agent.legacy_migration import migrate_native_session_meta
from bot.native_agent.pi_rpc_preflight import PiWindowsPreflightRequest, run_pi_windows_preflight
from bot.native_agent.pi_rpc_client import PiRpcRunError
from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key
from bot.native_agent.pi_session_runtime import (
    PiSessionRuntime,
    PiSessionRuntimeRegistry,
    PiSessionRuntimeRequest,
    build_pi_owner_key,
    build_pi_runtime_key,
)
from bot.native_agent.pi_workspace_history import PiWorkspaceHistory, WorkspaceHistoryStatus
from bot.native_agent.run_events import extract_native_context_usage, extract_native_session_id, native_json_to_events
from bot.native_agent.turn_state import NativeAgentTurnState
from bot.web.chat_history_service import ChatHistoryService, StreamingPersistenceBuffer

NATIVE_AGENT_PROVIDER = EXECUTION_MODE_NATIVE_AGENT
NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS = 1000.0
NATIVE_AGENT_NO_PROGRESS_MESSAGE = "原生 agent 长时间无输出或进展"


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
        self._runtime_registry = PiSessionRuntimeRegistry()
        self._pi_session_store = PiSessionStore()
        self._workspace_history = PiWorkspaceHistory()

    def _prompt_options(self, profile: BotProfile) -> tuple[str, str, str]:
        native_agent = effective_native_agent_config(getattr(profile, "native_agent", {}))
        validate_native_agent_model_config(native_agent)
        return (
            build_native_agent_model_id(native_agent),
            str(native_agent.get("pi_agent") or "").strip(),
            str(native_agent.get("reasoning_effort") or "").strip(),
        )

    def _pi_record_key(self, session: UserSession, user_id: int, conversation_id: str) -> str:
        return pi_session_key(
            cwd=session.working_dir,
            bot_id=int(session.bot_id or 0),
            user_id=int(user_id),
            conversation_id=conversation_id,
        )

    def _load_or_create_pi_record(
        self,
        *,
        key: str,
        session: UserSession,
        conversation_id: str,
        pi_session_id: str = "",
        session_meta: dict[str, str] | None = None,
    ) -> PiSessionRecord:
        record = self._pi_session_store.get(key)
        if record is not None:
            if pi_session_id and not record.pi_session_id:
                record.pi_session_id = pi_session_id
                record = self._pi_session_store.upsert(record)
            return record
        record = PiSessionRecord(
            key=key,
            cwd=session.working_dir,
            conversation_id=conversation_id,
            pi_session_id=str(pi_session_id or "").strip(),
            session_meta=dict(session_meta or {}),
        )
        return self._pi_session_store.upsert(record)

    def _seed_runtime_from_record(self, runtime: PiSessionRuntime, record: PiSessionRecord) -> None:
        runtime.state.native_session_id = str(record.pi_session_id or runtime.state.native_session_id or "").strip()
        current_head = str(
            record.workspace_history_head
            or getattr(runtime.state, "workspace_history_head", "")
            or getattr(runtime, "workspace_history_head", "")
            or ""
        ).strip()
        runtime.state.workspace_history_head = current_head
        runtime.state.linear_index = max(0, int(record.linear_index or 0))

    def _workspace_meta(self, record: PiSessionRecord | None, runtime: PiSessionRuntime | None = None) -> dict[str, Any]:
        head = str((record.workspace_history_head if record else "") or "").strip()
        linear_index = int((record.linear_index if record else 0) or 0)
        degraded = bool(record.degraded) if record is not None else False
        degraded_reason = str(record.degraded_reason or "") if record is not None else ""
        if runtime is not None:
            head = head or str(getattr(runtime.state, "workspace_history_head", "") or "").strip()
            linear_index = max(linear_index, int(getattr(runtime.state, "linear_index", 0) or 0))
        return {
            "workspace_history_head": head,
            "linear_index": linear_index,
            "rollback_supported": bool(head and not degraded),
            "degraded": degraded,
            "degraded_reason": degraded_reason,
        }

    async def rollback_workspace_history(
        self,
        *,
        profile: BotProfile,
        session: UserSession,
        conversation_id: str,
        target_head: str,
        native_session_id: str = "",
    ) -> WorkspaceHistoryStatus:
        model_id, agent_id, reasoning_effort = self._prompt_options(profile)
        native_agent_config = effective_native_agent_config(getattr(profile, "native_agent", {}))
        user_id = chat_session_user_id(session.user_id)
        runtime = await self._runtime_registry.open_or_create(
            PiSessionRuntimeRequest(
                runtime_key=build_pi_runtime_key(
                    bot_id=int(session.bot_id or 0),
                    user_id=int(user_id),
                    conversation_id=conversation_id,
                ),
                owner_key=build_pi_owner_key(bot_id=int(session.bot_id or 0), user_id=int(user_id)),
                conversation_id=conversation_id,
                cwd=session.working_dir,
                command=str(native_agent_config.get("pi_command") or config.NATIVE_AGENT_PI_COMMAND or config.NATIVE_AGENT_COMMAND or "pi"),
                model=model_id,
                agent_id=agent_id,
                reasoning_effort=reasoning_effort,
                native_session_id=native_session_id,
            )
        )
        key = self._pi_record_key(session, user_id, conversation_id)
        record = self._pi_session_store.get(key)
        if record is not None:
            self._seed_runtime_from_record(runtime, record)
        return await self._workspace_history.rollback(runtime, target_head=target_head)

    async def abort(self, session: UserSession) -> bool:
        with session._lock:
            if not session.is_processing:
                return False
            session.stop_requested = True
            runtime_id = str(session.native_agent_server_key or "").strip()
            process = session.process
        runtime = self._runtime_registry.get_by_runtime_id(runtime_id) if runtime_id else None
        if runtime is not None:
            return await runtime.abort()
        if process is None or process.poll() is not None:
            return False
        try:
            process.terminate()
            return True
        except Exception:
            return False

    async def reply_permission(
        self,
        session: UserSession,
        permission_id: str,
        *,
        approved: bool,
        message: str = "",
    ) -> dict[str, Any]:
        with session._lock:
            runtime_id = str(session.native_agent_server_key or "").strip()
        runtime = self._runtime_registry.get_by_runtime_id(runtime_id) if runtime_id else None
        if runtime is None:
            raise RuntimeError("原生 agent 权限请求已失效，请刷新后重试")
        return await runtime.reply_permission(permission_id, approved=approved, message=message)

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
        cluster_run_id: str = "",
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
        last_progress_at = started_at
        last_progress_signature = ""
        wants_ag_ui = str(protocol or "").strip().lower() == "ag-ui"
        normalized_cluster_run_id = str(cluster_run_id or "").strip()
        native_session_id = ""
        context_run_usage: dict[str, Any] = {}
        active_runtime: PiSessionRuntime | None = None
        pi_record_key = ""
        pi_record: PiSessionRecord | None = None
        workspace_history_enabled = False
        session_binding_invalidated = False

        try:
            if not config.NATIVE_AGENT_ENABLED:
                raise RuntimeError("原生 agent 未启用")
            try:
                history_items = history_service.list_history(profile, session, limit=12)
            except Exception:
                history_items = []
            turn_handle = history_service.start_turn(
                profile=profile,
                session=session,
                user_text=user_text,
                native_provider=NATIVE_AGENT_PROVIDER,
                actor=actor,
            )
            model_id, agent_id, reasoning_effort = self._prompt_options(profile)
            native_agent_config = effective_native_agent_config(getattr(profile, "native_agent", {}))
            workspace_history_enabled = bool(native_agent_config.get("workspace_history_enabled", True))
            pi_command = str(
                native_agent_config.get("pi_command")
                or config.NATIVE_AGENT_PI_COMMAND
                or config.NATIVE_AGENT_COMMAND
                or "pi"
            ).strip() or "pi"
            preflight = run_pi_windows_preflight(
                PiWindowsPreflightRequest(
                    cwd=session.working_dir,
                    pi_command=pi_command,
                    workspace_history_enabled=workspace_history_enabled,
                )
            )
            desired_meta = _native_session_meta(
                cwd=session.working_dir,
                model_id=model_id,
                pi_agent=agent_id,
                reasoning_effort=reasoning_effort,
            )
            try:
                conversation_native = history_service.store.get_conversation_native_session(turn_handle.conversation_id)
            except Exception:
                conversation_native = {}
            requested_session_id = str(conversation_native.get("session_id") or "").strip()
            stored_meta = conversation_native.get("meta") if isinstance(conversation_native.get("meta"), dict) else {}
            if requested_session_id and _native_session_meta_mismatch(stored_meta, desired_meta):
                history_service.store.set_conversation_native_session(turn_handle.conversation_id, None, None)
                history_service.store.invalidate_conversation_workspace_history(turn_handle.conversation_id)
                requested_session_id = ""
                session_binding_invalidated = True
            if requested_session_id:
                native_session_id = requested_session_id
                with session._lock:
                    session.native_agent_session_id = native_session_id
                session.persist()

            pi_record_key = self._pi_record_key(session, user_id, turn_handle.conversation_id)
            pi_record = self._load_or_create_pi_record(
                key=pi_record_key,
                session=session,
                conversation_id=turn_handle.conversation_id,
                pi_session_id=native_session_id,
                session_meta=desired_meta,
            )
            if _native_session_meta_mismatch(pi_record.session_meta, desired_meta):
                pi_record = self._pi_session_store.invalidate_binding(pi_record_key, "binding changed")
                history_service.store.set_conversation_native_session(turn_handle.conversation_id, None, None)
                history_service.store.invalidate_conversation_workspace_history(turn_handle.conversation_id)
                native_session_id = ""
                requested_session_id = ""
                session_binding_invalidated = True
                with session._lock:
                    session.native_agent_session_id = None
                session.persist()
            if pi_record.session_meta != desired_meta:
                pi_record.session_meta = dict(desired_meta)
                pi_record = self._pi_session_store.upsert(pi_record)
            if pi_record.pi_session_id:
                native_session_id = pi_record.pi_session_id
                with session._lock:
                    session.native_agent_session_id = native_session_id
                session.persist()

            aggregator = NativeAgentAggregator(user_message_id=f"msg_{uuid.uuid4().hex[:12]}")
            turn_state = NativeAgentTurnState(
                native_session_id=native_session_id,
                user_message_id=aggregator.user_message_id,
                assistant_message_id=turn_handle.assistant_message_id,
                baseline_message_count=0,
                baseline_known=False,
            )
            persistence_buffer = StreamingPersistenceBuffer(history_service, turn_handle, loop_time=loop.time)
            ag_ui_state = AgUiTurnState(
                thread_id=turn_handle.conversation_id,
                run_id=run_id,
                user_message_id=turn_handle.user_message_id,
                assistant_message_id=turn_handle.assistant_message_id,
            )
            if not bool(preflight.get("ok")):
                error_message = str(preflight.get("message") or "Pi 运行前置检查失败")
                history_service.complete_turn(
                    turn_handle,
                    content=error_message,
                    completion_state="error",
                    native_session_id=native_session_id,
                    error_code=str(preflight.get("code") or "pi_preflight_failed"),
                    error_message=error_message,
                )
                if wants_ag_ui:
                    yield {"type": "ag_ui", "event": build_run_error_event(error_message)}
                yield {
                    "type": "error",
                    "code": str(preflight.get("code") or "pi_preflight_failed"),
                    "message": error_message,
                    "preflight": preflight,
                    "turn_id": turn_handle.turn_id,
                    "assistant_message_id": turn_handle.assistant_message_id,
                }
                return
            preflight_warnings = [
                item
                for item in preflight.get("checks", [])
                if isinstance(item, dict) and item.get("severity") == "warning" and not item.get("ok")
            ]

            def mark_progress(now: float, *, signature: str = "") -> bool:
                nonlocal last_progress_at, last_progress_signature
                if signature:
                    if signature == last_progress_signature:
                        return False
                    last_progress_signature = signature
                else:
                    last_progress_signature = ""
                last_progress_at = now
                return True

            def mark_result_progress(event, result, *, now: float) -> None:
                signature = _native_agent_progress_signature(event, result)
                if signature is None:
                    return
                mark_progress(now, signature=signature)

            def no_progress_timed_out(now: float) -> bool:
                try:
                    timeout = float(NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS)
                except (TypeError, ValueError):
                    timeout = 0.0
                return timeout > 0 and now - last_progress_at >= timeout

            def remember_native_session(session_id: str) -> None:
                nonlocal native_session_id, pi_record
                resolved = str(session_id or "").strip()
                if not resolved or resolved == native_session_id:
                    return
                native_session_id = resolved
                turn_state.native_session_id = resolved
                history_service.store.set_conversation_native_session(turn_handle.conversation_id, resolved, desired_meta)
                if pi_record is not None:
                    pi_record.pi_session_id = resolved
                    pi_record = self._pi_session_store.upsert(pi_record)
                with session._lock:
                    session.native_agent_session_id = resolved
                session.persist()

            runtime_key = build_pi_runtime_key(
                bot_id=int(session.bot_id or 0),
                user_id=int(user_id),
                conversation_id=turn_handle.conversation_id,
            )
            active_runtime = await self._runtime_registry.open_or_create(
                PiSessionRuntimeRequest(
                    runtime_key=runtime_key,
                    owner_key=build_pi_owner_key(bot_id=int(session.bot_id or 0), user_id=int(user_id)),
                    conversation_id=turn_handle.conversation_id,
                    cwd=session.working_dir,
                    command=pi_command,
                    model=model_id,
                    agent_id=agent_id,
                    reasoning_effort=reasoning_effort,
                    native_session_id=native_session_id,
                )
            )
            if pi_record is not None:
                self._seed_runtime_from_record(active_runtime, pi_record)
                native_session_id = active_runtime.state.native_session_id
                turn_state.native_session_id = native_session_id
            if workspace_history_enabled and pi_record is not None:
                status_before_turn = await self._workspace_history.status(active_runtime)
                if status_before_turn.degraded:
                    pi_record = self._pi_session_store.mark_degraded(
                        pi_record_key,
                        status_before_turn.message or "workspace history 不可用",
                    )
                else:
                    active_runtime.state.workspace_history_head = str(status_before_turn.head or "").strip()
                    if status_before_turn.manual_change_count > 0:
                        checkpoint = await self._workspace_history.checkpoint(active_runtime, label="manual-before-turn")
                        if checkpoint.degraded:
                            pi_record = self._pi_session_store.mark_degraded(
                                pi_record_key,
                                checkpoint.message or "workspace history 不可用",
                            )
                        else:
                            active_runtime.state.workspace_history_head = str(
                                checkpoint.head or active_runtime.state.workspace_history_head or ""
                            ).strip()
            with session._lock:
                session.native_agent_server_key = active_runtime.runtime_id
            session.persist()

            yield {
                "type": "meta",
                "alias": profile.alias,
                "cli_type": profile.cli_type,
                "execution_mode": EXECUTION_MODE_NATIVE_AGENT,
                "native_provider": NATIVE_AGENT_PROVIDER,
                "runtime_provider": "pi",
                "pi_runtime_id": active_runtime.runtime_id,
                "preflight": preflight,
                **self._workspace_meta(pi_record, active_runtime),
                "native_session_id": native_session_id,
                "turn_id": turn_handle.turn_id,
                "assistant_message_id": turn_handle.assistant_message_id,
                "native_session_reused": bool(requested_session_id),
                "native_session_reason": "conversation_bound" if requested_session_id else "created",
                "working_dir": session.working_dir,
                **({"cluster_run_id": normalized_cluster_run_id} if normalized_cluster_run_id else {}),
            }
            for warning in preflight_warnings:
                trace_event = {
                    "kind": "warning",
                    "source": "native_agent",
                    "summary": str(warning.get("message") or "Pi preflight warning"),
                    "preflight_key": str(warning.get("key") or ""),
                    "fix": str(warning.get("fix") or ""),
                }
                live_trace.append(trace_event)
                persistence_buffer.queue_trace(trace_event)
                yield {"type": "trace", "event": trace_event}
            if wants_ag_ui:
                yield {
                    "type": "ag_ui",
                    "event": build_run_started_event(state=ag_ui_state, user_text=user_text),
                }

            async def stop_if_no_progress(now: float) -> bool:
                nonlocal completion_state, error_message, returncode
                if not no_progress_timed_out(now):
                    return False
                if aggregator.saw_tool_failure:
                    completion_state = "error"
                    returncode = 1
                    error_message = aggregator.tool_failure_message or "原生 agent 工具执行失败"
                    return True
                completion_state = "error"
                returncode = 1
                error_message = NATIVE_AGENT_NO_PROGRESS_MESSAGE
                if active_runtime is not None:
                    await active_runtime.kill()
                return True

            native_prompt_text = (
                prompt_text
                if requested_session_id or session_binding_invalidated
                else _build_native_prompt_with_history(history_items, prompt_text)
            )
            await active_runtime.prompt(native_prompt_text, conversation_id=native_session_id)
            stream = active_runtime.events()
            iterator = stream.__aiter__()
            next_event_task: asyncio.Task[dict[str, Any]] | None = None
            mark_progress(loop.time(), signature="pi-run-started")
            try:
                while True:
                    with session._lock:
                        stop_requested = bool(session.stop_requested)
                    if stop_requested:
                        completion_state = "cancelled"
                        await active_runtime.abort()
                        break
                    if await stop_if_no_progress(loop.time()):
                        break
                    if next_event_task is None:
                        next_event_task = asyncio.create_task(iterator.__anext__())
                    done_tasks, _ = await asyncio.wait({next_event_task}, timeout=0.5)
                    if not done_tasks:
                        continue
                    task = next_event_task
                    next_event_task = None
                    try:
                        raw_event = task.result()
                    except StopAsyncIteration:
                        with session._lock:
                            stopped_after_exit = bool(session.stop_requested)
                        if stopped_after_exit:
                            completion_state = "cancelled"
                            await active_runtime.abort()
                        break
                    except PiRpcRunError:
                        if completion_state == "cancelled":
                            break
                        raise
                    discovered_session_id = extract_native_session_id(raw_event, provider="pi")
                    if discovered_session_id:
                        remember_native_session(discovered_session_id)
                        active_runtime.state.native_session_id = discovered_session_id
                        yield {
                            "type": "meta",
                            "native_session_id": native_session_id,
                            "turn_id": turn_handle.turn_id,
                            "assistant_message_id": turn_handle.assistant_message_id,
                            "runtime_provider": "pi",
                        }
                    usage = extract_native_context_usage(raw_event, provider="pi")
                    if usage:
                        context_run_usage = usage
                    for mapped_raw in native_json_to_events(
                        raw_event,
                        provider="pi",
                        cwd=session.working_dir,
                        fallback_session_id=native_session_id,
                        assistant_message_id=aggregator.assistant_message_id or turn_handle.assistant_message_id,
                    ):
                        event = unwrap_event(mapped_raw)
                        if event is None:
                            continue
                        if native_session_id and not is_relevant_event(event, session_id=native_session_id, cwd=session.working_dir):
                            continue
                        result = aggregator.apply(event)
                        turn_state.observe(event, result, now=loop.time())
                        mark_result_progress(event, result, now=loop.time())
                        if event.type == "permission.updated":
                            permission_id = _permission_id_from_event(event)
                            if permission_id:
                                active_runtime.mark_permission_pending(permission_id)
                        if wants_ag_ui and not should_filter_event(event):
                            for ag_ui_event in map_ag_ui_event(event=event, result=result, state=ag_ui_state):
                                yield {"type": "ag_ui", "event": ag_ui_event}
                        if result.assistant_message_id:
                            ag_ui_state.assistant_message_id = result.assistant_message_id
                            yield {
                                "type": "meta",
                                "native_session_id": native_session_id,
                                "turn_id": turn_handle.turn_id,
                                "assistant_message_id": turn_handle.assistant_message_id,
                                "native_assistant_message_id": result.assistant_message_id,
                            }
                        if result.delta:
                            final_text = aggregator.text()
                            history_service.replace_assistant_content(turn_handle, final_text, state="streaming")
                            yield {"type": "delta", "text": result.delta}
                        if result.snapshot or result.replace_text:
                            final_text = result.snapshot
                            history_service.replace_assistant_content(turn_handle, final_text, state="streaming")
                            yield {
                                "type": "snapshot",
                                "text": final_text,
                                "elapsed_seconds": int(loop.time() - started_at),
                            }
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
                    if completion_state in {"error", "cancelled"} or turn_state.done:
                        break
            finally:
                if next_event_task is not None and not next_event_task.done():
                    next_event_task.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration):
                        await next_event_task
                try:
                    await stream.aclose()
                except Exception:
                    pass

            messages = []
            final_text = final_text or aggregator.text()
            if completion_state == "completed" and aggregator.saw_tool_failure:
                completion_state = "error"
                returncode = 1
                error_message = aggregator.tool_failure_message or "原生 agent 工具执行失败"
            if completion_state == "cancelled":
                live_trace.append({"kind": "cancelled", "source": "native_agent", "summary": "用户终止输出"})
                if active_runtime is not None:
                    await active_runtime.kill()
            if not final_text and completion_state == "completed":
                final_text = "原生 agent 未返回内容"
            if completion_state == "error" and not final_text:
                final_text = error_message or "原生 agent 执行失败"
            persistence_buffer.flush()
            for trace_event in live_trace:
                if trace_event.get("kind") == "cancelled":
                    history_service.append_trace_event(turn_handle, trace_event)
            final_session_payload = None
            context_usage = resolve_native_agent_context_usage(
                session_id=native_session_id,
                model_id=model_id,
                messages=messages,
                session_payload=final_session_payload,
                run_usage=context_run_usage,
            )
            done_message = history_service.complete_turn(
                turn_handle,
                content=final_text,
                completion_state=completion_state,
                native_session_id=native_session_id,
                error_code=None if completion_state == "completed" else completion_state,
                error_message=None if completion_state == "completed" else (error_message or final_text),
                context_usage=context_usage,
            )
            if completion_state == "completed" and active_runtime is not None and pi_record_key and pi_record is not None:
                if workspace_history_enabled:
                    status_after_turn = await self._workspace_history.status(active_runtime)
                    if status_after_turn.degraded:
                        pi_record = self._pi_session_store.mark_degraded(
                            pi_record_key,
                            status_after_turn.message or "workspace history 不可用",
                        )
                    else:
                        final_head = str(status_after_turn.head or "").strip()
                        active_runtime.state.workspace_history_head = final_head
                        pi_record = self._pi_session_store.update_after_completed_turn(
                            pi_record_key,
                            pi_session_id=native_session_id,
                            turn_id=turn_handle.turn_id,
                            workspace_history_head=final_head,
                        )
                        self._seed_runtime_from_record(active_runtime, pi_record)
                        history_service.store.update_turn_workspace_history(
                            turn_handle.turn_id,
                            pi_record.workspace_history_head,
                            pi_record.linear_index,
                        )
                else:
                    pi_record.pi_session_id = native_session_id
                    pi_record.session_meta = dict(desired_meta)
                    pi_record = self._pi_session_store.upsert(pi_record)
            if isinstance(done_message.get("meta"), dict):
                done_message["meta"].update(self._workspace_meta(pi_record, active_runtime))
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
                        context_usage=context_usage,
                    ),
                }
            elapsed_seconds = int(loop.time() - started_at)
            yield {
                "type": "done",
                "native_session_id": native_session_id,
                "turn_id": turn_handle.turn_id,
                "assistant_message_id": turn_handle.assistant_message_id,
                "native_assistant_message_id": aggregator.assistant_message_id,
                "output": final_text,
                "message": done_message,
                "elapsed_seconds": elapsed_seconds,
                "returncode": returncode,
                "context_usage": context_usage,
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
            if active_runtime is not None:
                await active_runtime.kill()
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
        agen = self.stream_chat(**kwargs)
        try:
            async for event in agen:
                if event.get("type") == "done":
                    last_event = event
                    break
                if event.get("type") == "error":
                    raise RuntimeError(str(event.get("message") or "原生 agent 执行失败"))
        finally:
            await agen.aclose()
        if last_event is None:
            raise RuntimeError("原生 agent 未返回结果")
        return {
            "output": str(last_event.get("output") or ""),
            "message": last_event.get("message"),
            "elapsed_seconds": last_event.get("elapsed_seconds", 0),
            "returncode": last_event.get("returncode", 0),
            "session": last_event.get("session"),
        }


def _build_native_prompt_with_history(history_items: list[dict[str, Any]], prompt_text: str) -> str:
    rows: list[str] = []
    for item in history_items[-12:]:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        if str(meta.get("completion_state") or "").strip().lower() not in {"", "completed"}:
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        if role == "assistant" and str(item.get("state") or "").strip().lower() != "done":
            continue
        content = _history_item_content(item)
        if not content:
            continue
        label = "用户" if role == "user" else "助手"
        rows.append(f"{label}: {content[:2000]}")
    if not rows:
        return prompt_text
    context = "\n\n".join(rows)
    return (
        "以下是本 Web 会话最近上下文，请据此回答当前用户消息。\n\n"
        f"{context}\n\n"
        "当前用户消息:\n"
        f"{prompt_text}"
    )


def _history_item_content(item: dict[str, Any]) -> str:
    for key in ("content", "text", "output", "message"):
        value = item.get(key)
        if value:
            return str(value).strip()
    return ""


def _native_session_meta(*, cwd: str, model_id: str, pi_agent: str, reasoning_effort: str) -> dict[str, str]:
    return {
        "cwd": str(cwd or ""),
        "model_id": str(model_id or ""),
        "pi_agent": str(pi_agent or ""),
        "reasoning_effort": str(reasoning_effort or ""),
    }


def _native_session_meta_mismatch(stored_meta: dict[str, Any], desired_meta: dict[str, str]) -> bool:
    stored_meta = migrate_native_session_meta(stored_meta)
    if not stored_meta:
        return any(str(value or "").strip() for value in desired_meta.values())
    for key, desired_value in desired_meta.items():
        normalized_desired = str(desired_value or "").strip()
        stored_value = str(stored_meta.get(key) or "").strip()
        if stored_value != normalized_desired:
            return True
    return False


def _native_agent_progress_signature(event: Any, result: Any) -> str | None:
    if result.delta or result.trace or result.error or result.done:
        return ""
    if result.snapshot:
        return f"snapshot:{result.snapshot}"
    if result.replace_text:
        return "replace"
    status = str(result.status or "").strip()
    if status:
        return f"status:{status}"
    assistant_message_id = str(result.assistant_message_id or "").strip()
    if assistant_message_id:
        return f"assistant:{assistant_message_id}"
    event_type = str(getattr(event, "type", "") or "").strip()
    if event_type in {"permission.updated", "permission.replied"}:
        payload = getattr(event, "payload", {}) if event is not None else {}
        permission_id = ""
        if isinstance(payload, dict):
            permission = payload.get("permission") if isinstance(payload.get("permission"), dict) else payload
            permission_id = str(
                permission.get("id")
                or permission.get("permissionID")
                or permission.get("permission_id")
                or ""
            ).strip()
        return f"permission:{permission_id or event_type}"
    return None


def _permission_id_from_event(event: Any) -> str:
    payload = getattr(event, "payload", {}) if event is not None else {}
    if not isinstance(payload, dict):
        return ""
    permission = payload.get("permission") if isinstance(payload.get("permission"), dict) else payload
    for key in ("id", "permissionID", "permission_id", "request_id", "requestId"):
        value = permission.get(key)
        if value:
            return str(value).strip()
    return ""


_SERVICE = NativeAgentService()


def get_native_agent_service() -> NativeAgentService:
    return _SERVICE
