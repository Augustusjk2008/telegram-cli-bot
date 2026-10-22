from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from bot import config
from bot.telegram.client import TelegramError
from bot.telegram.formatting import telegram_html_to_text
from bot.telegram.notifications import TelegramCompletionNotification, TelegramCompletionNotifier
from bot.telegram.state import TelegramState
from bot.web import api_service
from tests.test_telegram_controls import button, callback, reply
from tests.test_telegram_gateway import FakeTelegramClient, done, gateway, update


def test_broadcast_config_defaults_to_disabled(monkeypatch):
    try:
        with monkeypatch.context() as patch:
            patch.delenv("TELEGRAM_BROADCAST_COMPLETIONS", raising=False)
            patch.delitem(config._DOTENV_VALUES, "TELEGRAM_BROADCAST_COMPLETIONS", raising=False)
            config._refresh_environment_config()
            assert config.TELEGRAM_BROADCAST_COMPLETIONS is False
            patch.setenv("TELEGRAM_BROADCAST_COMPLETIONS", "true")
            config._refresh_environment_config()
            assert config.TELEGRAM_BROADCAST_COMPLETIONS is True
    finally:
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
    assert gateway.client.messages == [(42, "🤖 <b>[dev]</b>\n\n来自 Web\n\ncontext left: unknown")]
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
    assert gateway.client.messages == [(42, "🤖 <b>[dev]</b>\n\n来自 Pi\n\ncontext left: unknown")]


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
        yield done(content="Telegram 发起" * 100 + "**全文末尾**")

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
    assert all("<b>全文末尾</b>" in text for _, text in gateway.client.messages)
    assert all(mode == "HTML" for mode in gateway.client.parse_modes)


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
            content="重启恢复" * 100 + "全文末尾",
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
        assert second_client.send_message.await_args.kwargs["parse_mode"] == "HTML"
        assert "全文末尾" not in second_client.send_message.await_args.args[1]
        assert "全文末尾" in "".join(reopened.get_completion_notification("turn-restart:42")["full_parts"])
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


@pytest.mark.asyncio
@pytest.mark.parametrize("expand_via", ["button", "reply", "latest", "token"])
async def test_broadcast_preview_expands_persisted_message_without_running_agent(gateway, monkeypatch, tmp_path, expand_via):
    notifier = gateway.completion_notifier
    notifier.broadcast_enabled = True
    original = "## 完成\n\n**重点** " + "结果🧪 & <tag>\n" * 600 + "\n原始末尾"
    await notifier.notify_completion(alias="dev", conversation_id="conv-old", turn_id="turn-old", content=original)
    preview_id = len(gateway.client.messages)
    token = button(gateway, "展开全文")["callback_data"]
    preview = telegram_html_to_text(gateway.client.messages[-1][1])
    assert len(gateway.client.messages) == 1
    assert "重点" in preview and "**" not in preview
    assert "原始末尾" not in preview and len(preview) < 400
    assert "/expand" in preview

    await notifier.notify_completion(
        alias="ops", conversation_id="conv-new", turn_id="turn-new", content="新的通知" * 100 + "最新末尾",
    )
    # Expansion stays tied to the delivered reply even after a restart and target change.
    gateway.state.close()
    gateway.state = TelegramState(tmp_path / "telegram.sqlite3", "123")
    notifier.state = gateway.state
    gateway.state.select_target(42, 42, "ops")
    agent = Mock(side_effect=AssertionError("expanding a notification must not run an agent"))
    monkeypatch.setattr(api_service, "stream_chat", agent)

    event = {
        "button": callback(1, token),
        "reply": reply(1, preview_id, "/expand"),
        "latest": update(1, "/expand"),
        "token": update(1, f"/expand {token}"),
    }[expand_via]
    before = len(gateway.client.messages)
    await gateway.receive_update(event)
    expanded = "".join(text for _, text in gateway.client.messages[before:])
    assert ("最新末尾" if expand_via == "latest" else "原始末尾") in expanded
    if expand_via != "latest":
        assert "最新末尾" not in expanded and "<b>重点</b>" in expanded
        assert len(gateway.client.messages) > before + 1
    assert all(mode == "HTML" for mode in gateway.client.parse_modes[before:])
    assert gateway.state.get_delivery_for_update(1)["status"] == "sent"
    assert gateway.state.selected_target(42, 42) == "ops"
    agent.assert_not_called()
    awaitable = gateway.receive_update(event)
    if awaitable is not None:
        await awaitable
    assert len(gateway.client.messages) == before + len(gateway.state.get_delivery_for_update(1)["parts"])


@pytest.mark.asyncio
@pytest.mark.parametrize("broadcast_enabled", [False, True])
async def test_bound_chat_only_gets_preview_in_broadcast_mode(gateway, broadcast_enabled):
    notifier = gateway.completion_notifier
    notifier.broadcast_enabled = broadcast_enabled
    gateway.state.bind_conversation(
        chat_id=42, telegram_user_id=42, shared_user_id=1001, alias="dev", conversation_id="conv-1",
    )
    await notifier.notify_completion(
        alias="dev", conversation_id="conv-1", turn_id="turn-1", content="正文" * 300 + "完整结尾",
    )
    markup = gateway.client.markups[-1]
    labels = {item["text"] for row in markup["inline_keyboard"] for item in row}
    assert {"继续聊", "新会话"} <= labels
    assert ("展开全文" in labels) is broadcast_enabled
    assert ("完整结尾" in gateway.client.messages[-1][1]) is not broadcast_enabled


@pytest.mark.asyncio
@pytest.mark.parametrize("expand_via", ["button", "reply", "token"])
async def test_expansion_cannot_read_another_recipients_notification(gateway, expand_via):
    gateway.completion_notifier.broadcast_enabled = True
    await gateway.completion_notifier.notify_completion(
        alias="dev", turn_id="turn-private", content="正文" * 300 + "私有结尾",
    )
    token = button(gateway, "展开全文")["callback_data"]
    gateway.allowed_user_ids = frozenset({42, 43})
    if expand_via == "button":
        event = callback(1, token, user_id=43, chat_id=43)
    else:
        event = update(1, "/expand" if expand_via == "reply" else f"/expand {token}", user_id=43)
        event["message"]["chat"]["id"] = 43
        if expand_via == "reply":
            event["message"]["reply_to_message"] = {"message_id": 1}
    await gateway.receive_update(event)
    assert gateway.state.get(1)["status"] == "rejected"
    assert "私有结尾" not in gateway.client.messages[-1][1]

