from __future__ import annotations

import json
import ctypes
from pathlib import Path

import pytest

from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile
from bot.session_store import load_session, save_session
from bot.runtime_paths import get_chat_favorites_path
from bot.chat_identity import chat_session_user_id
from bot.web.api_common import AuthContext, WebApiError, resolve_session_bot_id
from bot.web.auth_store import CAP_CHAT_SEND
from bot.web.api_service import (
    delete_all_conversations,
    delete_conversation,
    delete_favorite_answer,
    list_favorite_answers,
    upsert_favorite_answer,
)
from bot.web.chat_favorite_store import ChatFavoriteStore, FavoriteScope, build_favorite_item
from bot.web.chat_store import ChatStore
from bot.web.server import WebApiServer


def _manager(tmp_path: Path, *, agents: list[AgentProfile] | None = None) -> MultiBotManager:
    storage = tmp_path / "managed_bots.json"
    storage.write_text(json.dumps({"bots": []}), encoding="utf-8")
    return MultiBotManager(
        BotProfile(
            alias="main",
            working_dir=str(tmp_path),
            supported_execution_modes=["cli", "native_agent"],
            agents=agents or [],
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
    working_dir: str | None = None,
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
        working_dir=working_dir or str(tmp_path),
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


def test_permanent_delete_all_conversations_removes_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "artifact.txt").write_text("leftover", encoding="utf-8")
    manager = _manager(workspace)
    _store, _handle, _message = _completed_turn(manager, workspace)

    deleted = delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert deleted["deleted_count"] == 1
    assert deleted["workspace_deleted"] is True
    assert deleted["workspace_path"] == str(workspace)
    assert deleted["errors"] == []
    assert not workspace.exists()
    assert ChatStore(workspace).list_conversations(
        bot_id=resolve_session_bot_id(manager, "main"),
        user_id=chat_session_user_id(123),
        working_dir=str(workspace),
    ) == []


def test_permanent_delete_all_conversations_removes_agent_records_and_sessions(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace, agents=[AgentProfile(id="reviewer", name="Reviewer")])
    _main_store, main_handle, main_message = _completed_turn(manager, workspace)
    _reviewer_store, reviewer_handle, reviewer_message = _completed_turn(manager, workspace, agent_id="reviewer")
    from bot.web.api_common import get_chat_session_for_alias

    bot_id = resolve_session_bot_id(manager, "main")
    shared_user_id = chat_session_user_id(123)
    upsert_favorite_answer(
        manager,
        "main",
        123,
        {"conversation_id": main_handle.conversation_id, "message_id": main_message["id"]},
        execution_mode="cli",
    )
    upsert_favorite_answer(
        manager,
        "main",
        123,
        {"conversation_id": reviewer_handle.conversation_id, "message_id": reviewer_message["id"]},
        agent_id="reviewer",
        execution_mode="cli",
    )
    _profile, _agent, main_session = get_chat_session_for_alias(manager, "main", 123, "main")
    _profile, _agent, reviewer_session = get_chat_session_for_alias(manager, "main", 123, "reviewer")
    with main_session._lock:
        main_session.codex_session_id = "codex-main"
    with reviewer_session._lock:
        reviewer_session.codex_session_id = "codex-reviewer"
    main_session.persist()
    reviewer_session.persist()

    deleted = delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert deleted["deleted_count"] == 2
    assert deleted["deleted_favorite_count"] == 2
    assert load_session(bot_id, shared_user_id, agent_id="main") is None
    assert load_session(bot_id, shared_user_id, agent_id="reviewer") is None
    assert ChatStore(workspace).list_conversation_records(
        bot_id=bot_id,
        user_id=shared_user_id,
        working_dir=str(workspace),
        agent_id=None,
        include_archived=True,
    ) == []
    assert list_favorite_answers(manager, "main", 123, execution_mode="cli")["items"] == []
    assert list_favorite_answers(manager, "main", 123, agent_id="reviewer", execution_mode="cli")["items"] == []


def test_permanent_delete_all_conversations_matches_resolved_workspace_paths(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace)
    variant_working_dir = str(workspace) + "/"
    _store, handle, message = _completed_turn(manager, workspace, working_dir=variant_working_dir)
    bot_id = resolve_session_bot_id(manager, "main")
    shared_user_id = chat_session_user_id(123)
    ChatFavoriteStore(workspace).upsert_favorite(
        build_favorite_item(
            scope=FavoriteScope(bot_id=bot_id, user_id=shared_user_id, agent_id="main", execution_mode="cli"),
            bot_alias="main",
            conversation_id=handle.conversation_id,
            message_id=message["id"],
            message_key=f"assistant|{message['id']}",
            answer_text=str(message["content"]),
        )
    )

    deleted = delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert deleted["deleted_count"] == 1
    assert deleted["deleted_favorite_count"] == 1
    assert ChatStore(workspace).list_conversation_records(
        bot_id=bot_id,
        user_id=shared_user_id,
        working_dir=None,
        agent_id=None,
        include_archived=True,
    ) == []
    assert list_favorite_answers(manager, "main", 123, execution_mode="cli")["items"] == []


def test_permanent_delete_all_conversations_rejects_overlapping_managed_bot_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    child_workspace = workspace / "child"
    child_workspace.mkdir(parents=True)
    (child_workspace / "keep.txt").write_text("keep", encoding="utf-8")
    manager = _manager(workspace)
    manager.managed_profiles["child"] = BotProfile(alias="child", working_dir=str(child_workspace))
    _completed_turn(manager, workspace)

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert (child_workspace / "keep.txt").is_file()
    assert workspace.exists()


def test_permanent_delete_all_conversations_rejects_same_managed_bot_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace)
    manager.managed_profiles["same"] = BotProfile(alias="same", working_dir=str(workspace))
    _completed_turn(manager, workspace)

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert workspace.exists()


