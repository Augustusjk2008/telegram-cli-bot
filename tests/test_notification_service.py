from __future__ import annotations

import pytest

from bot.web.notification_service import ChatNotificationService
from bot.web.server import WebApiServer


def test_notification_payload_uses_persisted_message_terminal_time() -> None:
    server = object.__new__(WebApiServer)
    server._chat_notification_url = lambda alias, conversation_id="": f"/{alias}/{conversation_id}"  # type: ignore[method-assign]

    payload = server._extract_chat_notification_payload(
        alias="main",
        agent_id="main",
        data={
            "message": {
                "id": "assistant-1",
                "state": "done",
                "updated_at": "2026-08-27T01:10:00+00:00",
            },
            "session": {"active_conversation_id": "conversation-1"},
        },
    )

    assert payload["terminal_at"] == "2026-08-27T01:10:00+00:00"


@pytest.mark.asyncio
async def test_chat_completion_event_exposes_canonical_terminal_time() -> None:
    service = ChatNotificationService()
    try:
        event = await service.notify_chat_completed(
            account_id="account-1",
            user_id=1,
            bot_alias="main",
            conversation_id="conversation-1",
            message_id="assistant-1",
            terminal_at="2026-08-27T01:10:00+00:00",
        )
    finally:
        await service.close()

    assert event is not None
    assert event["terminalAt"] == "2026-08-27T01:10:00+00:00"
