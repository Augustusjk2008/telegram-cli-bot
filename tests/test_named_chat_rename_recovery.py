"""Exercise the real stores using private data and injected interruptions."""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from bot import manager as manager_module, session_store, sessions
from bot.manager import ChatRenamePending, MultiBotManager
from bot.models import BotProfile
from bot.profile_store import save_managed_profiles
from bot.web.api_common import resolve_session_bot_id
from bot.web.chat_favorite_store import ChatFavoriteStore, FavoriteScope, build_favorite_item
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore
from bot.web.permission_store import BotPermissionStore


def _open_manager(path, grants):
    return MultiBotManager(
        BotProfile(alias="main", working_dir=str(path.parent)), str(path),
        rename_bot_permissions=grants.rename_bot,
    )


def _seed(tmp_path, aliases=("worker",), *, directory_permissions=False):
    path = tmp_path / "managed.json"
    grants = BotPermissionStore(tmp_path / ("permissions" if directory_permissions else "permissions.json"))
    old = aliases[0]
    save_managed_profiles(path, {alias: BotProfile(alias=alias, working_dir=str(tmp_path)) for alias in aliases})
    manager = _open_manager(path, grants)
    grants.set_bot_owner(old, "owner", grant_owner=True)
    old_id = resolve_session_bot_id(manager, old)
    session = sessions.create_web_chat_session(old_id, old, 1, str(tmp_path), "保存的对话")
    history = ChatHistoryService(ChatStore(tmp_path))
    handle = history.start_turn(profile=manager.get_profile(old), session=session, user_text="question", native_provider="codex")
    history.complete_turn(handle, content="answer", completion_state="completed", native_session_id="native-code")
    session.codex_session_id = "native-code"
    session.persist()
    ChatFavoriteStore(tmp_path).upsert_favorite(build_favorite_item(
        scope=FavoriteScope(old_id, session.user_id, session.storage_scope, bot_alias=old),
        bot_alias=old, conversation_id=handle.conversation_id,
        message_id=handle.assistant_message_id, message_key="key", answer_text="answer",
    ))
    return path, grants, manager, session.web_session_id, handle


def _discard_process_cache():
    with sessions.sessions_lock:
        runtime = list(sessions.sessions.values())
        sessions.sessions.clear()
    for session in runtime:
        session.disable_persistence()
    session_store.close_session_store()


def _assert_recovered(manager, path, grants, session_id, handle):
    new_id = resolve_session_bot_id(manager, "renamed")
    restored = sessions.get_web_chat_session(new_id, "renamed", 1, str(path.parent), session_id)
    assert (restored.web_session_title, restored.codex_session_id) == ("保存的对话", "native-code")
    assert restored.active_conversation_id == handle.conversation_id
    assert ChatStore(path.parent).get_conversation(handle.conversation_id)["bot_alias"] == "renamed"
    favorites = ChatFavoriteStore(path.parent).list_favorites(
        FavoriteScope(new_id, restored.user_id, restored.storage_scope, bot_alias="renamed"),
    )
    assert [row["message_id"] for row in favorites] == [handle.assistant_message_id]
    assert grants.allowed_bots_for_account("owner") == {"renamed"}
    assert grants.bot_owner("renamed") == "owner"
    (record,) = json.loads(path.read_text())["bots"]
    assert "pending_rename_to" not in record
    assert record["alias"] == "renamed"
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("stage", ["snapshots", "live", "history", "favorites", "permissions", "profile"])
@pytest.mark.asyncio
async def test_replay_partial_rename_with_cold_open_and_old_alias_retry(tmp_path, monkeypatch, stage):
    path, grants, manager, session_id, handle = _seed(tmp_path)
    owner, method = {
        "snapshots": (session_store, "rename_bot_sessions"),
        "live": (sessions, "rekey_bot_sessions"),
        "history": (ChatStore, "rename_bot_identity"),
        "favorites": (ChatFavoriteStore, "rename_bot"),
        "permissions": (BotPermissionStore, "rename_bot"),
        "profile": (manager_module, "save_managed_profiles"),
    }[stage]
    original = getattr(owner, method)

    def interrupted(*args, **kwargs):
        if stage == "profile":
            if "renamed" in args[1]:
                raise OSError("interrupted final profile replacement")
            return original(*args, **kwargs)
        original(*args, **kwargs)
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as fault:
        fault.setattr(owner, method, interrupted)
        manager.rename_bot_permissions = grants.rename_bot
        with pytest.raises(ChatRenamePending):
            await manager.rename_bot("worker", "renamed")
        (record,) = json.loads(path.read_text())["bots"]
        assert (record["alias"], record["pending_rename_to"]) == ("worker", "renamed")
        _discard_process_cache()
        reopened = _open_manager(path, grants)
        for alias in ("worker", "renamed"):
            with pytest.raises(ChatRenamePending):
                reopened.get_profile(alias)
        assert reopened.get_profile("main").alias == "main"

    # A clean startup replays without a client request; repeating the original
    # request still returns the committed profile after another process restart.
    recovered = _open_manager(path, grants)
    assert set(recovered.managed_profiles) == {"renamed"}
    assert (await _open_manager(path, grants).rename_bot("worker", "renamed")).alias == "renamed"
    _assert_recovered(recovered, path, grants, session_id, handle)


