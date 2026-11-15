from __future__ import annotations

import sqlite3

from bot.weixin.state import WeixinState


def test_cursor_dedup_context_binding_and_delivery_recovery(tmp_path):
    path = tmp_path / "weixin" / "state.sqlite3"
    state = WeixinState(path, "account")
    state.set_updates_buf("cursor-1")
    assert state.get_updates_buf() == "cursor-1"
    assert state.claim_message("message-1", peer_id="peer-1")
    assert not state.claim_message("message-1", peer_id="peer-1")
    state.set_context_token("peer-1", "context-1")
    state.bind_conversation(
        peer_id="peer-1",
        alias="dev",
        conversation_id="conversation-1",
        shared_user_id=1,
        actor_id="peer-1",
    )
    assert state.get_context_token("peer-1") == "context-1"
    assert state.get_binding("peer-1")["conversation_id"] == "conversation-1"
    state.create_delivery("delivery-1", "peer-1", ["one", "two"], alias="dev", turn_id="turn-1")
    state.mark_delivery_part_sent("delivery-1", 0)
    recovered = state.list_incomplete_deliveries()
    assert recovered[0]["delivery_id"] == "delivery-1"
    assert recovered[0]["part_records"][0]["status"] == "sent"
    state.close()

    reopened = WeixinState(path, "account")
    assert reopened.get_updates_buf() == "cursor-1"
    assert reopened.get_context_token("peer-1") == "context-1"
    assert reopened.get_binding("peer-1")["conversation_id"] == "conversation-1"
    reopened.close()

    with sqlite3.connect(path) as database:
        contents = " ".join(str(row[0]) for row in database.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
    assert "WEIXIN_TOKEN" not in contents
