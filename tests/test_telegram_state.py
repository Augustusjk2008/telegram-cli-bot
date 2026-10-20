from __future__ import annotations

import asyncio
from unittest.mock import Mock

import aiohttp
import pytest

from bot.telegram.client import TelegramClient, TelegramError, TelegramTransportError
from bot.telegram.state import TelegramState


def _create(state: TelegramState, *, retry_at: float = 0) -> str:
    return state.create_delivery(
        17,
        42,
        "dev",
        ["first", "second", "third"],
        conversation_id="conversation-1",
        turn_id="turn-1",
        assistant_message_id="assistant-1",
        reply_markup={"inline_keyboard": [[{"text": "继续聊"}]]},
        retry_at=retry_at,
    )


def test_delivery_survives_reopen_with_binding_and_markup(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = TelegramState(path, "123")
    delivery_id = _create(first, retry_at=100)
    first.close()

    reopened = TelegramState(path, "123")
    try:
        delivery = reopened.get_delivery(delivery_id)
        assert delivery["bot_id"] == "123"
        assert delivery["update_id"] == 17
        assert delivery["chat_id"] == 42
        assert delivery["alias"] == "dev"
        assert (delivery["conversation_id"], delivery["turn_id"], delivery["assistant_message_id"]) == (
            "conversation-1", "turn-1", "assistant-1",
        )
        assert delivery["parts"] == ["first", "second", "third"]
        assert delivery["reply_markup"]["inline_keyboard"][0][0]["text"] == "继续聊"
        assert [part["text"] for part in reopened.get_delivery_parts(delivery_id)] == delivery["parts"]
        assert [item["delivery_id"] for item in reopened.list_pending_deliveries(now=100)] == [delivery_id]
    finally:
        reopened.close()


def test_delivery_parts_are_read_in_order_and_track_partial_success(tmp_path):
    state = TelegramState(tmp_path / "state.sqlite3", "123")
    try:
        delivery_id = _create(state)
        state.mark_delivery_part_sent(delivery_id, 0, 501)
        state.mark_delivery_part_failed(delivery_id, 1, "temporary", retry_at=200)

        delivery = state.get_delivery(delivery_id)
        parts = state.get_delivery_parts(delivery_id)
        assert delivery["status"] == "partial"
        assert [(part["part_index"], part["status"], part["message_id"]) for part in parts] == [
            (0, "sent", 501), (1, "failed", None), (2, "pending", None),
        ]
        assert delivery["retry_at"] == 200
        assert state.list_pending_deliveries(now=199) == []
        assert [item["delivery_id"] for item in state.list_pending_deliveries(now=200)] == [delivery_id]
    finally:
        state.close()


def test_repeated_part_completion_keeps_original_message_id_and_sent_state(tmp_path):
    state = TelegramState(tmp_path / "state.sqlite3", "123")
    try:
        delivery_id = _create(state)
        state.mark_delivery_part_sent(delivery_id, 0, 501)
        state.mark_delivery_part_sent(delivery_id, 0, 999)
        part = state.get_delivery_parts(delivery_id)[0]
        assert (part["status"], part["message_id"], part["attempts"]) == ("sent", 501, 1)

        same_id = _create(state)
        assert same_id == delivery_id
        assert state.get_delivery_parts(delivery_id)[0]["message_id"] == 501
    finally:
        state.close()


class _Response:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def json(self, *, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_429_preserves_retry_after_without_token_in_error():
    client = TelegramClient("123:secret-for-test")
    client._session = Mock()
    client._session.post.return_value = _Response(
        429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 7}},
    )

    with pytest.raises(TelegramError) as raised:
        await client.send_message(42, "hello")

    error = raised.value
    assert (error.code, error.retry_after, error.retryable) == (429, 7, True)
    assert "secret-for-test" not in str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,attribute",
    [(aiohttp.ClientConnectionError("https://api.example/bot123:secret"), "is_network_error"),
     (asyncio.TimeoutError(), "is_timeout")],
)
async def test_transport_failures_are_classifiable_without_token(failure, attribute):
    client = TelegramClient("123:secret-for-test")
    client._session = Mock()
    client._session.post.side_effect = failure

    with pytest.raises(TelegramTransportError) as raised:
        await client.get_updates(9)

    error = raised.value
    assert getattr(error, attribute) is True
    assert error.retryable is True
    assert "secret-for-test" not in str(error)
