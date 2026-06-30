from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.runtime_paths import get_chat_favorites_path
from bot.chat_identity import chat_session_user_id
from bot.web.api_common import WebApiError, resolve_session_bot_id
from bot.web.api_service import (
    delete_all_conversations,
    delete_conversation,
    delete_favorite_answer,
    list_favorite_answers,
    upsert_favorite_answer,
)
from bot.web.chat_favorite_store import ChatFavoriteStore, FavoriteScope, build_favorite_item
from bot.web.chat_store import ChatStore


def _manager(tmp_path: Path) -> MultiBotManager:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(
            alias="main",
            working_dir=str(tmp_path),
            supported_execution_modes=["cli", "native_agent"],
        ),
        str(storage),
    )


def _completed_turn(
    manager: MultiBotManager,
    tmp_path: Path,
    *,
    user_id: int = 123,
    agent_id: str = "main",
    native_provider: str = "codex",
    assistant_text: str = "完整回答文本",
):
    store = ChatStore(tmp_path)
    bot_id = resolve_session_bot_id(manager, "main")
    shared_user_id = chat_session_user_id(user_id)
    handle = store.begin_turn(
        bot_id=bot_id,
        bot_alias="main",
        user_id=shared_user_id,
        agent_id=agent_id,
        bot_mode="cli",
        cli_type="codex",
        working_dir=str(tmp_path),
        session_epoch=0,
        user_text="问题",
        native_provider=native_provider,
    )
    message = store.complete_turn(handle, content=assistant_text, completion_state="completed")
    return store, handle, message


def test_favorite_store_persists_and_upserts(tmp_path: Path):
    scope = FavoriteScope(bot_id=1, user_id=2, agent_id="main", execution_mode="cli")
    item = build_favorite_item(
        scope=scope,
        bot_alias="main",
        conversation_id="conv_1",
        message_id="msg_1",
        message_key="assistant|msg_1",
        answer_text="回答",
    )

    store = ChatFavoriteStore(tmp_path)
    first = store.upsert_favorite(item)
    second = ChatFavoriteStore(tmp_path).upsert_favorite({**item, "answer_text": "更新后的回答"})

    assert first["id"] == second["id"]
    assert get_chat_favorites_path(tmp_path).is_file()
    listed = ChatFavoriteStore(tmp_path).list_favorites(scope)
    assert len(listed) == 1
    assert listed[0]["answer_text"] == "更新后的回答"
    assert ChatFavoriteStore(tmp_path).list_favorites(scope, query="更新后")[0]["id"] == first["id"]
    assert ChatFavoriteStore(tmp_path).delete_favorite("missing", scope) is False
    assert ChatFavoriteStore(tmp_path).list_favorites(scope)[0]["id"] == first["id"]


def test_favorite_store_isolates_scope_and_recovers_corrupt_json(tmp_path: Path):
    path = get_chat_favorites_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{bad json", encoding="utf-8")

    store = ChatFavoriteStore(tmp_path)

    assert store.list_favorites(FavoriteScope(bot_id=1, user_id=1)) == []
    assert list(path.parent.glob("favorites.json.corrupt-*"))

    store.upsert_favorite(build_favorite_item(
        scope=FavoriteScope(bot_id=1, user_id=1, agent_id="main", execution_mode="cli"),
        bot_alias="main",
        conversation_id="conv_1",
        message_id="msg_1",
        message_key="assistant|msg_1",
        answer_text="用户 1",
    ))
    store.upsert_favorite(build_favorite_item(
        scope=FavoriteScope(bot_id=1, user_id=2, agent_id="main", execution_mode="cli"),
        bot_alias="main",
        conversation_id="conv_2",
        message_id="msg_2",
        message_key="assistant|msg_2",
        answer_text="用户 2",
    ))

    assert [item["answer_text"] for item in store.list_favorites(FavoriteScope(bot_id=1, user_id=1))] == ["用户 1"]


def test_favorite_answer_service_validates_and_deletes(tmp_path: Path):
    manager = _manager(tmp_path)
    _store, handle, message = _completed_turn(manager, tmp_path)

    created = upsert_favorite_answer(
        manager,
        "main",
        123,
        {
            "conversation_id": handle.conversation_id,
            "message_id": message["id"],
            "message_key": f"assistant|{message['id']}",
            "answer_text": "前端回退内容不会覆盖后端内容",
        },
        execution_mode="cli",
    )["item"]

    assert created["answer_text"] == "完整回答文本"
    listed = list_favorite_answers(manager, "main", 123, execution_mode="cli")["items"]
    assert [item["id"] for item in listed] == [created["id"]]

    deleted = delete_favorite_answer(manager, "main", 123, created["id"], execution_mode="cli")

    assert deleted["deleted"] is True
    assert list_favorite_answers(manager, "main", 123, execution_mode="cli")["items"] == []


def test_deleting_conversation_removes_its_favorites(tmp_path: Path):
    manager = _manager(tmp_path)
    _store, handle, message = _completed_turn(manager, tmp_path)
    created = upsert_favorite_answer(
        manager,
        "main",
        123,
        {
            "conversation_id": handle.conversation_id,
            "message_id": message["id"],
            "message_key": f"assistant|{message['id']}",
        },
        execution_mode="cli",
    )["item"]

    deleted = delete_conversation(manager, "main", 123, handle.conversation_id, execution_mode="cli")

    assert deleted["deleted_conversation_id"] == handle.conversation_id
    assert deleted["deleted_favorite_count"] == 1
    assert list_favorite_answers(manager, "main", 123, execution_mode="cli")["items"] == []
    scope = FavoriteScope(
        bot_id=resolve_session_bot_id(manager, "main"),
        user_id=chat_session_user_id(123),
        agent_id="main",
        execution_mode="cli",
    )
    assert created["id"] not in [item["id"] for item in ChatFavoriteStore(tmp_path).list_favorites(scope)]


def test_deleting_all_conversations_removes_scoped_favorites(tmp_path: Path):
    manager = _manager(tmp_path)
    _store, handle, message = _completed_turn(manager, tmp_path)
    upsert_favorite_answer(
        manager,
        "main",
        123,
        {
            "conversation_id": handle.conversation_id,
            "message_id": message["id"],
            "message_key": f"assistant|{message['id']}",
        },
        execution_mode="cli",
    )

    deleted = delete_all_conversations(manager, "main", 123, execution_mode="cli")

    assert deleted["deleted_count"] == 1
    assert deleted["deleted_favorite_count"] == 1
    assert list_favorite_answers(manager, "main", 123, execution_mode="cli")["items"] == []


def test_favorite_answer_rejects_invalid_message_and_execution_mode(tmp_path: Path):
    manager = _manager(tmp_path)
    _store, handle, message = _completed_turn(manager, tmp_path, native_provider="native_agent")

    with pytest.raises(WebApiError) as mode_error:
        upsert_favorite_answer(
            manager,
            "main",
            123,
            {
                "conversation_id": handle.conversation_id,
                "message_id": message["id"],
                "message_key": f"assistant|{message['id']}",
            },
            execution_mode="cli",
        )
    assert mode_error.value.status == 409
    assert mode_error.value.code == "conversation_execution_mode_mismatch"

    with pytest.raises(WebApiError) as role_error:
        upsert_favorite_answer(
            manager,
            "main",
            123,
            {
                "conversation_id": handle.conversation_id,
                "message_id": handle.user_message_id,
                "message_key": f"user|{handle.user_message_id}",
            },
            execution_mode="native_agent",
        )
    assert role_error.value.status == 409
    assert role_error.value.code == "favorite_message_not_assistant"