def test_permanent_delete_all_conversations_rejects_parent_managed_bot_workspace(tmp_path: Path):
    parent_workspace = tmp_path / "workspace"
    child_workspace = parent_workspace / "child"
    child_workspace.mkdir(parents=True)
    manager = _manager(child_workspace)
    manager.managed_profiles["parent"] = BotProfile(alias="parent", working_dir=str(parent_workspace))
    _completed_turn(manager, child_workspace)

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert child_workspace.exists()


def test_permanent_delete_all_conversations_removes_legacy_agent_session_without_history(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace)
    _completed_turn(manager, workspace)
    bot_id = resolve_session_bot_id(manager, "main")
    shared_user_id = chat_session_user_id(123)
    save_session(
        bot_id,
        shared_user_id,
        codex_session_id="old-agent-session",
        working_dir=str(workspace) + "/",
        agent_id="old-agent",
    )

    deleted = delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert deleted["deleted_count"] == 1
    assert load_session(bot_id, shared_user_id, agent_id="old-agent") is None


def test_permanent_delete_workspace_reparse_fallback_detects_windows_junction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import bot.web.api_service as api_service

    class Kernel32:
        @staticmethod
        def GetFileAttributesW(_path: str) -> int:
            return 0x400

    class Windll:
        kernel32 = Kernel32()

    monkeypatch.setattr(api_service.os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", Windll(), raising=False)

    assert api_service._is_symlink_or_junction(tmp_path) is True


def test_permanent_delete_all_conversations_rejects_symlink_workspace(tmp_path: Path):
    target_workspace = tmp_path / "target"
    target_workspace.mkdir()
    (target_workspace / "keep.txt").write_text("keep", encoding="utf-8")
    link_workspace = tmp_path / "workspace-link"
    try:
        link_workspace.symlink_to(target_workspace, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    manager = _manager(link_workspace)
    _completed_turn(manager, link_workspace)

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert (target_workspace / "keep.txt").is_file()
    assert link_workspace.exists()


def test_permanent_delete_all_conversations_rejects_processing_session(tmp_path: Path):
    manager = _manager(tmp_path)
    _completed_turn(manager, tmp_path)
    from bot.web.api_common import get_chat_session_for_alias

    _profile, _agent, session = get_chat_session_for_alias(manager, "main", 123)
    with session._lock:
        session.is_processing = True

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 409
    assert exc.value.code == "conversation_switch_blocked"
    assert tmp_path.exists()


def test_permanent_delete_all_conversations_rejects_processing_sibling_agent(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace, agents=[AgentProfile(id="reviewer", name="Reviewer")])
    _completed_turn(manager, workspace)
    _completed_turn(manager, workspace, agent_id="reviewer")
    from bot.web.api_common import get_chat_session_for_alias

    _profile, _agent, reviewer_session = get_chat_session_for_alias(manager, "main", 123, "reviewer")
    with reviewer_session._lock:
        reviewer_session.is_processing = True

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 409
    assert exc.value.code == "conversation_switch_blocked"
    assert workspace.exists()
    assert len(ChatStore(workspace).list_conversation_records(
        bot_id=resolve_session_bot_id(manager, "main"),
        user_id=chat_session_user_id(123),
        working_dir=str(workspace),
        agent_id=None,
        include_archived=True,
    )) == 2


def test_permanent_delete_all_conversations_keeps_records_when_workspace_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace)
    _completed_turn(manager, workspace)
    import bot.web.api_service as api_service

    def fail_delete(_path: Path) -> None:
        raise OSError("locked")

    monkeypatch.setattr(api_service.shutil, "rmtree", fail_delete)

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 500
    assert exc.value.code == "workspace_delete_failed"
    assert workspace.exists()
    assert len(ChatStore(workspace).list_conversation_records(
        bot_id=resolve_session_bot_id(manager, "main"),
        user_id=chat_session_user_id(123),
        working_dir=str(workspace),
        agent_id=None,
        include_archived=True,
    )) == 1


@pytest.mark.asyncio
async def test_permanent_delete_conversations_view_requires_write_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = _manager(tmp_path)
    server = WebApiServer(manager)

    class Request(dict):
        match_info = {"alias": "main"}
        query = {"permanent": "true"}
        content_length = 0

    async def chat_send_only(_request, capability: str) -> AuthContext:
        assert capability == CAP_CHAT_SEND
        return AuthContext(user_id=123, token_used=True, capabilities={CAP_CHAT_SEND})

    monkeypatch.setattr(server, "_with_capability", chat_send_only)

    with pytest.raises(WebApiError) as exc:
        await server.delete_conversations_view(Request())

    assert exc.value.status == 403
    assert exc.value.code == "forbidden"


def test_permanent_delete_all_conversations_treats_missing_workspace_as_success(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace)
    _completed_turn(manager, workspace)
    (workspace / "marker.txt").write_text("gone", encoding="utf-8")
    for path in workspace.iterdir():
        path.unlink()
    workspace.rmdir()

    deleted = delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert deleted["deleted_count"] == 1
    assert deleted["workspace_deleted"] is False
    assert deleted["workspace_missing"] is True
    assert deleted["errors"] == []


def test_permanent_delete_all_conversations_rejects_workspace_mismatch(tmp_path: Path):
    profile_workspace = tmp_path / "profile"
    conversation_workspace = tmp_path / "conversation"
    profile_workspace.mkdir()
    conversation_workspace.mkdir()
    manager = _manager(profile_workspace)
    _completed_turn(manager, conversation_workspace)
    from bot.web.api_common import get_chat_session_for_alias

    _profile, _agent, session = get_chat_session_for_alias(manager, "main", 123)
    with session._lock:
        session.working_dir = str(conversation_workspace)
        session.browse_dir = str(conversation_workspace)

    with pytest.raises(WebApiError) as exc:
        delete_all_conversations(manager, "main", 123, execution_mode="cli", permanent=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert conversation_workspace.exists()


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
