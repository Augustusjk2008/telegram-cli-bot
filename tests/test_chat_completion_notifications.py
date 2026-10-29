from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.telegram.notifications import (
    TelegramCompletionNotification,
    TelegramCompletionNotifier,
)
from bot.telegram.state import TelegramState
from bot.models import UserSession
from bot.web import api_service
from bot.web.notification_service import ChatNotificationService
from bot.web.server import WebApiServer


class _TelegramClient:
    def __init__(self) -> None:
        self.send_message = AsyncMock(side_effect=[
            {"message_id": 1},
            {"message_id": 2},
            {"message_id": 3},
        ])


def _completion(*, terminal_at: str = "", group_id: str = "") -> TelegramCompletionNotification:
    return TelegramCompletionNotification(
        alias="dev",
        conversation_id="conversation-1",
        turn_id="turn-1",
        assistant_message_id="assistant-1",
        content="answer",
        endless_group_id=group_id,
        terminal_at=terminal_at,
    )


@pytest.mark.asyncio
async def test_telegram_allows_new_endless_completion_generation_and_dedupes_retries(tmp_path):
    state = TelegramState(tmp_path / "telegram.sqlite3", "bot-1")
    client = _TelegramClient()
    state.bind_conversation(
        chat_id=42,
        telegram_user_id=42,
        shared_user_id=42,
        alias="dev",
        conversation_id="conversation-1",
    )
    notifier = TelegramCompletionNotifier(state, client, {42})
    try:
        old_ids = await notifier.notify_completion(_completion())
        first_ids = await notifier.notify_completion(_completion(group_id="endless-1", terminal_at="t1"))
        duplicate_ids = await notifier.notify_completion(_completion(group_id="endless-1", terminal_at="t1"))
        second_ids = await notifier.notify_completion(_completion(group_id="endless-1", terminal_at="t2"))

        assert old_ids == ["turn-1:42"]
        assert first_ids == ["turn-1:42:t1"]
        assert duplicate_ids == ["turn-1:42:t1"]
        assert second_ids == ["turn-1:42:t2"]
        assert client.send_message.await_count == 3
        assert state.get_completion_notification("turn-1:42") is not None
        assert state.get_completion_notification("turn-1:42:t1") is not None
        assert state.get_completion_notification("turn-1:42:t2") is not None
    finally:
        await notifier.close()
        state.close()


@pytest.mark.asyncio
async def test_api_completion_notification_forwards_endless_identity(monkeypatch):
    captured: list[TelegramCompletionNotification] = []

    class _Notifier:
        async def notify_completion(self, completion):
            captured.append(completion)

    monkeypatch.setattr(
        "bot.telegram.notifications.get_active_completion_notifier",
        lambda: _Notifier(),
    )
    await api_service._notify_telegram_completion(
        {
            "type": "done",
            "turn_id": "turn-1",
            "assistant_message_id": "assistant-1",
            "message": {
                "id": "assistant-1",
                "conversation_id": "conversation-1",
                "content": "answer",
                "updated_at": "2026-10-28T12:00:00+00:00",
                "meta": {
                    "completion_state": "completed",
                    "endless_group_id": "endless-1",
                },
            },
        },
        alias="dev",
        agent_id="main",
        source_chat_id=None,
    )

    assert len(captured) == 1
    assert captured[0].endless_group_id == "endless-1"
    assert captured[0].terminal_at == "2026-10-28T12:00:00+00:00"


def test_endless_completion_identity_adds_fallback_token():
    event = api_service._with_endless_completion_identity(
        {
            "type": "done",
            "message": {"meta": {"completion_state": "completed"}},
        },
        endless_group_id="endless-1",
        completion_token="token-1",
    )

    assert event["endless_group_id"] == "endless-1"
    assert event["endless_completion_token"] == "token-1"
    assert event["message"]["meta"]["endless_completion_token"] == "token-1"


