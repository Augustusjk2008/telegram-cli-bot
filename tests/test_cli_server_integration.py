from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile
from bot.web import api_service
from bot.web.api_common import WebApiError


class ServerTurn:
    thread_id = "server-thread"
    context_usage = None
    returncode = 0

    def __init__(self):
        self.prompts = []
        self.failure = False
        self.wait_for_interrupt = False
        self.interrupted = asyncio.Event()
        self.interrupt = AsyncMock(side_effect=self.interrupted.set)
        self.close = AsyncMock()

    async def stream_turn(self, prompt):
        self.prompts.append(prompt)
        yield {"type": "thread.started", "thread_id": self.thread_id}
        yield {"type": "item.started", "item": {"id": "command", "type": "command_execution", "command": "echo test", "status": "in_progress"}}
        yield {"type": "item.delta", "item": {"type": "agent_message", "delta": "partial answer"}}
        if self.failure:
            raise RuntimeError("stdio disconnected")
        if self.wait_for_interrupt:
            await self.interrupted.wait()
            self.returncode = -1
            yield {"type": "turn.completed"}
            return
        yield {"type": "item.completed", "item": {"id": "answer", "type": "agent_message", "text": "final answer"}}
        yield {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3}}


@pytest.fixture
def server_chat(tmp_path: Path, monkeypatch):
    from bot.codex_server import runtime as server_module

    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", cli_type="codex_server", cli_path="codex", working_dir=str(tmp_path)), str(storage))
    runtime = ServerTurn()
    registry = SimpleNamespace(
        open_or_create=AsyncMock(return_value=runtime),
        close_owner=AsyncMock(),
        release_owner=Mock(),
        steer_owner=AsyncMock(),
    )
    monkeypatch.setattr(server_module, "get_codex_server_registry", lambda: registry)
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_args: "codex")
    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", AsyncMock(return_value=None))
    monkeypatch.setattr(api_service, "_resolve_cli_context_usage_bounded", AsyncMock(return_value=None))
    monkeypatch.setattr(api_service, "_reconcile_native_trace_before_completion", AsyncMock(return_value=None))
    monkeypatch.setattr(api_service, "build_cli_command", Mock(side_effect=AssertionError("server must not execute CLI")))
    return manager, runtime, registry


@pytest.mark.asyncio
async def test_server_stream_reuses_binding_and_preserves_sse_history_contract(server_chat):
    manager, runtime, registry = server_chat
    first = [event async for event in api_service._stream_cli_chat(manager, "main", 1001, "hello")]
    done = [event for event in first if event["type"] == "done"]
    assert len(done) == 1 and done[0]["output"] == "final answer"
    assert {event["turn_id"] for event in first} == {done[0]["turn_id"]}
    assert {event["assistant_message_id"] for event in first} == {done[0]["assistant_message_id"]}
    assert any(event["type"] == "status" and event.get("preview_text") for event in first)
    assert any(event["type"] == "trace" for event in first)
    session = api_service.get_session_for_alias(manager, "main", 1001)
    assert session.process is None and not session.is_processing
    assert session.codex_session_id == runtime.thread_id
    saved = api_service._get_chat_store(session).get_conversation(session.active_conversation_id)
    assert saved["native_provider"] == "codex" and saved["cli_type"] == "codex_server"
    second = [event async for event in api_service._stream_cli_chat(manager, "main", 1001, "continue")]
    assert second[-1]["type"] == "done"
    request = registry.open_or_create.call_args.args[0]
    assert request.thread_id == runtime.thread_id
    assert request.owner_key == (session.bot_id, session.user_id, "main")
    history = api_service._get_chat_history_service(session).list_history(manager.main_profile, session)
    assert len([message for message in history if message["role"] == "assistant"]) == 2
    assert runtime.close.await_count == 0


@pytest.mark.asyncio
async def test_server_exit_preserves_partial_reply_and_thread(server_chat):
    manager, runtime, _registry = server_chat
    runtime.failure = True
    events = [event async for event in api_service._stream_cli_chat(manager, "main", 1001, "hello")]
    done = events[-1]
    assert done["type"] == "done" and done["returncode"] != 0
    assert "partial answer" in done["output"]
    assert done["message"]["meta"]["completion_state"] == "error"
    assert "stdio disconnected" in done["output"]
    assert api_service.get_session_for_alias(manager, "main", 1001).codex_session_id == runtime.thread_id


