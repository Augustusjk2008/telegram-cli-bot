from __future__ import annotations

import json
import asyncio
import ctypes
from pathlib import Path

import pytest

from bot.manager import MultiBotManager
from bot.models import AgentProfile, BotProfile
from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key
from bot.session_store import load_session, save_session
from bot.runtime_paths import get_chat_favorites_path
from bot.chat_identity import chat_session_user_id
from bot.web.api_common import AuthContext, WebApiError, resolve_session_bot_id
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_CHAT_SEND
from bot.web.api_service import (
    delete_all_conversations,
    delete_conversation,
    delete_favorite_answer,
    list_favorite_answers,
    remove_managed_bot_with_history,
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


def _add_managed_profile(manager: MultiBotManager, alias: str, working_dir: Path, *, agents: list[AgentProfile] | None = None) -> None:
    manager.managed_profiles[alias] = BotProfile(
        alias=alias,
        working_dir=str(working_dir),
        supported_execution_modes=["cli", "native_agent"],
        agents=agents or [],
    )


def _remove_bot_with_history(manager: MultiBotManager, alias: str, **options):
    return asyncio.run(remove_managed_bot_with_history(manager, alias, **options))


def _completed_turn(
    manager: MultiBotManager,
    tmp_path: Path,
    *,
    alias: str = "main",
    user_id: int = 123,
    agent_id: str = "main",
    native_provider: str = "codex",
    assistant_text: str = "完整回答文本",
    working_dir: str | None = None,
):
    store = ChatStore(tmp_path)
    bot_id = resolve_session_bot_id(manager, alias)
    shared_user_id = chat_session_user_id(user_id)
    handle = store.begin_turn(
        bot_id=bot_id,
        bot_alias=alias,
        user_id=shared_user_id,
        agent_id=agent_id,
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


def test_delete_all_conversations_ignores_legacy_permanent_query(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = _manager(workspace)
    _completed_turn(manager, workspace)
    (workspace / "artifact.txt").write_text("keep", encoding="utf-8")

    deleted = delete_all_conversations(manager, "main", 123, execution_mode="cli")

    assert deleted["deleted_count"] == 1
    assert "workspace_deleted" not in deleted
    assert workspace.exists()
    assert (workspace / "artifact.txt").is_file()


def test_remove_bot_with_workspace_deletes_workspace_history_favorites_and_sessions(tmp_path: Path):
    main_workspace = tmp_path / "main"
    bot_workspace = tmp_path / "bot"
    main_workspace.mkdir()
    bot_workspace.mkdir()
    (bot_workspace / "artifact.txt").write_text("leftover", encoding="utf-8")
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", bot_workspace, agents=[AgentProfile(id="reviewer", name="Reviewer")])
    _main_store, main_handle, main_message = _completed_turn(manager, bot_workspace, alias="team", agent_id="main")
    _reviewer_store, reviewer_handle, reviewer_message = _completed_turn(
        manager,
        bot_workspace,
        alias="team",
        agent_id="reviewer",
        native_provider="native_agent",
    )
    from bot.web.api_common import get_chat_session_for_alias

    bot_id = resolve_session_bot_id(manager, "team")
    shared_user_id = chat_session_user_id(123)
    upsert_favorite_answer(
        manager,
        "team",
        123,
        {"conversation_id": main_handle.conversation_id, "message_id": main_message["id"]},
        execution_mode="cli",
    )
    upsert_favorite_answer(
        manager,
        "team",
        123,
        {"conversation_id": reviewer_handle.conversation_id, "message_id": reviewer_message["id"]},
        agent_id="reviewer",
        execution_mode="native_agent",
    )
    _profile, _agent, main_session = get_chat_session_for_alias(manager, "team", 123, "main")
    _profile, _agent, reviewer_session = get_chat_session_for_alias(manager, "team", 123, "reviewer")
    with main_session._lock:
        main_session.codex_session_id = "codex-main"
    with reviewer_session._lock:
        reviewer_session.codex_session_id = "codex-reviewer"
    main_session.persist()
    reviewer_session.persist()
    save_session(
        bot_id,
        shared_user_id,
        codex_session_id="old-agent-session",
        working_dir=str(bot_workspace) + "/",
        agent_id="old-agent",
    )
    pi_key = pi_session_key(
        cwd=str(bot_workspace),
        bot_id=bot_id,
        user_id=shared_user_id,
        conversation_id=reviewer_handle.conversation_id,
    )
    PiSessionStore().upsert(PiSessionRecord(
        key=pi_key,
        cwd=str(bot_workspace),
        conversation_id=reviewer_handle.conversation_id,
        pi_session_id="pi-reviewer",
    ))

    deleted = _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert deleted["removed"] is True
    assert deleted["history_deleted"] is True
    assert deleted["history_deleted_count"] == 2
    assert deleted["favorite_deleted_count"] == 2
    assert deleted["workspace_deleted"] is True
    assert deleted["workspace_path"] == str(bot_workspace)
    assert deleted["errors"] == []
    assert "team" not in manager.managed_profiles
    assert not bot_workspace.exists()
    assert load_session(bot_id, shared_user_id, agent_id="main") is None
    assert load_session(bot_id, shared_user_id, agent_id="reviewer") is None
    assert load_session(bot_id, shared_user_id, agent_id="old-agent") is None
    assert PiSessionStore().get(pi_key) is None
    assert ChatStore(bot_workspace).list_conversation_records(
        bot_id=bot_id,
        user_id=shared_user_id,
        working_dir=None,
        agent_id=None,
        include_archived=True,
    ) == []
    assert ChatFavoriteStore(bot_workspace).list_favorites(FavoriteScope(bot_id=bot_id, user_id=shared_user_id)) == []


def test_remove_bot_with_history_only_keeps_workspace(tmp_path: Path):
    main_workspace = tmp_path / "main"
    bot_workspace = tmp_path / "bot"
    main_workspace.mkdir()
    bot_workspace.mkdir()
    (bot_workspace / "artifact.txt").write_text("keep", encoding="utf-8")
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", bot_workspace)
    _completed_turn(manager, bot_workspace, alias="team")
    bot_id = resolve_session_bot_id(manager, "team")

    deleted = _remove_bot_with_history(manager, "team", delete_history=True)

    assert deleted["removed"] is True
    assert deleted["history_deleted"] is True
    assert deleted["history_deleted_count"] == 1
    assert deleted["workspace_deleted"] is False
    assert bot_workspace.exists()
    assert (bot_workspace / "artifact.txt").is_file()
    assert ChatStore(bot_workspace).list_conversation_records(
        bot_id=bot_id,
        user_id=chat_session_user_id(123),
        working_dir=None,
        agent_id=None,
        include_archived=True,
    ) == []


def test_remove_bot_with_workspace_rejects_overlapping_managed_bot_workspace(tmp_path: Path):
    main_workspace = tmp_path / "main"
    workspace = tmp_path / "workspace"
    child_workspace = workspace / "child"
    main_workspace.mkdir()
    child_workspace.mkdir(parents=True)
    (child_workspace / "keep.txt").write_text("keep", encoding="utf-8")
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", workspace)
    _add_managed_profile(manager, "child", child_workspace)

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert "team" in manager.managed_profiles
    assert (child_workspace / "keep.txt").is_file()
    assert workspace.exists()


def test_remove_bot_with_workspace_rejects_same_managed_bot_workspace(tmp_path: Path):
    main_workspace = tmp_path / "main"
    workspace = tmp_path / "workspace"
    main_workspace.mkdir()
    workspace.mkdir()
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", workspace)
    _add_managed_profile(manager, "same", workspace)

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert "team" in manager.managed_profiles
    assert workspace.exists()


def test_remove_bot_with_workspace_rejects_parent_managed_bot_workspace(tmp_path: Path):
    main_workspace = tmp_path / "main"
    parent_workspace = tmp_path / "workspace"
    child_workspace = parent_workspace / "child"
    main_workspace.mkdir()
    child_workspace.mkdir(parents=True)
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", child_workspace)
    _add_managed_profile(manager, "parent", parent_workspace)

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert "team" in manager.managed_profiles
    assert child_workspace.exists()


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


def test_remove_bot_with_workspace_rejects_symlink_workspace(tmp_path: Path):
    target_workspace = tmp_path / "target"
    target_workspace.mkdir()
    (target_workspace / "keep.txt").write_text("keep", encoding="utf-8")
    link_workspace = tmp_path / "workspace-link"
    try:
        link_workspace.symlink_to(target_workspace, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    main_workspace = tmp_path / "main"
    main_workspace.mkdir()
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", link_workspace)

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"
    assert "team" in manager.managed_profiles
    assert (target_workspace / "keep.txt").is_file()
    assert link_workspace.exists()


def test_remove_bot_with_workspace_rejects_processing_session(tmp_path: Path):
    main_workspace = tmp_path / "main"
    bot_workspace = tmp_path / "bot"
    main_workspace.mkdir()
    bot_workspace.mkdir()
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", bot_workspace)
    _completed_turn(manager, bot_workspace, alias="team")
    from bot.web.api_common import get_chat_session_for_alias

    _profile, _agent, session = get_chat_session_for_alias(manager, "team", 123)
    with session._lock:
        session.is_processing = True

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 409
    assert exc.value.code == "conversation_switch_blocked"
    assert "team" in manager.managed_profiles
    assert bot_workspace.exists()


def test_remove_bot_with_workspace_rejects_processing_sibling_agent(tmp_path: Path):
    main_workspace = tmp_path / "main"
    workspace = tmp_path / "workspace"
    main_workspace.mkdir()
    workspace.mkdir()
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", workspace, agents=[AgentProfile(id="reviewer", name="Reviewer")])
    _completed_turn(manager, workspace, alias="team")
    _completed_turn(manager, workspace, alias="team", agent_id="reviewer")
    from bot.web.api_common import get_chat_session_for_alias

    _profile, _agent, reviewer_session = get_chat_session_for_alias(manager, "team", 123, "reviewer")
    with reviewer_session._lock:
        reviewer_session.is_processing = True

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 409
    assert exc.value.code == "conversation_switch_blocked"
    assert "team" in manager.managed_profiles
    assert workspace.exists()
    assert len(ChatStore(workspace).list_conversation_records(
        bot_id=resolve_session_bot_id(manager, "team"),
        user_id=chat_session_user_id(123),
        working_dir=str(workspace),
        agent_id=None,
        include_archived=True,
    )) == 2


def test_remove_bot_with_workspace_keeps_records_when_workspace_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    main_workspace = tmp_path / "main"
    workspace = tmp_path / "workspace"
    main_workspace.mkdir()
    workspace.mkdir()
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", workspace)
    _completed_turn(manager, workspace, alias="team")
    import bot.web.api_service as api_service

    def fail_delete(_path: Path) -> None:
        raise OSError("locked")

    monkeypatch.setattr(api_service.shutil, "rmtree", fail_delete)

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 500
    assert exc.value.code == "workspace_delete_failed"
    assert "team" in manager.managed_profiles
    assert workspace.exists()
    assert len(ChatStore(workspace).list_conversation_records(
        bot_id=resolve_session_bot_id(manager, "team"),
        user_id=chat_session_user_id(123),
        working_dir=str(workspace),
        agent_id=None,
        include_archived=True,
    )) == 1


@pytest.mark.asyncio
async def test_delete_conversations_view_ignores_legacy_permanent_without_write_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    response = await server.delete_conversations_view(Request())

    assert response.status == 200


@pytest.mark.asyncio
async def test_remove_bot_with_workspace_view_requires_write_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    main_workspace = tmp_path / "main"
    workspace = tmp_path / "workspace"
    main_workspace.mkdir()
    workspace.mkdir()
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", workspace)
    server = WebApiServer(manager)

    class Request(dict):
        match_info = {"alias": "team"}
        query = {"delete_workspace": "true"}

    async def admin_only(_request, capability: str) -> AuthContext:
        assert capability == CAP_ADMIN_OPS
        return AuthContext(user_id=123, token_used=True, capabilities={CAP_ADMIN_OPS})

    monkeypatch.setattr(server, "_with_capability", admin_only)

    with pytest.raises(WebApiError) as exc:
        await server.admin_remove_bot(Request())

    assert exc.value.status == 403
    assert exc.value.code == "forbidden"
    assert "team" in manager.managed_profiles
    assert workspace.exists()


def test_remove_bot_with_workspace_treats_missing_workspace_as_success(tmp_path: Path):
    main_workspace = tmp_path / "main"
    workspace = tmp_path / "workspace"
    main_workspace.mkdir()
    workspace.mkdir()
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", workspace)
    _completed_turn(manager, workspace, alias="team")
    (workspace / "marker.txt").write_text("gone", encoding="utf-8")
    for path in workspace.iterdir():
        path.unlink()
    workspace.rmdir()

    deleted = _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert deleted["history_deleted_count"] == 1
    assert deleted["workspace_deleted"] is False
    assert deleted["workspace_missing"] is True
    assert deleted["errors"] == []
    assert "team" not in manager.managed_profiles


def test_remove_bot_with_workspace_rejects_main_bot_before_deleting_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("keep", encoding="utf-8")
    manager = _manager(workspace)

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "main", delete_workspace=True)

    assert exc.value.status == 400
    assert exc.value.code == "invalid_bot_config"
    assert workspace.exists()
    assert (workspace / "keep.txt").is_file()


def test_remove_bot_with_workspace_rejects_root_directory(tmp_path: Path):
    main_workspace = tmp_path / "main"
    main_workspace.mkdir()
    root = tmp_path.anchor or str(tmp_path.resolve().anchor)
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", Path(root))

    with pytest.raises(WebApiError) as exc:
        _remove_bot_with_history(manager, "team", delete_workspace=True)

    assert exc.value.status == 409
    assert exc.value.code == "workspace_delete_scope_mismatch"


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
