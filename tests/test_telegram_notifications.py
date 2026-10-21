from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from bot import config
from bot.telegram.client import TelegramError
from bot.telegram.notifications import TelegramCompletionNotification, TelegramCompletionNotifier
from bot.telegram.state import TelegramState
from bot.web import api_service
from tests.test_telegram_gateway import FakeTelegramClient, done, gateway


def test_broadcast_config_defaults_to_disabled(monkeypatch):
    try:
        monkeypatch.delenv("TELEGRAM_BROADCAST_COMPLETIONS", raising=False)
        config._refresh_environment_config()
        assert config.TELEGRAM_BROADCAST_COMPLETIONS is False
        monkeypatch.setenv("TELEGRAM_BROADCAST_COMPLETIONS", "true")
        config._refresh_environment_config()
        assert config.TELEGRAM_BROADCAST_COMPLETIONS is True
    finally:
        monkeypatch.delenv("TELEGRAM_BROADCAST_COMPLETIONS", raising=False)
        config._refresh_environment_config()


def test_binding_refresh_is_scoped_to_alias_and_agent(tmp_path):
    state = TelegramState(tmp_path / "telegram.sqlite3", "123")
    try:
        state.bind_conversation(
            chat_id=42,
            telegram_user_id=42,
            shared_user_id=1001,
            alias="dev",
            agent_id="main",
            conversation_id="conv-1",
        )
        assert state.is_conversation_bound("dev", "main", "conv-1", chat_id=42)
        state.bind_conversation(
            chat_id=42,
            telegram_user_id=42,
            shared_user_id=1001,
            alias="dev",
            agent_id="main",
            conversation_id="conv-2",
        )
        assert not state.is_conversation_bound("dev", "main", "conv-1", chat_id=42)
        assert [row["conversation_id"] for row in state.list_bound_chats("dev", "main", "conv-2")] == ["conv-2"]
    finally:
        state.close()


@pytest.mark.asyncio
async def test_web_cli_completion_uses_matching_binding(gateway, monkeypatch):
    gateway.state.bind_conversation(
        chat_id=42,
        telegram_user_id=42,
        shared_user_id=1001,
        alias="dev",
        agent_id="main",
        conversation_id="conv-1",
    )

    async def stream(*_args, **_kwargs):
        yield done(content="来自 Web")

    monkeypatch.setattr(api_service, "_stream_cli_chat", stream)
    events = [event async for event in api_service.stream_chat(gateway.manager, "dev", 1001, "hello")]

    assert events[-1]["type"] == "done"
    assert gateway.client.messages == [(42, "[dev]\n\n来自 Web\n\ncontext left: unknown")]
    assert gateway.client.markups[-1] is not None


@pytest.mark.asyncio
async def test_web_native_completion_uses_matching_binding(gateway, monkeypatch):
    profile = gateway.manager.managed_profiles["dev"]
    profile.supported_execution_modes = ["cli", "native_agent"]
    gateway.state.bind_conversation(
        chat_id=42,
        telegram_user_id=42,
        shared_user_id=1001,
        alias="dev",
        agent_id="main",
        conversation_id="conv-1",
    )

    async def stream(*_args, **_kwargs):
        yield done(content="来自 Pi")

    monkeypatch.setattr(api_service, "_stream_native_agent_chat", stream)
    events = [
        event async for event in api_service.stream_chat(
            gateway.manager,
            "dev",
            1001,
            "hello",
            execution_mode="native_agent",
        )
    ]

    assert events[-1]["type"] == "done"
    assert gateway.client.messages == [(42, "[dev]\n\n来自 Pi\n\ncontext left: unknown")]


@pytest.mark.asyncio
async def test_broadcast_reaches_allowed_users_and_leaves_broadcast_only_text(gateway):
    notifier = gateway.completion_notifier
    notifier.allowed_user_ids = frozenset({42, 43})
    notifier.broadcast_enabled = True
    gateway.state.bind_conversation(
        chat_id=42,
        telegram_user_id=42,
        shared_user_id=1001,
        alias="dev",
        agent_id="main",
        conversation_id="conv-1",
    )

    await notifier.notify_completion(
        TelegramCompletionNotification(
            alias="dev",
            conversation_id="conv-1",
            turn_id="turn-1",
            assistant_message_id="message-1",
            content="广播答复",
        )
    )

    assert [chat_id for chat_id, _text in gateway.client.messages] == [42, 43]
    assert gateway.client.markups[0] is not None
    assert gateway.client.markups[1] is None


