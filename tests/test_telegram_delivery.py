from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from bot.telegram.client import TelegramError
from bot.telegram.state import TelegramState
from tests.test_telegram_gateway import done, gateway, install_stream, update


@pytest.mark.asyncio
async def test_final_result_is_durable_and_retry_does_not_execute_agent_again(gateway, monkeypatch):
    calls = install_stream(monkeypatch, [done(content="answer")])
    gateway.client.send_message = AsyncMock(
        side_effect=[TelegramError("sendMessage", code=429, retry_after=17), {"message_id": 2}],
    )
    scheduled = Mock()
    monkeypatch.setattr(gateway, "_schedule_delivery_retry", scheduled)

    await gateway.receive_update(update())
    delivery = gateway.state.get_delivery_for_update(1)
    assert delivery["status"] == "failed"
    assert delivery["part_records"][0]["status"] == "failed"
    assert scheduled.call_args.args[0] == delivery["delivery_id"]
    assert scheduled.call_args.args[1] == 17
    assert len(calls) == 1

    gateway.state.mark_delivery_part_failed(delivery["delivery_id"], 0, "retry now", retry_at=0)
    await gateway._deliver_persisted(delivery["delivery_id"])
    assert gateway.state.get_delivery(delivery["delivery_id"])["status"] == "sent"
    assert gateway.state.get(1)["delivery_status"] == "sent"
    assert len(calls) == 1
    assert gateway.client.send_message.await_count == 2


@pytest.mark.asyncio
async def test_partial_delivery_resumes_at_first_unsent_part(gateway, monkeypatch):
    install_stream(monkeypatch, [done(content="x" * 11000)])
    gateway.client.send_message = AsyncMock(
        side_effect=[{"message_id": 1}, TelegramError("sendMessage", code=500), {"message_id": 2}, {"message_id": 3}],
    )
    scheduled = Mock()
    monkeypatch.setattr(gateway, "_schedule_delivery_retry", scheduled)

    await gateway.receive_update(update())
    delivery = gateway.state.get_delivery_for_update(1)
    parts = delivery["part_records"]
    assert len(parts) >= 3
    assert [part["status"] for part in parts[:3]] == ["sent", "failed", "pending"]
    assert parts[0]["message_id"] == 1

    gateway.state.mark_delivery_part_failed(delivery["delivery_id"], 1, "retry now", retry_at=0)
    await gateway._deliver_persisted(delivery["delivery_id"])
    assert gateway.state.get_delivery(delivery["delivery_id"])["status"] == "sent"
    assert [part["status"] for part in gateway.state.get_delivery_parts(delivery["delivery_id"])] == ["sent"] * len(parts)
    assert gateway.client.send_message.await_count == len(parts) + 1


@pytest.mark.asyncio
async def test_restart_recovers_pending_delivery_without_reexecuting(gateway, tmp_path):
    gateway.state.claim(7, user_id=42, chat_id=42)
    gateway.state.update(7, alias="dev", status="completed", conversation_id="conv-1")
    delivery_id = gateway.state.create_delivery(7, 42, "dev", ["first", "second"], retry_at=0)
    gateway.state.mark_delivery_part_sent(delivery_id, 0, 100)
    gateway.state.mark_delivery_part_failed(delivery_id, 1, "temporary", retry_at=0)

    state_path = tmp_path / "telegram.sqlite3"
    gateway.state.close()
    gateway.state = TelegramState(state_path, "123")
    gateway.client.send_message = AsyncMock(return_value={"message_id": 101})

    await gateway._recover_state()
    retry_task = gateway._delivery_retry_tasks[delivery_id]
    await retry_task

    restored = gateway.state.get_delivery(delivery_id)
    assert restored["status"] == "sent"
    assert [part["message_id"] for part in restored["part_records"]] == [100, 101]
    gateway.client.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_marks_unknown_running_update_interrupted_and_sends_recovery_notice(gateway):
    gateway.state.claim(8, user_id=42, chat_id=42)
    gateway.state.update(8, alias="dev", status="running", conversation_id="conv-8")
    gateway.client.send_message = AsyncMock(return_value={"message_id": 201})

    await gateway._recover_state()

    row = gateway.state.get(8)
    assert row["status"] == "interrupted"
    assert row["delivery_status"] == "sent"
    assert "未能确认结果" in gateway.client.send_message.await_args.args[1]


def test_duplicate_update_does_not_lower_high_water_mark(tmp_path):
    state = TelegramState(tmp_path / "state.sqlite3", "123")
    try:
        assert state.claim(100, user_id=42, chat_id=42)
        assert state.claim(200, user_id=42, chat_id=42)
        assert not state.claim(100, user_id=42, chat_id=42)
        assert state.next_offset() == 201
    finally:
        state.close()