def test_server_builds_endless_dedupe_key_from_terminal_identity():
    server = SimpleNamespace(_chat_notification_url=lambda alias, conversation_id: "/chat")
    payload = WebApiServer._extract_chat_notification_payload(
        server,
        alias="dev",
        agent_id="main",
        account_id="account-1",
        data={
            "message": {
                "id": "assistant-1",
                "conversation_id": "conversation-1",
                "updated_at": "2026-10-28T12:00:00+00:00",
                "meta": {"endless_group_id": "endless-1"},
            },
        },
    )

    assert payload["dedupe_key"] == (
        "endless:account-1:dev:main:conversation-1:endless-1:"
        "2026-10-28T12:00:00+00:00"
    )


@pytest.mark.asyncio
async def test_web_notification_service_allows_new_endless_generation_and_dedupes_retry():
    service = ChatNotificationService()
    try:
        first = await service.notify_chat_completed(
            account_id="account-1",
            user_id=42,
            bot_alias="dev",
            conversation_id="conversation-1",
            message_id="assistant-1",
            dedupe_key="endless:account-1:dev:main:conversation-1:endless-1:t1",
        )
        duplicate = await service.notify_chat_completed(
            account_id="account-1",
            user_id=42,
            bot_alias="dev",
            conversation_id="conversation-1",
            message_id="assistant-1",
            dedupe_key="endless:account-1:dev:main:conversation-1:endless-1:t1",
        )
        second = await service.notify_chat_completed(
            account_id="account-1",
            user_id=42,
            bot_alias="dev",
            conversation_id="conversation-1",
            message_id="assistant-1",
            dedupe_key="endless:account-1:dev:main:conversation-1:endless-1:t2",
        )

        assert first["dedupeKey"].endswith(":t1")
        assert duplicate is None
        assert second["dedupeKey"].endswith(":t2")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_endless_retry_stream_notifies_only_final_done_with_fallback_identity(monkeypatch, tmp_path):
    captured: list[TelegramCompletionNotification] = []

    class _Notifier:
        async def notify_completion(self, completion):
            captured.append(completion)

    monkeypatch.setattr(
        "bot.telegram.notifications.get_active_completion_notifier",
        lambda: _Notifier(),
    )
    monkeypatch.setattr(api_service.config, "ENDLESS_CONTINUE_DELAY_SECONDS", 0)
    session = UserSession(bot_id=1, bot_alias="dev", user_id=42, working_dir=str(tmp_path))
    request = api_service._ChatRunRequest(
        bot_alias="dev",
        user_id=42,
        text="question",
        endless_mode=True,
        endless_group_id="endless-1",
    )
    attempts = [
        {
            "type": "done",
            "turn_id": "turn-1",
            "assistant_message_id": "assistant-1",
            "message": {
                "id": "assistant-1",
                "turn_id": "turn-1",
                "conversation_id": "conversation-1",
                "content": "temporary failure",
                "state": "error",
                "meta": {"completion_state": "error"},
            },
        },
        {
            "type": "done",
            "turn_id": "turn-1",
            "assistant_message_id": "assistant-1",
            "message": {
                "id": "assistant-1",
                "turn_id": "turn-1",
                "conversation_id": "conversation-1",
                "content": "final answer",
                "state": "done",
                "meta": {"completion_state": "completed"},
            },
        },
    ]
    attempt_index = 0
    attempt_processing_states: list[bool] = []

    def attempt_factory(_text, _request):
        nonlocal attempt_index
        attempt_processing_states.append(session.is_processing)
        event = attempts[attempt_index]
        attempt_index += 1

        async def events():
            yield event

        return events()

    endless_stream = api_service._stream_endless_attempts(
        session=session,
        alias="dev",
        shared_user_id=42,
        initial_text="question",
        initial_request=request,
        attempt_factory=attempt_factory,
    )
    first_event = await anext(endless_stream)
    assert first_event["type"] == "endless_error"
    assert session.is_processing is True
    events = [
        first_event,
        *[
            event
            async for event in api_service._stream_with_telegram_completion_notifications(
                endless_stream,
                alias="dev",
                agent_id="main",
                source_chat_id=None,
            )
        ],
    ]

    assert [event["type"] for event in events] == ["endless_error", "endless_continue", "done"]
    assert attempt_processing_states == [False, False]
    assert len(captured) == 1
    assert captured[0].content == "final answer"
    assert captured[0].endless_group_id == "endless-1"
    assert captured[0].endless_completion_token.startswith("endless_completion_")
