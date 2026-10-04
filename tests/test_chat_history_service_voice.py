from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.models import UserSession
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


def _session(tmp_path):
    return UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=2,
        working_dir=str(tmp_path),
        _persist_enabled=False,
    )


@pytest.mark.asyncio
async def test_history_service_voice_contract_and_async_wrappers(tmp_path) -> None:
    service = ChatHistoryService(ChatStore(tmp_path))
    session = _session(tmp_path)
    handle = await service.ensure_voice_turn_async(
        session,
        bot_alias="main",
        task_submission_key="submission-1",
        codex_turn_id="codex-turn-1",
    )
    assert (await service.ensure_voice_turn_async(
        session,
        bot_alias="main",
        task_submission_key="submission-1",
        codex_turn_id="codex-turn-1",
    )) == handle
    snapshot = service.build_session_snapshot(
        SimpleNamespace(alias="main", cli_type="codex", cli_path="codex"),
        session,
    )
    assert snapshot["running_reply"]["voice"]["tcb_turn_id"] == handle.turn_id
    same_conversation = await service.ensure_voice_turn_async(
        session,
        bot_alias="main",
        task_submission_key="submission-2",
        codex_turn_id="codex-turn-2",
        conversation_id=handle.conversation_id,
    )
    assert same_conversation.conversation_id == handle.conversation_id

    assert await service.record_voice_event_async(
        handle,
        {
            "event_id": "event-1",
            "seq": 1,
            "role": "user",
            "transcript": "hello",
            "is_final": True,
        },
    ) is True
    assert await service.record_voice_event_async(
        handle,
        {"event_id": "event-1", "role": "user", "transcript": "duplicate"},
    ) is False
    assert await service.record_voice_event_async(
        session,
        handle,
        {"event_id": "event-2", "seq": 2, "role": "user", "transcript": "hello again"},
    ) is True
    appended = await service.append_user_message_to_turn_async(
        session,
        turn_id=handle.turn_id,
        conversation_id=handle.conversation_id,
        user_text="steer once",
        request_id="steer-1",
    )
    duplicate = await service.append_user_message_to_turn_async(
        session,
        turn_id=handle.turn_id,
        conversation_id=handle.conversation_id,
        user_text="steer retry",
        request_id="steer-1",
    )
    assert duplicate["id"] == appended["id"]
    found = await service.find_voice_steer_request_async(handle.turn_id, "steer-1")
    assert found is not None and found["id"] == appended["id"]
    task = await service.get_voice_task_async(handle)
    assert task["conversation_id"] == handle.conversation_id
    assert task["tcb_turn_id"] == handle.turn_id

    await service.complete_voice_turn_async(
        handle,
        content="",
        completion_state="unknown",
        native_session_id="runtime-1",
        error_code="runtime_closed",
        error_message="runtime closed",
    )
    assert (await service.get_voice_task_async(handle))["state"] == "unknown"
    assert await service.record_voice_event_async(
        handle,
        {"event_id": "late", "task_state": "completed", "transcript": "late"},
    ) is True
    assert (await service.get_voice_task_async(handle))["state"] == "unknown"