@pytest.mark.asyncio
async def test_broadcast_excludes_telegram_source_chat_and_is_idempotent(gateway):
    notifier = gateway.completion_notifier
    notifier.allowed_user_ids = frozenset({42, 43})
    notifier.broadcast_enabled = True
    completion = TelegramCompletionNotification(
        alias="dev",
        conversation_id="conv-1",
        turn_id="turn-1",
        assistant_message_id="message-1",
        content="只应发送一次",
        source_chat_id=42,
    )

    await notifier.notify_completion(completion)
    await notifier.notify_completion(completion)

    assert [chat_id for chat_id, _text in gateway.client.messages] == [43]
    assert gateway.state.get_completion_notification("turn-1:43")["status"] == "sent"


@pytest.mark.asyncio
async def test_telegram_source_is_sent_once_when_broadcast_is_enabled(gateway, monkeypatch):
    notifier = gateway.completion_notifier
    notifier.allowed_user_ids = frozenset({42, 43})
    notifier.broadcast_enabled = True

    async def stream(*_args, **_kwargs):
        yield done(content="Telegram 发起")

    monkeypatch.setattr(api_service, "_stream_cli_chat", stream)
    await gateway.receive_update({
        "update_id": 1,
        "message": {
            "from": {"id": 42, "username": "tester"},
            "chat": {"id": 42, "type": "private"},
            "text": "to dev hello",
        },
    })

    assert [chat_id for chat_id, _text in gateway.client.messages].count(42) == 1
    assert [chat_id for chat_id, _text in gateway.client.messages].count(43) == 1


@pytest.mark.asyncio
async def test_notification_retry_does_not_reexecute_or_block_other_recipients(gateway):
    notifier = gateway.completion_notifier
    notifier.allowed_user_ids = frozenset({42, 43})
    notifier.broadcast_enabled = True
    gateway.client.send_message = AsyncMock(
        side_effect=[TelegramError("sendMessage", code=500), {"message_id": 2}, {"message_id": 3}]
    )
    notifier._schedule_retry = Mock()

    await notifier.notify_completion(
        TelegramCompletionNotification(
            alias="dev",
            conversation_id="conv-1",
            turn_id="turn-retry",
            assistant_message_id="message-retry",
            content="可恢复",
        )
    )

    failed = gateway.state.get_completion_notification("turn-retry:42")
    sent = gateway.state.get_completion_notification("turn-retry:43")
    assert failed["status"] == "failed"
    assert sent["status"] == "sent"
    assert notifier._schedule_retry.called

    gateway.state.mark_completion_notification_part_failed(
        "turn-retry:42", 0, "retry now", retry_at=0,
    )
    await notifier._deliver_persisted("turn-retry:42")
    assert gateway.state.get_completion_notification("turn-retry:42")["status"] == "sent"


@pytest.mark.asyncio
async def test_notification_recovery_after_state_reopen(tmp_path):
    path = tmp_path / "telegram.sqlite3"
    state = TelegramState(path, "123")
    first_client = FakeTelegramClient()
    first_client.send_message = AsyncMock(side_effect=TelegramError("sendMessage", code=500))
    first = TelegramCompletionNotifier(state, first_client, {42}, broadcast_enabled=True)
    first._schedule_retry = Mock()
    await first.notify_completion(
        TelegramCompletionNotification(
            alias="dev",
            conversation_id="conv-1",
            turn_id="turn-restart",
            assistant_message_id="message-restart",
            content="重启恢复",
        )
    )
    state.mark_completion_notification_part_failed("turn-restart:42", 0, "retry now", retry_at=0)
    state.close()

    reopened = TelegramState(path, "123")
    second_client = FakeTelegramClient()
    second_client.send_message = AsyncMock(return_value={"message_id": 9})
    second = TelegramCompletionNotifier(reopened, second_client, {42}, broadcast_enabled=True)
    try:
        await second.recover()
        assert reopened.get_completion_notification("turn-restart:42")["status"] == "sent"
        second_client.send_message.assert_awaited_once()
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_permanent_telegram_rejection_is_not_rescheduled(gateway):
    notifier = gateway.completion_notifier
    notifier.broadcast_enabled = True
    notifier._schedule_retry = Mock()
    gateway.client.send_message = AsyncMock(side_effect=TelegramError("sendMessage", code=400))
    completion = TelegramCompletionNotification(
        alias="dev",
        conversation_id="conv-1",
        turn_id="turn-permanent",
        assistant_message_id="message-permanent",
        content="拒绝",
    )

    await notifier.notify_completion(completion)
    await notifier.notify_completion(completion)

    assert not notifier._schedule_retry.called
    record = gateway.state.get_completion_notification("turn-permanent:42")
    assert record["status"] == "failed"
    assert record["retry_at"] == float("inf")

