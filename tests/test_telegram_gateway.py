from __future__ import annotations

import asyncio
import io
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
import pytest_asyncio

from bot import config
from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.telegram.client import TelegramClient, TelegramError
from bot.telegram.gateway import TelegramGateway, start_telegram_gateway
from bot.telegram.state import TelegramState
from bot.telegram.ui import context_left, format_result, parse_target_text
from bot.web import api_service
from bot.web.api_common import WebApiError


class FakeTelegramClient:
    def __init__(self):
        self.messages = []
        self.markups = []
        self.callbacks = []
        self.closed = False

    async def send_message(self, chat_id, text, *, reply_markup=None):
        self.messages.append((chat_id, text))
        self.markups.append(reply_markup)
        return {"message_id": len(self.messages)}

    async def answer_callback_query(self, callback_query_id, text=""):
        self.callbacks.append(callback_query_id)

    async def close(self):
        self.closed = True


def update(update_id=1, text="to dev hello", *, user_id=42, chat_type="private"):
    return {
        "update_id": update_id,
        "message": {"from": {"id": user_id, "username": "tester"},
                    "chat": {"id": 42, "type": chat_type}, "text": text},
    }


def done(*, usage=None, content="最终答复", turn_id="turn-1", message_id="message-1"):
    return {
        "type": "done", "turn_id": turn_id, "assistant_message_id": message_id,
        "message": {"id": message_id, "turn_id": turn_id, "conversation_id": "conv-1",
                    "content": content, "meta": {"completion_state": "completed", "context_usage": usage}},
        "returncode": 0,
    }


def install_stream(monkeypatch, events):
    calls = []

    async def stream(*args, **kwargs):
        calls.append((args, kwargs))
        for event in events:
            yield event

    monkeypatch.setattr(api_service, "stream_chat", stream)
    return calls


@pytest_asyncio.fixture
async def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", tmp_path / "app_settings.json")
    manager = MultiBotManager(
        BotProfile(alias="main", cli_type="codex", cli_path="codex", working_dir=str(tmp_path)),
        str(tmp_path / "managed_bots.json"),
    )
    for alias in ("dev", "ops", "disabled", "archived"):
        manager.managed_profiles[alias] = BotProfile(
            alias=alias, cli_type="codex", cli_path="codex", working_dir=str(tmp_path),
            enabled=alias != "disabled", archived=alias == "archived",
        )
    instance = TelegramGateway(manager, FakeTelegramClient(), TelegramState(tmp_path / "telegram.sqlite3", "123"), {42})
    yield instance
    await instance.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,chat_type", [(99, "private"), ("42", "private"), (42, "group"), (42, "supergroup")])
async def test_only_numeric_whitelisted_private_sender_can_execute(gateway, monkeypatch, user_id, chat_type):
    calls = install_stream(monkeypatch, [done()])
    assert gateway.receive_update(update(user_id=user_id, chat_type=chat_type)) is None
    assert calls == []
    assert gateway.client.messages == []
    assert gateway.state.get(1)["status"] == "ignored"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/start", "/help", "普通正文", "to dev", "to missing hello", "to disabled hello", "to archived hello"])
async def test_help_and_invalid_targets_never_execute(gateway, monkeypatch, text):
    calls = install_stream(monkeypatch, [done()])
    await gateway.receive_update(update(text=text))
    assert calls == []
    result = gateway.client.messages[0][1]
    assert "• dev" in result and "• ops" in result
    assert "• disabled" not in result and "• archived" not in result


@pytest.mark.asyncio
async def test_routes_to_main_agent_with_shared_identity_and_preserves_multiline(gateway, monkeypatch):
    calls = install_stream(monkeypatch, [done(usage={"context_left_percent": 72})])
    body = "  def answer():\n      return 42\n\n末尾\n"
    await gateway.receive_update(update(text="to DEV\n" + body))
    args, kwargs = calls[0]
    assert args == (gateway.manager, "dev", chat_session_user_id(42), body)
    assert kwargs["agent_id"] == "main" and kwargs["include_trace"] is False
    assert kwargs["actor"]["user_id"] == 42
    assert gateway.client.messages == [(42, "[dev]\n\n最终答复\n\ncontext left: 72%")]
    row = gateway.state.get(1)
    assert (row["conversation_id"], row["turn_id"], row["assistant_message_id"]) == ("conv-1", "turn-1", "message-1")