@pytest.mark.asyncio
async def test_server_stop_interrupts_turn_and_keeps_idle_process_reusable(server_chat):
    manager, runtime, _registry = server_chat
    runtime.wait_for_interrupt = True
    events = []
    async for event in api_service._stream_cli_chat(manager, "main", 1001, "wait"):
        events.append(event)
        if event["type"] == "status" and event.get("preview_text"):
            result = await api_service.kill_user_process(manager, "main", 1001)
            assert result["stop_requested"]
    assert events[-1]["message"]["meta"]["completion_state"] == "cancelled"
    runtime.interrupt.assert_awaited_once()
    runtime.close.assert_not_awaited()
    runtime.wait_for_interrupt = False
    runtime.returncode = 0
    next_events = [event async for event in api_service._stream_cli_chat(manager, "main", 1001, "continue")]
    assert next_events[-1]["message"]["meta"]["completion_state"] == "completed"


@pytest.mark.asyncio
async def test_server_start_failure_completes_turn_once(server_chat):
    manager, _runtime, registry = server_chat
    registry.open_or_create.side_effect = ValueError("unsupported app-server option --unknown")
    events = [event async for event in api_service._stream_cli_chat(manager, "main", 1001, "hello")]
    assert len(events) == 1 and events[0]["type"] == "done"
    assert "--unknown" in events[0]["output"]
    assert events[0]["message"]["meta"]["completion_state"] == "error"
    assert not api_service.get_session_for_alias(manager, "main", 1001).is_processing


@pytest.mark.asyncio
async def test_codex_entry_switch_blocks_busy_and_keeps_saved_thread(server_chat, monkeypatch):
    manager, runtime, registry = server_chat
    monkeypatch.setattr("bot.manager.resolve_cli_executable", lambda *_args: "codex")
    session = api_service.get_session_for_alias(manager, "main", 1001)
    session.codex_session_id = runtime.thread_id
    session.is_processing = True
    with pytest.raises(ValueError, match="任务运行中"):
        await manager.set_bot_cli("main", "codex", "codex")
    assert manager.main_profile.cli_type == "codex_server"
    registry.close_owner.assert_not_awaited()
    session.is_processing = False
    await manager.set_bot_cli("main", "codex", "codex")
    registry.close_owner.assert_awaited_once_with((session.bot_id, session.user_id, "main"))
    assert session.codex_session_id == runtime.thread_id


@pytest.mark.asyncio
async def test_new_and_restored_conversation_release_server_binding(server_chat):
    manager, runtime, registry = server_chat
    _events = [event async for event in api_service._stream_cli_chat(manager, "main", 1001, "hello")]
    session = api_service.get_session_for_alias(manager, "main", 1001)
    previous = session.active_conversation_id
    registry.release_owner.reset_mock()
    await api_service.create_conversation(manager, "main", 1001)
    assert not session.codex_session_id
    registry.release_owner.assert_called_once()
    await api_service.select_conversation(manager, "main", 1001, previous)
    assert session.codex_session_id == runtime.thread_id
    assert registry.release_owner.call_count == 2


@pytest.mark.asyncio
async def test_server_compaction_counts_events_once_across_turns(server_chat):
    manager, runtime, _registry = server_chat
    for turn_compactions, expected in ((1, 1), (0, 1), (1, 2)):
        runtime.context_usage = {
            "provider": "codex", "source": "codex_server_token_count", "session_id": runtime.thread_id,
            "context_left_percent": 95, "compaction_count": turn_compactions,
        }
        events = [event async for event in api_service._stream_cli_chat(manager, "main", 1001, "continue")]
        assert events[-1]["message"]["meta"]["context_usage"]["compaction_count"] == expected


