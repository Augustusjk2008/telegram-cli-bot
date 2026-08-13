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
from bot.chat_identity import chat_session_user_id
from bot.web.api_common import AuthContext, WebApiError, resolve_session_bot_id
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_CHAT_SEND
from bot.web.api_service import (
    delete_all_conversations,
    remove_managed_bot_with_history,
    upsert_favorite_answer,
)
from bot.web.chat_favorite_store import ChatFavoriteStore, FavoriteScope
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


def _assert_workspace_removal_error(manager: MultiBotManager, alias: str, status: int, code: str) -> None:
    with pytest.raises(WebApiError) as error:
        _remove_bot_with_history(manager, alias, delete_workspace=True)
    assert (error.value.status, error.value.code) == (status, code)


def _conversation_records(manager: MultiBotManager, workspace: Path, alias: str, working_dir: str | None):
    return ChatStore(workspace).list_conversation_records(
        bot_id=resolve_session_bot_id(manager, alias), user_id=chat_session_user_id(123),
        working_dir=working_dir, agent_id=None, include_archived=True,
    )


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
    assert all(load_session(bot_id, shared_user_id, agent_id=item) is None for item in ("main", "reviewer", "old-agent"))
    assert PiSessionStore().get(pi_key) is None
    assert _conversation_records(manager, bot_workspace, "team", None) == []
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
    assert _conversation_records(manager, bot_workspace, "team", None) == []


@pytest.mark.parametrize("nested", [False, True], ids=["same", "nested"])
def test_remove_bot_with_workspace_rejects_overlapping_managed_bot_workspace(tmp_path: Path, nested: bool):
    main_workspace = tmp_path / "main"
    workspace = tmp_path / "workspace"
    main_workspace.mkdir()
    other_workspace = workspace / "child" if nested else workspace
    other_workspace.mkdir(parents=True)
    (other_workspace / "keep.txt").write_text("keep", encoding="utf-8")
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", workspace)
    _add_managed_profile(manager, "other", other_workspace)
    _assert_workspace_removal_error(manager, "team", 409, "workspace_delete_scope_mismatch")
    assert "team" in manager.managed_profiles
    assert (other_workspace / "keep.txt").is_file()
    assert workspace.exists()


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

    _assert_workspace_removal_error(manager, "team", 409, "workspace_delete_scope_mismatch")
    assert "team" in manager.managed_profiles
    assert (target_workspace / "keep.txt").is_file()
    assert link_workspace.exists()


@pytest.mark.parametrize("processing_agent", ["main", "reviewer"])
def test_remove_bot_with_workspace_rejects_processing_session(tmp_path: Path, processing_agent: str):
    main_workspace = tmp_path / "main"
    bot_workspace = tmp_path / "bot"
    main_workspace.mkdir()
    bot_workspace.mkdir()
    manager = _manager(main_workspace)
    agents = [AgentProfile(id="reviewer", name="Reviewer")] if processing_agent == "reviewer" else []
    _add_managed_profile(manager, "team", bot_workspace, agents=agents)
    _completed_turn(manager, bot_workspace, alias="team")
    if processing_agent == "reviewer":
        _completed_turn(manager, bot_workspace, alias="team", agent_id=processing_agent)
    from bot.web.api_common import get_chat_session_for_alias

    _profile, _agent, session = get_chat_session_for_alias(manager, "team", 123, processing_agent)
    with session._lock:
        session.is_processing = True
    _assert_workspace_removal_error(manager, "team", 409, "conversation_switch_blocked")
    assert "team" in manager.managed_profiles
    assert bot_workspace.exists()
    expected_count = 2 if processing_agent == "reviewer" else 1
    assert len(_conversation_records(manager, bot_workspace, "team", str(bot_workspace))) == expected_count


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

    _assert_workspace_removal_error(manager, "main", 400, "invalid_bot_config")
    assert workspace.exists()
    assert (workspace / "keep.txt").is_file()


def test_remove_bot_with_workspace_rejects_root_directory(tmp_path: Path):
    main_workspace = tmp_path / "main"
    main_workspace.mkdir()
    root = tmp_path.anchor or str(tmp_path.resolve().anchor)
    manager = _manager(main_workspace)
    _add_managed_profile(manager, "team", Path(root))

    _assert_workspace_removal_error(manager, "team", 409, "workspace_delete_scope_mismatch")


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