@pytest.mark.parametrize("text,body", [("to dev a\nb", "a\nb"), ("to dev\r\n  a\r\nb", "  a\r\nb"), ("to dev \n  x", "  x")])
def test_multiline_route_separator(text, body):
    assert parse_target_text(text) == ("dev", body)


@pytest.mark.asyncio
async def test_progress_and_native_final_events_produce_one_terminal_reply(gateway, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def stream(*args, **kwargs):
        yield {"type": "meta", "turn_id": "turn-1", "assistant_message_id": "message-1"}
        yield {"type": "status", "preview_text": "临时正文"}
        yield {"type": "trace", "event": {"summary": "执行工具"}}
        yield {"type": "ag_ui", "event": {"type": "RUN_FINISHED", "result": {"content": "原生最终正文"}}}
        entered.set()
        await release.wait()
        yield done()

    monkeypatch.setattr(api_service, "stream_chat", stream)
    task = gateway.receive_update(update())
    await asyncio.wait_for(entered.wait(), 2)
    assert gateway.client.messages == []
    assert gateway.state.get(1)["status"] == "running"
    assert gateway.state.get(1)["turn_id"] == "turn-1"
    release.set()
    await task
    assert gateway.client.messages == [(42, "[dev]\n\n最终答复\n\ncontext left: unknown")]


@pytest.mark.asyncio
async def test_repeated_update_is_claimed_once_before_execution_and_after_reopen(gateway, monkeypatch, tmp_path):
    calls = install_stream(monkeypatch, [done()])
    task = gateway.receive_update(update())
    assert gateway.receive_update(update()) is None
    await task
    assert gateway.receive_update(update()) is None
    reopened = TelegramState(tmp_path / "telegram.sqlite3", "123")
    try:
        assert not reopened.claim(1, user_id=42, chat_id=42)
        assert reopened.next_offset() == 2
        assert reopened.get(1)["status"] == "completed"
    finally:
        reopened.close()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_polling_and_different_targets_continue_while_a_turn_runs(gateway, monkeypatch):
    started = set()
    release, polled_again, both_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    offsets = []

    async def get_updates(offset):
        offsets.append(offset)
        if len(offsets) == 1:
            return [update(5, "to dev one"), update(6, "to ops two")]
        polled_again.set()
        await asyncio.Event().wait()

    async def stream(manager, alias, user_id, text, **kwargs):
        started.add(alias)
        if len(started) == 2:
            both_started.set()
        await release.wait()
        yield done(content=alias)

    gateway.client.get_updates = get_updates
    monkeypatch.setattr(api_service, "stream_chat", stream)
    gateway.start()
    await asyncio.wait_for(asyncio.gather(polled_again.wait(), both_started.wait()), 2)
    assert offsets == [0, 7]
    assert gateway.client.messages == []
    assert gateway.state.next_offset() == 7
    release.set()
    await asyncio.gather(*list(gateway._tasks))
    assert {text.splitlines()[0] for _, text in gateway.client.messages} == {"[dev]", "[ops]"}


@pytest.mark.asyncio
async def test_polling_cursor_can_decrease_after_telegram_resets_update_ids(gateway, monkeypatch, tmp_path):
    gateway.state.claim(900, user_id=42, chat_id=42)
    calls = install_stream(monkeypatch, [done()])
    offsets = []
    third_poll = asyncio.Event()

    async def get_updates(offset):
        offsets.append(offset)
        if len(offsets) == 3:
            third_poll.set()
            await asyncio.Event().wait()
        if offset == 102:
            return [update(102)]
        return [update(100), update(101)]

    gateway.client.get_updates = get_updates
    gateway.start()
    await asyncio.wait_for(third_poll.wait(), 2)
    await asyncio.gather(*list(gateway._tasks))
    assert offsets == [901, 102, 103]
    assert len(calls) == 3
    reopened = TelegramState(tmp_path / "telegram.sqlite3", "123")
    try:
        assert reopened.next_offset() == 103
        assert not reopened.claim(100, user_id=42, chat_id=42)
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_terminal_event_cannot_switch_to_another_turn(gateway, monkeypatch):
    install_stream(monkeypatch, [
        {"type": "meta", "turn_id": "turn-1", "assistant_message_id": "message-1"},
        done(content="别的轮次", turn_id="turn-other", message_id="other"),
        done(content="本轮答复"),
    ])
    await gateway.receive_update(update())
    assert "本轮答复" in gateway.client.messages[0][1]
    assert "别的轮次" not in gateway.client.messages[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("events,expected,status", [
    ([{"type": "error", "code": "session_busy", "message": "当前任务运行中"}], "当前任务运行中", "rejected"),
    ([{"type": "status", "preview_text": "未完成正文"}], "未收到最终结果", "failed"),
])
async def test_errors_and_missing_final_are_reported_once(gateway, monkeypatch, events, expected, status):
    install_stream(monkeypatch, events)
    await gateway.receive_update(update())
    assert len(gateway.client.messages) == 1
    assert expected in gateway.client.messages[0][1]
    assert gateway.state.get(1)["status"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,expected_mode", [("native_agent", "native_agent"), ("codex", "cli")])
async def test_current_conversation_mode_wins_over_profile_default(gateway, monkeypatch, provider, expected_mode):
    profile, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 42)
    profile.supported_execution_modes = ["cli", "native_agent"]
    profile.default_execution_mode = "cli" if expected_mode == "native_agent" else "native_agent"
    session.active_conversation_id = "conv-1"
    store = Mock()
    store.get_conversation.return_value = {"native_provider": provider}
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _: store)
    calls = []

    async def cli_stream(*args, **kwargs):
        calls.append("cli")
        yield done()

    async def native_stream(*args, **kwargs):
        assert kwargs["protocol"] == "ag-ui"
        calls.append("native_agent")
        yield done()

    monkeypatch.setattr(api_service, "_stream_cli_chat", cli_stream)
    monkeypatch.setattr(api_service, "_stream_native_agent_chat", native_stream)
    await gateway.receive_update(update())
    assert calls == [expected_mode]


@pytest.mark.asyncio
async def test_context_fallback_uses_bound_final_message(gateway, monkeypatch):
    store = Mock()
    store.get_message.return_value = {
        "turn_id": "turn-1", "conversation_id": "conv-1", "meta": {"context_usage": {"used_tokens": 28, "context_window": 100}},
    }
    monkeypatch.setattr(api_service, "_get_chat_store", lambda _: store)
    install_stream(monkeypatch, [done()])
    await gateway.receive_update(update())
    store.get_message.assert_called_once_with("message-1")
    assert gateway.client.messages[0][1].endswith("context left: 72%")


@pytest.mark.parametrize("usage,expected", [
    (None, "unknown"), ({}, "unknown"),
    ({"context_left_percent": 72, "context_used_percent": 90}, "72%"),
    ({"contextUsedPercent": 28}, "72%"),
    ({"context_used": 28, "used_tokens": 99, "context_window": 100}, "72%"),
    ({"usedTokens": 28, "contextWindow": 100}, "72%"),
    ({"context_used": 101, "context_window": 100}, "0%"),
    ({"context_left_percent": 200}, "100%"),
    ({"context_left_percent": 72.25}, "72.3%"),
    ({"context_left_percent": float("nan")}, "unknown"),
    ({"context_used": -1, "context_window": 100}, "unknown"),
    ({"context_used": 28, "context_window": 0}, "unknown"),
    ({"context_left_percent": True}, "unknown"),
])
def test_context_left_precedence_and_valid_boundaries(usage, expected):
    assert context_left(usage) == expected


@pytest.mark.parametrize("content", ["x" * 4069, "x" * 4096, "x" * 8192, "代码\n🧪" * 2200], ids=["near-limit", "at-limit", "two-pages", "unicode"])
def test_long_answers_preserve_all_text_and_keep_footer_in_last_segment(content):
    parts = format_result("dev", content, None)
    footer = "\n\ncontext left: unknown"
    assert all(0 < len(part.encode("utf-16-le")) // 2 <= 4096 for part in parts)
    assert all(part.startswith("[dev]\n\n") for part in parts)
    assert all("context left:" not in part for part in parts[:-1])
    assert parts[-1].endswith(footer)
    reconstructed = "".join(part[len("[dev]\n\n"):] for part in parts)
    assert reconstructed[:-len(footer)] == content


@pytest.mark.asyncio
async def test_send_failure_does_not_reexecute_or_send_another_answer(gateway, monkeypatch, caplog):
    calls = install_stream(monkeypatch, [done()])
    gateway.client.send_message = AsyncMock(side_effect=TelegramError("sendMessage"))
    await gateway.receive_update(update())
    assert gateway.receive_update(update()) is None
    assert len(calls) == 1
    assert gateway.state.get(1)["status"] == "completed"
    assert gateway.state.get(1)["delivery_status"] == "failed"
    gateway.client.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,token,allowed", [(False, "123:secret", {42}), (True, "123:secret", set()), (True, "", {42})])
async def test_disabled_or_incomplete_config_does_not_open_transport(monkeypatch, enabled, token, allowed):
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", enabled)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_USER_IDS", allowed)
    client = Mock(side_effect=AssertionError("transport must stay closed"))
    monkeypatch.setattr("bot.telegram.gateway.TelegramClient", client)
    assert await start_telegram_gateway(Mock()) is None
    client.assert_not_called()


def test_telegram_allowlist_is_independent_of_shared_web_identity(monkeypatch):
    try:
        with monkeypatch.context() as patch:
            patch.setenv("TELEGRAM_ENABLED", "true")
            patch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
            patch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42, 43, -1, username, 0, 42")
            patch.setenv("ALLOWED_USER_IDS", "1001")
            config._refresh_environment_config()
            assert config.TELEGRAM_ENABLED
            assert config.TELEGRAM_ALLOWED_USER_IDS == {42, 43}
            assert config.ALLOWED_USER_IDS == [1001]
    finally:
        config._refresh_environment_config()


@pytest.mark.asyncio
async def test_transport_errors_do_not_expose_token():
    client = TelegramClient("123:secret-for-test")
    client._session = Mock()
    client._session.post.side_effect = aiohttp.ClientConnectionError(client._base_url)
    with pytest.raises(TelegramError) as error:
        await client.get_updates(9)
    assert "secret-for-test" not in str(error.value)


@pytest.mark.asyncio
async def test_web_and_telegram_share_history_and_new_conversation_resets_binding(gateway, monkeypatch):
    def process(*args, **kwargs):
        return SimpleNamespace(
            poll=Mock(return_value=0), wait=Mock(return_value=0), terminate=Mock(), kill=Mock(),
            stdout=io.StringIO(
                '{"type":"thread.started","thread_id":"telegram-thread"}\n'
                '{"type":"item.completed","item":{"type":"assistant_message","text":"shared answer"}}\n'
                '{"type":"turn.completed"}\n'
            ),
            stdin=None, pid=None, returncode=0,
        )

    monkeypatch.setattr(api_service, "_start_codex_rate_limit_capture", AsyncMock(return_value=SimpleNamespace(record_once=AsyncMock())))
    monkeypatch.setattr(api_service, "resolve_cli_executable", lambda *_: "codex")
    build_command = Mock(return_value=(["codex"], False))
    monkeypatch.setattr(api_service, "build_cli_command", build_command)
    monkeypatch.setattr(api_service, "resolve_cli_context_usage", lambda *_, **__: {"context_left_percent": 72})
    monkeypatch.setattr(api_service.subprocess, "Popen", process)
    web_events = [event async for event in api_service.stream_chat(gateway.manager, "dev", 1001, "remember marker-42")]
    assert web_events[-1]["type"] == "done"
    assert build_command.call_args.kwargs["session_id"] is None
    await asyncio.wait_for(gateway.receive_update(update(text="to dev //status")), 10)
    assert build_command.call_args.kwargs["user_text"] == "/status"
    assert build_command.call_args.kwargs["session_id"] == "telegram-thread"
    assert gateway.client.messages == [(42, "[dev]\n\nshared answer\n\ncontext left: 72%")]
    row = gateway.state.get(1)
    _, _, web_session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 1001)
    stored = api_service._get_chat_store(web_session).get_message(row["assistant_message_id"])
    assert stored["content"] == "shared answer"
    assert stored["conversation_id"] == web_session.active_conversation_id
    assert stored["turn_id"] == row["turn_id"]
    await api_service.run_chat(gateway.manager, "dev", 1001, "web follow-up")
    assert build_command.call_args.kwargs["session_id"] == "telegram-thread"
    store = api_service._get_chat_store(web_session)
    previous = web_session.active_conversation_id
    history = store.list_messages(previous)
    assert [item["content"] for item in history if item["role"] == "user"] == ["remember marker-42", "//status", "web follow-up"]

    call_count = build_command.call_count
    await gateway.receive_update(update(2, "to dev /new"))
    assert gateway.receive_update(update(2, "to dev /new")) is None
    current = web_session.active_conversation_id
    assert current != previous and current == gateway.state.get(2)["conversation_id"]
    assert web_session.codex_session_id is None
    assert build_command.call_count == call_count
    assert store.list_messages(current) == []
    assert store.list_messages(previous) == history
    assert "context left:" not in gateway.client.messages[-1][1]

    await gateway.receive_update(update(3, "to dev fresh message"))
    assert build_command.call_args.kwargs["session_id"] is None
    assert gateway.state.get(3)["conversation_id"] == current
    assert store.list_messages(previous) == history


