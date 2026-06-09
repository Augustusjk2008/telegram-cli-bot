from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
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
from bot.native_agent.run_client import (
    NativeAgentExportRequest,
    NativeAgentRunClient,
    NativeAgentRunError,
    NativeAgentRunRequest,
    is_session_unavailable_error,
)
from bot.native_agent.run_events import extract_session_id as extract_run_session_id
from bot.native_agent.run_events import extract_step_finish_usage, run_json_to_events
from bot.native_agent.turn_state import NativeAgentTurnState
from bot.web.chat_history_service import ChatHistoryService, StreamingPersistenceBuffer

NATIVE_AGENT_PROVIDER = EXECUTION_MODE_NATIVE_AGENT
EVENT_READY_TIMEOUT_SECONDS = 10.0
LIST_MESSAGES_TIMEOUT_SECONDS = 1.5
ABORT_TIMEOUT_SECONDS = 2.0
FINAL_CANDIDATE_GRACE_SECONDS = 2.0
FINAL_CANDIDATE_MAX_SECONDS = 4.0
NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS = 1000.0
NATIVE_AGENT_NO_PROGRESS_MESSAGE = "原生 agent 长时间无输出或进展"


@dataclass(frozen=True)
class NativeAgentSessionResolution:
    session_id: str
    reused: bool
    reason: str
    baseline_messages: list[dict[str, Any]]
    session_payload: dict[str, Any] | None = None


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
        self._run_client_factory = NativeAgentRunClient

    def _prompt_options(self, profile: BotProfile) -> tuple[str, str]:
        native_agent = effective_native_agent_config(getattr(profile, "native_agent", {}))
        validate_native_agent_model_config(native_agent)
        return (
            build_native_agent_model_id(native_agent),
            str(native_agent.get("opencode_agent") or "").strip(),
        )

    async def _ensure_session_id(
        self,
        client: NativeAgentClient,
        session: UserSession,
        history_service: ChatHistoryService,
        conversation_id: str,
        *,
        model_id: str,
        opencode_agent: str,
    ) -> NativeAgentSessionResolution:
        desired_meta = _native_session_meta(
            cwd=session.working_dir,
            model_id=model_id,
            opencode_agent=opencode_agent,
        )

        async def create(reason: str) -> NativeAgentSessionResolution:
            created = await client.create_session(cwd=session.working_dir)
            native_session_id = _extract_session_id(created)
            with session._lock:
                session.native_agent_session_id = native_session_id
            history_service.store.set_conversation_native_session(conversation_id, native_session_id, desired_meta)
            session.persist()
            return NativeAgentSessionResolution(
                session_id=native_session_id,
                reused=False,
                reason=reason,
                baseline_messages=[],
                session_payload=created if isinstance(created, dict) else None,
            )

        try:
            conversation_native = history_service.store.get_conversation_native_session(conversation_id)
        except Exception:
            conversation_native = {}
        conversation_session_id = str(conversation_native.get("session_id") or "").strip()
        stored_meta = conversation_native.get("meta") if isinstance(conversation_native.get("meta"), dict) else {}
        if not conversation_session_id:
            return await create("created")

        if not callable(getattr(client, "get_session", None)):
            raise RuntimeError(_native_session_diagnostic(conversation_session_id, "get_session_unavailable"))
        try:
            session_payload = await _get_session_with_timeout(client, conversation_session_id)
        except Exception as exc:
            raise RuntimeError(_native_session_diagnostic(conversation_session_id, "get_session_failed", str(exc))) from exc

        if not _session_payload_cwd_matches(session_payload, session.working_dir):
            actual_cwd = _session_payload_cwd(session_payload)
            raise RuntimeError(_native_session_diagnostic(conversation_session_id, "cwd_mismatch", f"{actual_cwd} != {session.working_dir}"))
        if _native_session_meta_mismatch(stored_meta, desired_meta):
            raise RuntimeError(_native_session_diagnostic(conversation_session_id, "config_changed"))
        try:
            baseline_messages = await _list_messages_with_timeout(client, conversation_session_id)
        except Exception as exc:
            raise RuntimeError(_native_session_diagnostic(conversation_session_id, "list_messages_failed", str(exc))) from exc

        with session._lock:
            session.native_agent_session_id = conversation_session_id
        history_service.store.set_conversation_native_session(conversation_id, conversation_session_id, desired_meta)
        session.persist()
        return NativeAgentSessionResolution(
            session_id=conversation_session_id,
            reused=True,
            reason="conversation_bound",
            baseline_messages=baseline_messages,
            session_payload=session_payload,
        )

    async def abort(self, session: UserSession) -> bool:
        with session._lock:
            process = session.process
            if not session.is_processing:
                return False
            session.stop_requested = True
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
        _ = session, permission_id, approved, message
        raise RuntimeError("unsupported_in_run_mode: opencode run 模式暂不支持交互式权限处理，请调整 OpenCode agent 权限配置")

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
        raw_output_parts: list[str] = []
        active_run_client: NativeAgentRunClient | None = None

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
            model_id, agent_id = self._prompt_options(profile)
            native_agent_config = effective_native_agent_config(getattr(profile, "native_agent", {}))
            desired_meta = _native_session_meta(
                cwd=session.working_dir,
                model_id=model_id,
                opencode_agent=agent_id,
            )
            try:
                conversation_native = history_service.store.get_conversation_native_session(turn_handle.conversation_id)
            except Exception:
                conversation_native = {}
            requested_session_id = str(conversation_native.get("session_id") or "").strip()
            stored_meta = conversation_native.get("meta") if isinstance(conversation_native.get("meta"), dict) else {}
            if requested_session_id and _native_session_meta_mismatch(stored_meta, desired_meta):
                history_service.store.set_conversation_native_session(turn_handle.conversation_id, None, None)
                requested_session_id = ""
            if requested_session_id:
                native_session_id = requested_session_id
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

            def attach_process(process) -> None:
                with session._lock:
                    session.process = process

            def remember_native_session(session_id: str) -> None:
                nonlocal native_session_id
                resolved = str(session_id or "").strip()
                if not resolved or resolved == native_session_id:
                    return
                native_session_id = resolved
                turn_state.native_session_id = resolved
                history_service.store.set_conversation_native_session(turn_handle.conversation_id, resolved, desired_meta)
                with session._lock:
                    session.native_agent_session_id = resolved
                session.persist()

            yield {
                "type": "meta",
                "alias": profile.alias,
                "cli_type": profile.cli_type,
                "execution_mode": EXECUTION_MODE_NATIVE_AGENT,
                "native_provider": NATIVE_AGENT_PROVIDER,
                "native_session_id": native_session_id,
                "turn_id": turn_handle.turn_id,
                "assistant_message_id": turn_handle.assistant_message_id,
                "native_session_reused": bool(requested_session_id),
                "native_session_reason": "conversation_bound" if requested_session_id else "created",
                "working_dir": session.working_dir,
                **({"cluster_run_id": normalized_cluster_run_id} if normalized_cluster_run_id else {}),
            }
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
                if active_run_client is not None:
                    active_run_client.kill()
                return True

            attempt = 0
            while True:
                attempt += 1
                reused = bool(requested_session_id)
                native_prompt_text = prompt_text if reused else _build_native_prompt_with_history(history_items, prompt_text)
                run_client = self._run_client_factory()
                active_run_client = run_client
                request = NativeAgentRunRequest(
                    cwd=session.working_dir,
                    prompt=native_prompt_text,
                    command=config.NATIVE_AGENT_COMMAND,
                    session_id=requested_session_id,
                    model_id=model_id,
                    agent_id=agent_id,
                    variant=str(native_agent_config.get("reasoning_effort") or ""),
                    native_agent=native_agent_config,
                    on_process=attach_process,
                )
                stream = run_client.stream(request)
                iterator = stream.__aiter__()
                mark_progress(loop.time(), signature="run-started")
                try:
                    while True:
                        with session._lock:
                            stop_requested = bool(session.stop_requested)
                        if stop_requested:
                            completion_state = "cancelled"
                            run_client.kill()
                            break
                        if await stop_if_no_progress(loop.time()):
                            break
                        try:
                            raw_event = await asyncio.wait_for(iterator.__anext__(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        except StopAsyncIteration:
                            with session._lock:
                                stopped_after_exit = bool(session.stop_requested)
                            if stopped_after_exit:
                                completion_state = "cancelled"
                                run_client.kill()
                            break
                        except NativeAgentRunError as exc:
                            if completion_state == "cancelled":
                                break
                            if requested_session_id and attempt == 1 and is_session_unavailable_error(exc):
                                history_service.store.set_conversation_native_session(turn_handle.conversation_id, None, None)
                                with session._lock:
                                    session.native_agent_session_id = None
                                session.persist()
                                requested_session_id = ""
                                native_session_id = ""
                                yield {
                                    "type": "status",
                                    "elapsed_seconds": int(loop.time() - started_at),
                                    "preview_text": "已绑定 opencode session 不可用，正在新建 session 重试",
                                }
                                break
                            raise
                        if str(raw_event.get("type") or "") == "raw_text":
                            raw_text = str(raw_event.get("raw_text") or "")
                            if raw_text:
                                raw_output_parts.append(raw_text)
                        discovered_session_id = extract_run_session_id(raw_event)
                        if discovered_session_id:
                            remember_native_session(discovered_session_id)
                            yield {
                                "type": "meta",
                                "native_session_id": native_session_id,
                                "turn_id": turn_handle.turn_id,
                                "assistant_message_id": turn_handle.assistant_message_id,
                            }
                        usage = extract_step_finish_usage(raw_event)
                        if usage:
                            context_run_usage = usage
                        for mapped_raw in run_json_to_events(
                            raw_event,
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
                            if event.type == "permission.updated":
                                error_message = "opencode run 模式暂不支持交互式权限请求，请调整 OpenCode agent 权限配置"
                                completion_state = "error"
                                returncode = 1
                                if wants_ag_ui:
                                    text_end = build_text_end_event(state=ag_ui_state)
                                    if text_end is not None:
                                        yield {"type": "ag_ui", "event": text_end}
                                    yield {"type": "ag_ui", "event": build_run_error_event(error_message)}
                                break
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
                    if requested_session_id == "" and reused and attempt == 1 and not native_session_id:
                        continue
                    break
                finally:
                    try:
                        await stream.aclose()
                    except Exception:
                        pass

            messages = []
            if native_session_id and active_run_client is not None:
                try:
                    messages = await active_run_client.export_session(
                        NativeAgentExportRequest(
                            cwd=session.working_dir,
                            session_id=native_session_id,
                            command=config.NATIVE_AGENT_COMMAND,
                            native_agent=native_agent_config,
                        )
                    )
                except Exception:
                    messages = []
            if messages:
                try:
                    reconciled = aggregator.reconcile_messages(messages)
                    trace = aggregator.pop_reconciled_trace()
                    for trace_event in trace:
                        live_trace.append(trace_event)
                        persistence_buffer.queue_trace(trace_event)
                    if reconciled:
                        final_text = reconciled
                except Exception:
                    pass
            final_text = final_text or aggregator.text()
            if completion_state == "completed" and aggregator.saw_tool_failure:
                completion_state = "error"
                returncode = 1
                error_message = aggregator.tool_failure_message or "原生 agent 工具执行失败"
            if completion_state == "cancelled":
                live_trace.append({"kind": "cancelled", "source": "native_agent", "summary": "用户终止输出"})
                if active_run_client is not None:
                    active_run_client.kill()
            if completion_state == "completed" and not final_text and raw_output_parts:
                completion_state = "error"
                returncode = 1
                error_message = f"原生 agent 返回了非 JSON 输出: {' '.join(raw_output_parts)[:2000]}"
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
            if active_run_client is not None:
                active_run_client.kill()
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


def _native_session_meta(*, cwd: str, model_id: str, opencode_agent: str) -> dict[str, str]:
    return {
        "cwd": str(cwd or ""),
        "model_id": str(model_id or ""),
        "opencode_agent": str(opencode_agent or ""),
    }


def _native_session_meta_mismatch(stored_meta: dict[str, Any], desired_meta: dict[str, str]) -> bool:
    if not isinstance(stored_meta, dict) or not stored_meta:
        return False
    for key, desired_value in desired_meta.items():
        if key not in stored_meta:
            continue
        if str(stored_meta.get(key) or "") != str(desired_value or ""):
            return True
    return False


def _native_session_diagnostic(session_id: str, reason: str, detail: str = "") -> str:
    messages = {
        "get_session_unavailable": "原生 agent 客户端不支持探测已绑定 session",
        "get_session_failed": "已绑定 opencode session 不可用",
        "list_messages_failed": "已绑定 opencode session 消息探测失败",
        "cwd_mismatch": "已绑定 opencode session 工作目录不匹配",
        "config_changed": "已绑定 opencode session 配置不匹配",
    }
    base = messages.get(str(reason or ""), "已绑定 opencode session 探测失败")
    suffix = f": {detail}" if str(detail or "").strip() else ""
    return f"{base} ({session_id}){suffix}"


def _session_payload_cwd_matches(session_payload: dict[str, Any] | None, cwd: str) -> bool:
    payload_cwd = _session_payload_cwd(session_payload)
    if not payload_cwd:
        return True
    return _normalize_path_for_compare(payload_cwd) == _normalize_path_for_compare(cwd)


def _session_payload_cwd(session_payload: dict[str, Any] | None) -> str:
    if not isinstance(session_payload, dict):
        return ""
    candidates = [session_payload]
    for key in ("data", "session"):
        value = session_payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for item in candidates:
        for key in ("directory", "cwd", "working_dir", "workingDir"):
            value = item.get(key)
            if value:
                return str(value)
    return ""


def _native_session_reuse_health(
    messages: list[dict[str, Any]],
    session_payload: dict[str, Any] | None,
) -> tuple[bool, str]:
    if _payload_has_pending_permission(session_payload):
        return False, "pending_permission"
    if _payload_is_cancelled(session_payload):
        return False, "cancelled"
    last_message = _last_user_or_assistant_message(messages)
    if not last_message:
        return True, "empty"
    if _payload_has_pending_permission(last_message):
        return False, "pending_permission"
    if _payload_is_cancelled(last_message):
        return False, "cancelled"
    role = str(last_message.get("role") or "").strip().lower()
    if role == "user":
        return False, "last_user"
    if role == "assistant":
        if _service_message_expects_followup(last_message):
            return False, "tool_call"
        if _service_message_completed(last_message):
            return True, "completed"
        return False, "assistant_incomplete"
    return True, "empty"


def _last_user_or_assistant_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(messages, list):
        return {}
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role in {"user", "assistant"}:
            return message
    return {}


def _payload_is_cancelled(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status_values: list[str] = []
    for key in ("status", "state", "finish", "finish_reason", "finishReason"):
        value = payload.get(key)
        if value is not None:
            status_values.append(str(value).strip().lower())
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    for key in ("status", "state", "finish", "finish_reason", "finishReason"):
        value = info.get(key)
        if value is not None:
            status_values.append(str(value).strip().lower())
    return any(value in {"abort", "aborted", "cancel", "canceled", "cancelled"} for value in status_values)


def _payload_has_pending_permission(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("permission", "permissions"):
        value = payload.get(key)
        if _permission_payload_pending(value):
            return True
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    for key in ("permission", "permissions"):
        value = info.get(key)
        if _permission_payload_pending(value):
            return True
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if _permission_payload_pending(part):
                return True
    return False


def _permission_payload_pending(value: Any) -> bool:
    if isinstance(value, list):
        return any(_permission_payload_pending(item) for item in value)
    if not isinstance(value, dict):
        return False
    kind = str(value.get("type") or value.get("kind") or "").strip().lower()
    status = str(value.get("status") or value.get("state") or value.get("result") or "").strip().lower()
    if kind == "permission" and status in {"", "pending", "requested", "open", "waiting", "awaiting"}:
        return True
    return status in {"pending", "requested", "open", "waiting", "awaiting"}


def _normalize_path_for_compare(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        normalized = str(Path(text).expanduser().resolve(strict=False))
    except Exception:
        normalized = text
    return os.path.normcase(normalized).rstrip("\\/")


def _defer_reconciled_done(
    aggregator: NativeAgentAggregator,
    *,
    completed_at: float,
    now: float,
    window_seconds: float = 2.0,
) -> bool:
    if not aggregator.assistant_completed or not completed_at:
        return False
    return now - completed_at < window_seconds


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


async def _list_messages_with_timeout(
    client: NativeAgentClient,
    session_id: str,
    *,
    timeout_seconds: float | None = None,
) -> list[dict[str, Any]]:
    if not callable(getattr(client, "list_messages", None)):
        return []
    timeout = LIST_MESSAGES_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    messages = await asyncio.wait_for(client.list_messages(session_id), timeout=timeout)
    return messages if isinstance(messages, list) else []


async def _get_session_with_timeout(
    client: NativeAgentClient,
    session_id: str,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    timeout = LIST_MESSAGES_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    payload = await asyncio.wait_for(client.get_session(session_id), timeout=timeout)
    return payload if isinstance(payload, dict) else {}


async def _abort_native_prompt_best_effort(
    client: NativeAgentClient,
    session_id: str,
    *,
    assistant_message_id: str = "",
) -> bool:
    try:
        await asyncio.wait_for(
            _abort_native_prompt(client, session_id, assistant_message_id=assistant_message_id),
            timeout=ABORT_TIMEOUT_SECONDS,
        )
        return True
    except Exception:
        return False


async def _abort_native_prompt(
    client: NativeAgentClient,
    session_id: str,
    *,
    assistant_message_id: str = "",
) -> None:
    if not callable(getattr(client, "abort", None)):
        return
    await _wait_for_abort_checkpoint(client, session_id, assistant_message_id=assistant_message_id)
    try:
        await client.abort(session_id)
    except Exception:
        pass
    await _wait_until_session_can_continue(client, session_id)


async def _wait_for_abort_checkpoint(
    client: NativeAgentClient,
    session_id: str,
    *,
    assistant_message_id: str = "",
    timeout_seconds: float = 0.8,
) -> None:
    target = str(assistant_message_id or "").strip()
    if not target or not callable(getattr(client, "list_messages", None)):
        await asyncio.sleep(min(0.2, max(0.0, timeout_seconds)))
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout_seconds)
    while loop.time() < deadline:
        try:
            messages = await _list_messages_with_timeout(
                client,
                session_id,
                timeout_seconds=min(LIST_MESSAGES_TIMEOUT_SECONDS, max(0.01, deadline - loop.time())),
            )
        except Exception:
            return
        if _has_message_after(messages, target):
            return
        await asyncio.sleep(0.05)


async def _wait_until_session_can_continue(
    client: NativeAgentClient,
    session_id: str,
    *,
    timeout_seconds: float = 1.2,
) -> None:
    if not callable(getattr(client, "list_messages", None)):
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout_seconds)
    while loop.time() < deadline:
        if await _session_can_continue(client, session_id):
            return
        await asyncio.sleep(0.05)


def _has_message_after(messages: list[dict[str, Any]], message_id: str) -> bool:
    target = str(message_id or "").strip()
    if not target or not isinstance(messages, list):
        return False
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        if _message_id_from_service_message(message) == target:
            return any(isinstance(item, dict) for item in messages[index + 1 :])
    return False


async def _session_can_continue(client: NativeAgentClient, session_id: str) -> bool:
    try:
        messages = await _list_messages_with_timeout(client, session_id)
    except Exception:
        return True
    if not isinstance(messages, list) or not messages:
        return True
    last_message = {}
    for item in reversed(messages):
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower()
            if role in {"user", "assistant"}:
                last_message = item
                break
    role = str(last_message.get("role") or "").strip().lower()
    if role == "user":
        return False
    if role == "assistant":
        if _service_message_expects_followup(last_message):
            return False
        return _service_message_completed(last_message) or bool(_service_message_text(last_message))
    return True


def _service_message_completed(message: dict[str, Any]) -> bool:
    if _service_message_expects_followup(message):
        return False
    finish = str(message.get("finish") or message.get("finish_reason") or message.get("finishReason") or "").strip().lower()
    if finish in {"stop", "stopped", "complete", "completed", "done", "success", "end", "finished"}:
        return True
    time_payload = message.get("time")
    if isinstance(time_payload, dict) and time_payload.get("completed"):
        return True
    for key in ("completed", "completed_at", "completedAt"):
        if message.get(key):
            return True
    state = str(message.get("state") or message.get("status") or "").strip().lower()
    return state in {"completed", "done", "idle", "success"}


def _service_message_expects_followup(message: dict[str, Any]) -> bool:
    finish = str(message.get("finish") or message.get("finish_reason") or message.get("finishReason") or "").strip().lower()
    return finish in {"tool-calls", "tool_calls", "tool-call", "tool_call"}


def _service_message_text(message: dict[str, Any]) -> str:
    text = str(message.get("content") or message.get("text") or "").strip()
    if text:
        return text
    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    values: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").strip().lower() not in {"text", "assistant_text", "message", ""}:
            continue
        value = str(part.get("text") or part.get("content") or part.get("delta") or "").strip()
        if value:
            values.append(value)
    return "".join(values).strip()


def _message_id_from_service_message(message: dict[str, Any]) -> str:
    for key in ("id", "messageID", "message_id", "messageId"):
        value = message.get(key)
        if value:
            return str(value)
    info = message.get("info")
    if isinstance(info, dict):
        for key in ("id", "messageID", "message_id", "messageId"):
            value = info.get(key)
            if value:
                return str(value)
    return ""


_SERVICE = NativeAgentService()


def get_native_agent_service() -> NativeAgentService:
    return _SERVICE