@pytest.mark.parametrize("persisted", [False, True])
@pytest.mark.asyncio
async def test_failure_writing_first_intent_leaves_a_recoverable_profile(tmp_path, monkeypatch, persisted):
    path, grants, manager, session_id, handle = _seed(tmp_path)
    save = manager._save_profiles

    def fail_intent():
        if persisted:
            save()
        raise OSError("interrupted intent write")

    monkeypatch.setattr(manager, "_save_profiles", fail_intent)
    with pytest.raises(OSError):
        await manager.rename_bot("worker", "renamed")
    assert grants.allowed_bots_for_account("owner") == {"worker"}
    _discard_process_cache()
    reopened = _open_manager(path, grants)
    assert (await reopened.rename_bot("worker", "renamed")).alias == "renamed"
    _assert_recovered(reopened, path, grants, session_id, handle)


@pytest.mark.parametrize("backend", ["sqlite", "json"])
@pytest.mark.asyncio
async def test_named_rename_resumes_on_first_access_after_unlock(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("SESSION_STORE_BACKEND", backend)
    path, grants, manager, session_id, handle = _seed(tmp_path)
    notifications = []
    manager.on_chat_renamed = lambda old, new: notifications.append((old, new))
    with monkeypatch.context() as fault:
        def locked(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")
        fault.setattr(session_store, "rename_bot_sessions", locked)
        with pytest.raises(ChatRenamePending):
            await manager.rename_bot("worker", "renamed")
        with pytest.raises(ChatRenamePending):
            manager.ensure_chat_rename_ready("renamed")
    manager.ensure_chat_rename_ready("renamed")
    manager.ensure_chat_rename_ready("worker")
    assert notifications == [("worker", "renamed")]
    _assert_recovered(manager, path, grants, session_id, handle)


@pytest.mark.asyncio
async def test_real_history_write_lock_resumes_after_cold_start(tmp_path, monkeypatch):
    path, grants, manager, session_id, handle = _seed(tmp_path)
    database = ChatStore(tmp_path).db_path
    connect = sqlite3.connect
    blocker = connect(database)
    blocker.execute("BEGIN IMMEDIATE")

    def short_history_timeout(db, *args, **kwargs):
        if db == database:
            kwargs["timeout"] = 0.01
        return connect(db, *args, **kwargs)

    try:
        with monkeypatch.context() as fault:
            fault.setattr(sqlite3, "connect", short_history_timeout)
            with pytest.raises(ChatRenamePending) as error:
                await manager.rename_bot("worker", "renamed")
            assert isinstance(error.value.__cause__, sqlite3.OperationalError)
            _discard_process_cache()
            reopened = _open_manager(path, grants)
            with pytest.raises(ChatRenamePending):
                reopened.ensure_chat_rename_ready("renamed")
    finally:
        blocker.rollback()
        blocker.close()
    assert (await reopened.rename_bot("worker", "renamed")).alias == "renamed"
    _assert_recovered(reopened, path, grants, session_id, handle)


@pytest.mark.parametrize(("old", "new"), [("eee", "renamed"), ("worker", "eee")])
@pytest.mark.asyncio
async def test_rename_preserves_unrelated_colliding_bots_data(tmp_path, old, new):
    path, grants, manager, session_id, _ = _seed(tmp_path, (old, "fcf"))
    other_id = resolve_session_bot_id(manager, "fcf")
    assert other_id == resolve_session_bot_id(manager, "eee")
    neighbor = sessions.create_web_chat_session(other_id, "fcf", 1, str(tmp_path), "Neighbor")
    neighbor.codex_session_id = "native-neighbor"
    neighbor.persist()
    legacy = sessions.get_or_create_session(other_id, "fcf", 1, str(tmp_path))
    legacy.codex_session_id = "legacy-neighbor"
    legacy.persist()
    history = ChatHistoryService(ChatStore(tmp_path))
    handle = history.start_turn(profile=manager.get_profile("fcf"), session=legacy, user_text="neighbor", native_provider="codex")
    history.complete_turn(handle, content="answer", completion_state="completed")
    if old == "worker":
        owner = sessions.get_or_create_session(resolve_session_bot_id(manager, old), old, 1, str(tmp_path))
        owner.codex_session_id = "other-binding"
        owner.persist()
    grants.set_bot_owner("fcf", "neighbor", grant_owner=True)

    assert (await manager.rename_bot(old, new)).alias == new
    assert sessions.get_or_create_session(other_id, "fcf", 1, str(tmp_path)) is legacy
    _discard_process_cache()
    assert sessions.get_web_chat_session(other_id, "fcf", 1, str(tmp_path), neighbor.web_session_id).codex_session_id == "native-neighbor"
    assert sessions.get_or_create_session(other_id, "fcf", 1, str(tmp_path)).codex_session_id == "legacy-neighbor"
    assert ChatStore(tmp_path).get_conversation(handle.conversation_id)["bot_alias"] == "fcf"
    assert grants.allowed_bots_for_account("neighbor") == {"fcf"}
    new_id = resolve_session_bot_id(manager, new)
    assert sessions.get_web_chat_session(new_id, new, 1, str(tmp_path), session_id).codex_session_id == "native-code"



@pytest.mark.asyncio
async def test_final_profile_replace_survives_lost_acknowledgement(tmp_path, monkeypatch):
    path, grants, manager, session_id, handle = _seed(tmp_path)
    save = manager_module.save_managed_profiles

    def lose_acknowledgement(path, profiles, **kwargs):
        save(path, profiles, **kwargs)
        if "renamed" in profiles:
            raise OSError("profile committed before interruption")

    with monkeypatch.context() as fault:
        fault.setattr(manager_module, "save_managed_profiles", lose_acknowledgement)
        with pytest.raises(ChatRenamePending):
            await manager.rename_bot("worker", "renamed")
    _discard_process_cache()
    reopened = _open_manager(path, grants)
    assert (await reopened.rename_bot("worker", "renamed")).alias == "renamed"
    _assert_recovered(reopened, path, grants, session_id, handle)


@pytest.mark.parametrize("unavailable", ["sqlite", "json", "favorites"])
@pytest.mark.asyncio
async def test_temporarily_unreadable_existing_store_keeps_the_intent(tmp_path, monkeypatch, unavailable):
    if unavailable == "json":
        monkeypatch.setenv("SESSION_STORE_BACKEND", "json")
    path, grants, manager, session_id, handle = _seed(tmp_path)
    _discard_process_cache()
    with monkeypatch.context() as fault:
        if unavailable == "sqlite":
            def database_locked(store):
                raise sqlite3.OperationalError("database is locked")
            fault.setattr(session_store.SessionStoreSQLite, "ensure_ready", database_locked)
        else:
            blocked_file = session_store.STORE_FILE if unavailable == "json" else ChatFavoriteStore(tmp_path).path
            read = Path.read_text

            def fail_store_read(file, *args, **kwargs):
                if file == blocked_file:
                    raise PermissionError("temporarily unavailable")
                return read(file, *args, **kwargs)
            fault.setattr(Path, "read_text", fail_store_read)
        with pytest.raises(ChatRenamePending):
            await manager.rename_bot("worker", "renamed")
    assert (await manager.rename_bot("worker", "renamed")).alias == "renamed"
    _assert_recovered(manager, path, grants, session_id, handle)


@pytest.mark.parametrize("fault_at", ["enumeration", "account_read"])
@pytest.mark.asyncio
async def test_directory_permissions_must_be_read_before_completing_a_rename(tmp_path, monkeypatch, fault_at):
    path, grants, manager, session_id, handle = _seed(tmp_path, directory_permissions=True)
    grants.set_allowed_bots("member", ["worker", "other"])
    scan, read = os.scandir, Path.read_text

    def deny_listing(directory):
        if directory == grants.accounts_dir:
            raise PermissionError("account directory is unreadable")
        return scan(directory)

    def deny_read(file, *args, **kwargs):
        if file == grants.accounts_dir / "member.json":
            raise PermissionError("account record is unreadable")
        return read(file, *args, **kwargs)

    with monkeypatch.context() as fault:
        if fault_at == "enumeration":
            fault.setattr(os, "scandir", deny_listing)
        else:
            fault.setattr(Path, "read_text", deny_read)
        with pytest.raises(ChatRenamePending):
            await manager.rename_bot("worker", "renamed")
        assert json.loads(path.read_text())["bots"][0]["pending_rename_to"] == "renamed"
        assert grants.bot_owner("worker") == "owner"
        _discard_process_cache()
    reopened = _open_manager(path, grants)
    _assert_recovered(reopened, path, grants, session_id, handle)
    assert grants.allowed_bots_for_account("member") == {"renamed", "other"}


@pytest.mark.asyncio
async def test_retry_keeps_preexisting_collision_decision_after_neighbor_profile_removed(tmp_path, monkeypatch):
    path, grants, manager, _, _ = _seed(tmp_path, ("eee", "fcf"))
    old_id = resolve_session_bot_id(manager, "eee")
    legacy = sessions.get_or_create_session(old_id, "fcf", 1, str(tmp_path))
    legacy.codex_session_id = "neighbor"
    legacy.persist()
    with monkeypatch.context() as fault:
        def unavailable(*args, **kwargs):
            raise sqlite3.OperationalError("locked")
        fault.setattr(session_store, "rename_bot_sessions", unavailable)
        with pytest.raises(ChatRenamePending):
            await manager.rename_bot("eee", "renamed")
    await manager.remove_bot("fcf")
    _discard_process_cache()
    reopened = _open_manager(path, grants)
    assert set(reopened.managed_profiles) == {"renamed"}
    assert session_store.load_session(old_id, legacy.user_id)["codex_session_id"] == "neighbor"
    assert session_store.load_session(resolve_session_bot_id(reopened, "renamed"), legacy.user_id) is None