@pytest.mark.asyncio
@pytest.mark.parametrize("current_mode", ["cli", "native_agent", None])
async def test_new_preserves_current_mode_or_uses_profile_default_without_starting_model(gateway, monkeypatch, current_mode):
    profile, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 42)
    profile.supported_execution_modes = ["cli", "native_agent"]
    profile.default_execution_mode = "native_agent" if current_mode != "native_agent" else "cli"
    if current_mode:
        await api_service.create_conversation(gateway.manager, "dev", 1001, execution_mode=current_mode)
    for name in ("codex_session_id", "claude_session_id", "native_agent_session_id", "native_agent_run_id", "native_agent_server_key"):
        setattr(session, name, "old-binding")
    calls = install_stream(monkeypatch, [done()])
    await gateway.receive_update(update(text="to dev /new"))
    assert calls == []
    assert gateway.state.get(1)["status"] == "completed"
    conversation = api_service._get_chat_store(session).get_conversation(session.active_conversation_id)
    assert api_service._conversation_execution_mode(conversation) == (current_mode or profile.default_execution_mode)
    assert all(getattr(session, name) is None for name in ("codex_session_id", "claude_session_id", "native_agent_session_id", "native_agent_run_id", "native_agent_server_key"))


@pytest.mark.asyncio
async def test_busy_web_turn_rejects_telegram_send_and_new(gateway):
    _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 1001)
    session.is_processing = True
    try:
        await gateway.receive_update(update(1, "to dev hello"))
        await gateway.receive_update(update(2, "to dev /new"))
        assert [gateway.state.get(i)["status"] for i in (1, 2)] == ["rejected", "rejected"]
        assert session.active_conversation_id is None
        assert session.is_processing
    finally:
        session.is_processing = False