@pytest.mark.asyncio
async def test_server_steering_appends_user_message_to_active_turn(server_chat):
    manager, runtime, registry = server_chat
    runtime.wait_for_interrupt = True
    stream = api_service._stream_cli_chat(manager, "main", 1001, "hello")
    first = await anext(stream)
    session = api_service.get_session_for_alias(manager, "main", 1001)
    running = api_service._get_chat_history_service(session).store.get_running_reply(
        bot_id=session.bot_id,
        user_id=session.user_id,
        agent_id=session.agent_id,
        working_dir=session.working_dir,
        session_epoch=session.session_epoch,
        conversation_id=session.active_conversation_id,
        native_provider_exclude="native_agent",
    )
    assert first["type"] == "meta"
    assert running is not None
    registry._runtimes = {
        (session.bot_id, session.user_id, "main"): SimpleNamespace(_turn_id="app-turn")
    }

    result = await api_service.steer_chat(
        manager,
        "main",
        1001,
        "follow-up",
        turn_id=running["turn_id"],
        execution_mode="cli",
        actor={"user_id": 1001, "account_id": "acct", "username": "tester"},
    )

    assert result["turn_id"] == running["turn_id"]
    assert result["assistant_message_id"] == running["assistant_message_id"]
    assert result["user_message"]["content"] == "follow-up"
    assert result["user_message"]["turn_id"] == running["turn_id"]
    second = await api_service.steer_chat(
        manager,
        "main",
        1001,
        "second follow-up",
        turn_id="app-turn",
        execution_mode="cli",
    )
    assert second["assistant_message_id"] == running["assistant_message_id"]
    assert second["user_message"]["content"] == "second follow-up"
    registry.steer_owner.assert_any_await(
        (session.bot_id, session.user_id, "main"), "app-turn", "follow-up"
    )
    registry.steer_owner.assert_any_await(
        (session.bot_id, session.user_id, "main"), "app-turn", "second follow-up"
    )
    assert registry.steer_owner.await_count == 2
    assert session.is_processing

    history = api_service._get_chat_history_service(session).list_history(manager.main_profile, session)
    assert [item["role"] for item in history].count("assistant") == 1
    assert [item["content"] for item in history if item["role"] == "user"] == [
        "hello", "follow-up", "second follow-up"
    ]

    runtime.interrupted.set()
    remaining = [event async for event in stream]
    assert remaining[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_server_steering_rejects_stale_turn_and_wrong_owner(server_chat):
    manager, runtime, registry = server_chat
    manager.main_profile.agents.append(AgentProfile(id="worker", name="worker"))
    runtime.wait_for_interrupt = True
    stream = api_service._stream_cli_chat(manager, "main", 1001, "hello")
    await anext(stream)
    session = api_service.get_session_for_alias(manager, "main", 1001)
    running = api_service._get_chat_history_service(session).store.get_running_reply(
        bot_id=session.bot_id,
        user_id=session.user_id,
        agent_id=session.agent_id,
        working_dir=session.working_dir,
        session_epoch=session.session_epoch,
        conversation_id=session.active_conversation_id,
        native_provider_exclude="native_agent",
    )
    assert running is not None

    with pytest.raises(WebApiError) as stale:
        await api_service.steer_chat(
            manager,
            "main",
            1001,
            "stale",
            turn_id="stale-turn",
            execution_mode="cli",
        )
    assert stale.value.status == 409
    assert stale.value.code == "steering_turn_mismatch"

    with pytest.raises(WebApiError) as wrong_owner:
        await api_service.steer_chat(
            manager,
            "main",
            1002,
            "wrong owner",
            turn_id=running["turn_id"],
            agent_id="worker",
            execution_mode="cli",
        )
    assert wrong_owner.value.status == 409
    assert wrong_owner.value.code == "steering_turn_done"
    registry.steer_owner.assert_not_awaited()

    runtime.interrupted.set()
    remaining = [event async for event in stream]
    assert remaining[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_server_ordinary_busy_behavior_remains_session_busy(server_chat):
    manager, _runtime, _registry = server_chat
    session = api_service.get_session_for_alias(manager, "main", 1001)
    session.is_processing = True

    events = api_service._stream_cli_chat(manager, "main", 1001, "busy")
    with pytest.raises(WebApiError) as exc_info:
        await anext(events)
    assert exc_info.value.status == 409
    assert exc_info.value.code == "session_busy"
    await events.aclose()
    session.is_processing = False


@pytest.mark.asyncio
async def test_failed_server_steering_does_not_persist_user_message(server_chat):
    manager, runtime, registry = server_chat
    runtime.wait_for_interrupt = True
    stream = api_service._stream_cli_chat(manager, "main", 1001, "hello")
    await anext(stream)
    session = api_service.get_session_for_alias(manager, "main", 1001)
    running = api_service._get_chat_history_service(session).store.get_running_reply(
        bot_id=session.bot_id,
        user_id=session.user_id,
        agent_id=session.agent_id,
        working_dir=session.working_dir,
        session_epoch=session.session_epoch,
        conversation_id=session.active_conversation_id,
        native_provider_exclude="native_agent",
    )
    assert running is not None
    registry.steer_owner.side_effect = RuntimeError("codex server owner 没有运行时")

    with pytest.raises(WebApiError) as exc_info:
        await api_service.steer_chat(
            manager,
            "main",
            1001,
            "should not persist",
            turn_id=running["turn_id"],
            execution_mode="cli",
        )
    assert exc_info.value.status == 409
    assert exc_info.value.code == "steering_runtime_missing"
    history = api_service._get_chat_history_service(session).list_history(manager.main_profile, session)
    assert "should not persist" not in [item["content"] for item in history]

    runtime.interrupted.set()
    remaining = [event async for event in stream]
    assert remaining[-1]["type"] == "done"
