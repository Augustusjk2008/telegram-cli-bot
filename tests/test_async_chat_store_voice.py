from __future__ import annotations

import pytest

from bot.web.async_chat_store import AsyncChatStore
from bot.web.chat_store import ChatStore


@pytest.mark.asyncio
async def test_async_chat_store_voice_wrappers_use_serialized_writes(tmp_path) -> None:
    store = AsyncChatStore(ChatStore(tmp_path))
    handle = await store.ensure_voice_turn(
        bot_id=1,
        bot_alias="main",
        user_id=2,
        working_dir=str(tmp_path),
        session_epoch=0,
        task_submission_key="submission-1",
        codex_turn_id="codex-turn-1",
    )
    assert await store.record_voice_event(
        handle,
        {"event_id": "event-1", "role": "assistant", "transcript": "answer", "is_final": True},
    ) is True
    assert await store.append_voice_trace(
        handle,
        [{"kind": "tool_call", "summary": "run tool"}],
    ) is True
    task = await store.get_voice_task(handle)
    assert task["persistence"]["trace"] is True
    await store.complete_voice_turn(handle, task_state="completed")
    assert (await store.get_voice_task(handle))["state"] == "completed"