@pytest.mark.asyncio
async def test_disabled_current_mode_does_not_redirect_to_profile_default(gateway, monkeypatch):
    profile, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 42)
    profile.supported_execution_modes = ["cli", "native_agent"]
    result = await api_service.create_conversation(gateway.manager, "dev", 1001, execution_mode="native_agent")
    profile.supported_execution_modes = ["cli"]
    stream = Mock(side_effect=AssertionError("disabled mode must not execute"))
    monkeypatch.setattr(api_service, "_stream_cli_chat", stream)
    await gateway.receive_update(update(1, "to dev hello"))
    await gateway.receive_update(update(2, "to dev /new"))
    assert session.active_conversation_id == result["conversation"]["id"]
    assert all("执行模式已停用" in text for _, text in gateway.client.messages)
    stream.assert_not_called()


@pytest.mark.asyncio
async def test_pending_cluster_children_block_new_conversation(gateway, monkeypatch):
    result = await api_service.create_conversation(gateway.manager, "dev", 1001)
    pending = Mock(return_value=True)
    monkeypatch.setattr(api_service._CLUSTER_RUNTIME, "has_pending_tasks", pending)
    await gateway.receive_update(update(text="to dev /new"))
    assert gateway.state.get(1)["status"] == "rejected"
    assert "子任务运行" in gateway.client.messages[0][1]
    _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 1001)
    assert session.active_conversation_id == result["conversation"]["id"]
    pending.assert_called_once_with(bot_alias="dev", user_id=chat_session_user_id(42), main_conversation_id=session.active_conversation_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cli", "native_agent"])
async def test_telegram_preparation_blocks_same_target_web_switch_and_allows_other_targets(gateway, monkeypatch, mode):
    profile = gateway.manager.managed_profiles["dev"]
    profile.supported_execution_modes = ["cli", "native_agent"]
    result = await api_service.create_conversation(gateway.manager, "dev", 1001, execution_mode=mode)
    conversation_id = result["conversation"]["id"]
    entered, release = asyncio.Event(), asyncio.Event()

    async def stream(manager, alias, *args, **kwargs):
        if alias == "dev":
            entered.set()
            await release.wait()
        yield done()

    monkeypatch.setattr(api_service, "_stream_cli_chat", stream)
    monkeypatch.setattr(api_service, "_stream_native_agent_chat", stream)
    task = gateway.receive_update(update())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await gateway.receive_update(update(2, "to dev concurrent"))
        assert gateway.state.get(2)["status"] == "rejected"
        with pytest.raises(WebApiError) as error:
            await api_service.select_conversation(gateway.manager, "dev", 1001, conversation_id)
        assert error.value.code == "conversation_switch_blocked"
        with pytest.raises(WebApiError) as error:
            await api_service.run_chat(gateway.manager, "dev", 1001, "concurrent Web send")
        assert error.value.code == "session_busy"
        await gateway.receive_update(update(3, "to ops hello"))
        assert gateway.state.get(3)["status"] == "completed"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await gateway.receive_update(update(4, "to dev /new"))
    assert gateway.state.get(4)["status"] == "completed"


@pytest.mark.asyncio
async def test_native_reconnect_observes_busy_turn_without_starting_another(gateway, monkeypatch):
    profile, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 1001)
    profile.supported_execution_modes = ["cli", "native_agent"]

    async def replay(*, after_sequence):
        assert after_sequence == 4
        yield {"type": "status", "turn_id": "existing-turn", "sequence": 5}

    service = SimpleNamespace(
        resume_turn_channel=Mock(return_value=SimpleNamespace(events=replay)),
        stream_chat=Mock(side_effect=AssertionError("reconnect must not execute")),
    )
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: service)
    with api_service._session_lifecycle_scope(session):
        events = [event async for event in api_service.stream_chat(
            gateway.manager, "dev", 1001, "", execution_mode="native_agent",
            resume_stream_id="existing-stream", resume_turn_id="existing-turn", after_sequence=4,
        )]
        assert events == [{"type": "status", "turn_id": "existing-turn", "sequence": 5}]
        await gateway.receive_update(update())
        assert gateway.state.get(1)["status"] == "rejected"
    service.resume_turn_channel.assert_called_once_with("existing-stream", turn_id="existing-turn")
    service.stream_chat.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "select"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_web_conversation_operation_blocks_telegram_until_store_worker_finishes(gateway, monkeypatch, operation, cancel):
    monkeypatch.setenv("TCB_ASYNC_CHAT_STORE", "true")
    target = None
    if operation == "select":
        result = await api_service.create_conversation(gateway.manager, "dev", 1001)
        target = result["conversation"]["id"]
        await api_service.create_conversation(gateway.manager, "dev", 1001)
    worker_name = f"_{operation}_conversation_locked"
    original = getattr(api_service, worker_name)
    entered, release = threading.Event(), threading.Event()

    def worker(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(api_service, worker_name, worker)
    action = (api_service.create_conversation(gateway.manager, "dev", 1001) if operation == "create"
              else api_service.select_conversation(gateway.manager, "dev", 1001, target))
    task = asyncio.create_task(action)
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        if cancel:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
        await gateway.receive_update(update(1, "to dev hello"))
        await gateway.receive_update(update(2, "to dev /new"))
        assert [gateway.state.get(i)["status"] for i in (1, 2)] == ["rejected", "rejected"]
        assert not task.done()
    finally:
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        else:
            await asyncio.wait_for(task, 5)
    _, _, session = api_service.get_chat_session_for_alias(gateway.manager, "dev", 1001)
    assert session.active_conversation_id
    if target:
        assert session.active_conversation_id == target
    await gateway.receive_update(update(3, "to dev /new"))
    assert gateway.state.get(3)["status"] == "completed"
