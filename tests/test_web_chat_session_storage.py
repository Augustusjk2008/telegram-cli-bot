import json
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock

import pytest

from bot.chat_identity import chat_session_user_id
from bot.models import BotProfile, flush_pending_session_persistence
from bot import session_store
from bot.sessions import (
    create_web_chat_session,
    get_or_create_session,
    get_web_chat_session,
    list_web_chat_sessions,
    rekey_bot_sessions,
    unload_bot_sessions,
)
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore


@pytest.mark.parametrize("backend", ["sqlite", "json"])
def test_named_snapshots_commit_before_return_and_restore_independently(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("SESSION_STORE_BACKEND", backend)
    monkeypatch.setenv("SESSION_STORE_FLUSH_INTERVAL_SECONDS", "60")
    workdir = str(tmp_path)
    legacy = get_or_create_session(12, "local", 10, workdir)
    child = get_or_create_session(12, "local", 10, workdir, agent_id="reviewer")
    custom_path = str(tmp_path / "private-install" / "codex")
    first = create_web_chat_session(
        12, "local", 10, workdir, "调查日志", selected_cli_type="codex_server", selected_cli_path=custom_path,
    )
    second = create_web_chat_session(12, "local", 10, workdir, "Review")
    assert re.fullmatch(r"ses_[0-9a-f]{32}", first.web_session_id)
    assert first.web_session_id != second.web_session_id
    assert legacy.web_session_id == child.web_session_id == ""
    assert (legacy.storage_scope, child.storage_scope) == ("main", "reviewer")
    key = f"12:{chat_session_user_id()}:@{first.web_session_id}"
    if backend == "sqlite":
        with sqlite3.connect(session_store.STORE_FILE.with_suffix(".sqlite3")) as conn:
            payload_json, = conn.execute("SELECT payload_json FROM sessions WHERE session_key=?", (key,)).fetchone()
        initial_payload = json.loads(payload_json)
    else:
        initial_payload = json.loads(session_store.STORE_FILE.read_text())[key]
    assert initial_payload["web_session_title"] == "调查日志"
    assert (initial_payload["selected_cli_type"], initial_payload["selected_cli_path"]) == ("codex_server", custom_path)
    with pytest.raises(AttributeError):
        first.web_session_id = second.web_session_id
    with pytest.raises(ValueError):
        get_or_create_session(12, "local", 10, workdir, agent_id=first.storage_scope)
    assert get_web_chat_session(12, "local", 20, workdir, first.web_session_id) is first
    for bot_id, session_id in [(13, first.web_session_id), (12, first.storage_scope), (12, "ses_" + "0" * 32)]:
        with pytest.raises(KeyError):
            get_web_chat_session(bot_id, "local", 10, workdir, session_id)
    assert list_web_chat_sessions(13, "other", 10) == []
    for index, session in enumerate((legacy, child, first, second)):
        session.codex_session_id = f"codex-{index}"
        session.claude_session_id = f"claude-{index}"
        session.antigravity_conversation_id = f"agy-{index}"
        session.deepseek_session_id = f"dsh-{index}"
        session.active_conversation_id = f"conversation-{index}"
        session.persist_debounced()
    flush_pending_session_persistence()
    rows = session_store.load_session_ids()
    for index, session in enumerate((legacy, child, first, second)):
        scope_suffix = "" if session.storage_scope == "main" else ":" + session.storage_scope
        assert rows[f"12:{chat_session_user_id()}{scope_suffix}"]["codex_session_id"] == f"codex-{index}"

    unload_bot_sessions("local")
    session_store.close_session_store()
    if backend == "sqlite":
        def forbid_full_scan(*_args, **_kwargs):
            pytest.fail("Named session lookup must use an indexed Bot/user or primary-key lookup")
        monkeypatch.setattr(session_store.SessionStoreSQLite, "load_all", forbid_full_scan)
    rows = list_web_chat_sessions(12, "local", 99)
    assert {row["id"]: row["title"] for row in rows} == {
        first.web_session_id: "调查日志", second.web_session_id: "Review",
    }
    assert next(row for row in rows if row["id"] == first.web_session_id)["selected_cli_type"] == "codex_server"
    assert all("selected_cli_path" not in row for row in rows)
    with ThreadPoolExecutor(max_workers=4) as pool:
        restored = list(pool.map(lambda _: get_web_chat_session(12, "local", 22, workdir, first.web_session_id), range(8)))
    assert all(item is restored[0] for item in restored)
    for index, original in enumerate((first, second), start=2):
        session = get_web_chat_session(12, "local", 22, workdir, original.web_session_id)
        assert session is not original
        assert session.agent_id == "main"
        assert session.storage_scope == "@" + original.web_session_id
        assert session.web_session_title == original.web_session_title
        assert session.selected_cli_type == original.selected_cli_type
        assert session.selected_cli_path == original.selected_cli_path
        assert session.codex_session_id == f"codex-{index}"
        assert session.claude_session_id == f"claude-{index}"
        assert session.antigravity_conversation_id == f"agy-{index}"
        assert session.deepseek_session_id == f"dsh-{index}"
        assert session.active_conversation_id == f"conversation-{index}"


def test_history_traces_revision_and_rename_preserve_scope(tmp_path):
    workdir = str(tmp_path)
    profile = BotProfile(alias="local", cli_type="deepseek", working_dir=workdir)
    history = ChatHistoryService(ChatStore(tmp_path))
    legacy = get_or_create_session(12, "local", 10, workdir)
    a = create_web_chat_session(12, "local", 10, workdir, "A")
    b = create_web_chat_session(12, "local", 10, workdir, "B")
    handles = []
    for index, session in enumerate((legacy, a, b)):
        handle = history.start_turn(profile=profile, session=session, user_text=f"request {index}", native_provider="deepseek")
        history.append_trace_events(handle, [{"kind": "tool_result", "call_id": "same", "payload": {"index": index}}])
        history.complete_turn(handle, content=f"reply {index}", completion_state="completed", native_session_id=f"native-{index}")
        handles.append(handle)
    for index, session in enumerate((legacy, a, b)):
        handle = handles[index]
        assert [m["content"] for m in history.list_history(profile, session)] == [f"request {index}", f"reply {index}"]
        assert history.build_session_snapshot(profile, session)["history_count"] == 2
        delta = history.list_history_delta(profile, session, revision=0)
        assert {m["id"] for m in delta["items"]} == {handle.user_message_id, handle.assistant_message_id}
        for source_index, source in enumerate(handles):
            trace = history.get_message_trace(profile, session, source.assistant_message_id, compact=True)
            event = history.get_message_trace_event(profile, session, source.assistant_message_id, kind="tool_result", call_id="same")
            if source_index == index:
                assert trace["trace"][0]["payload"]["index"] == index
                assert event["event"]["payload"]["index"] == index
            else:
                assert trace is None and event is None
    # Several conversations under one named scope must all survive an admin rename.
    extra = history.store.create_conversation(
        bot_id=12, bot_alias="local", user_id=a.user_id, agent_id=a.storage_scope, cli_type="deepseek",
        working_dir=workdir, session_epoch=0, native_provider="deepseek",
    )
    a.active_conversation_id = extra
    a.deepseek_session_id = "native-extra"
    a.persist()
    assert session_store.rename_bot_sessions(12, 15, old_alias="local", new_alias="renamed") == 3
    assert rekey_bot_sessions(12, 15, old_alias="local", new_alias="renamed") == 3
    assert history.store.rename_bot_identity(old_bot_id=12, new_bot_id=15, old_alias="local", new_alias="renamed") == 4
    assert get_web_chat_session(15, "renamed", 10, workdir, a.web_session_id) is a
    unload_bot_sessions("renamed")
    session_store.close_session_store()
    assert list_web_chat_sessions(12, "local", 10) == []
    restored = get_web_chat_session(15, "renamed", 10, workdir, a.web_session_id)
    assert restored.active_conversation_id == extra
    assert restored.deepseek_session_id == "native-extra"
    assert history.store.get_conversation(handles[1].conversation_id)["bot_id"] == 15
    assert history.get_message_trace(profile, restored, handles[1].assistant_message_id)
    restored_b = get_web_chat_session(15, "renamed", 10, workdir, b.web_session_id)
    assert [m["content"] for m in history.list_history(profile, restored_b)] == ["request 2", "reply 2"]
    # A stale active id must never cause a different session's conversation to be removed.
    restored.active_conversation_id = handles[2].conversation_id
    history.reset_active_conversation(restored)
    assert history.store.get_conversation(handles[2].conversation_id)["agent_id"] == restored_b.storage_scope


@pytest.mark.asyncio
async def test_app_server_owner_matches_named_scope(tmp_path, monkeypatch):
    from bot.manager import _close_codex_server_runtimes

    registry = Mock(close_owner=AsyncMock())
    monkeypatch.setattr("bot.codex_server.runtime.get_codex_server_registry", lambda: registry)
    sessions = [create_web_chat_session(12, "local", 10, str(tmp_path), title) for title in ["A", "B"]]
    await _close_codex_server_runtimes("local")
    owners = {call.args[0] for call in registry.close_owner.await_args_list}
    assert owners == {(12, chat_session_user_id(), s.storage_scope) for s in sessions}


def test_json_to_sqlite_migration_keeps_named_and_legacy_bindings(tmp_path, monkeypatch):
    workdir = str(tmp_path)
    monkeypatch.setenv("SESSION_STORE_BACKEND", "json")
    main = get_or_create_session(41, "bot", 20, workdir)
    main.codex_session_id = "old-thread"
    session = create_web_chat_session(41, "bot", 20, workdir, "Experiment")
    session.codex_session_id = "new-thread"
    unload_bot_sessions("bot")

    monkeypatch.setenv("SESSION_STORE_BACKEND", "sqlite")
    assert list_web_chat_sessions(41, "bot", 20) == [{"id": session.web_session_id, "title": "Experiment"}]
    assert get_web_chat_session(41, "bot", 20, workdir, session.web_session_id).codex_session_id == "new-thread"
    assert get_or_create_session(41, "bot", 20, workdir).codex_session_id == "old-thread"
    assert session_store.session_store_diagnostics()["active_backend"] == "sqlite"


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_rename_retry_combines_existing_transcript_with_its_pinned_tool(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("SESSION_STORE_BACKEND", backend)
    workspace = str(tmp_path)
    source = create_web_chat_session(
        11, "old", 1, workspace, "Review", selected_cli_type="claude", selected_cli_path="/private/claude",
    )
    # An existing copy of the same chat at the destination has newer conversation state.
    assert session_store.insert_web_session_snapshot(
        22, source.user_id, source.web_session_id, workspace, "Review", bot_alias="new",
    )
    dest = get_web_chat_session(22, "new", 1, workspace, source.web_session_id)
    dest.message_count = 9
    dest.claude_session_id = "review-thread"
    dest.persist()
    session_store.rename_bot_sessions(11, 22, old_alias="old", new_alias="new")
    rekey_bot_sessions(11, 22, old_alias="old", new_alias="new")
    for cold in (False, True):
        if cold:
            unload_bot_sessions("new")
            session_store.close_session_store()
        restored = get_web_chat_session(22, "new", 1, workspace, source.web_session_id)
        assert (restored.selected_cli_type, restored.selected_cli_path) == ("claude", "/private/claude")
        assert restored.claude_session_id == "review-thread"


def test_failed_creation_preserves_existing_json_and_publishes_no_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_STORE_BACKEND", "json")
    main = get_or_create_session(41, "bot", 20, str(tmp_path))
    main.codex_session_id = "old-thread"
    main.persist()
    previous = session_store.STORE_FILE.read_bytes()

    def full_disk(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(session_store.os, "replace", full_disk)
    with pytest.raises(OSError, match="disk full"):
        create_web_chat_session(41, "bot", 20, str(tmp_path), "Unsaved")
    assert session_store.STORE_FILE.read_bytes() == previous
    assert list_web_chat_sessions(41, "bot", 20) == []


@pytest.mark.parametrize("unambiguous", [True, False])
def test_rename_moves_unlabeled_legacy_history_only_with_an_unambiguous_owner(tmp_path, unambiguous):
    store = ChatStore(tmp_path)
    old = store.create_conversation(
        bot_id=41, bot_alias="", user_id=1, agent_id="main", cli_type="codex", working_dir=str(tmp_path),
        session_epoch=0, native_provider="codex",
    )
    store.rename_bot_identity(
        old_bot_id=41, new_bot_id=42, old_alias="worker", new_alias="renamed",
        include_unlabeled_legacy=unambiguous,
    )
    assert store.get_conversation(old)["bot_id"] == (42 if unambiguous else 41)


@pytest.mark.parametrize("backend", ["sqlite", "json"])
@pytest.mark.parametrize("new_alias", ["gag", "new-name"])
def test_colliding_bot_aliases_keep_named_snapshots_through_rename_and_removal(
    tmp_path, monkeypatch, backend, new_alias,
):
    import zlib
    from bot.sessions import clear_bot_sessions, update_bot_alias

    def checksum(alias):
        return -zlib.adler32(f"web:{alias}".encode())

    monkeypatch.setenv("SESSION_STORE_BACKEND", backend)
    old_id = checksum("eee")
    assert old_id == checksum("fcf") == checksum("gag")
    new_id = checksum(new_alias)
    workdir = str(tmp_path)
    owner = create_web_chat_session(old_id, " EEE ", 1, workdir, "Mine")
    neighbor = create_web_chat_session(old_id, "fcf", 1, workdir, "Theirs")
    for session in (owner, neighbor):
        session.codex_session_id = "native-" + session.web_session_title
        session.persist()
    for cold in (False, True):
        if cold:
            unload_bot_sessions("eee")
            unload_bot_sessions("fcf")
            session_store.close_session_store()
        with pytest.raises(KeyError):
            get_web_chat_session(old_id, "fcf", 1, workdir, owner.web_session_id)
        assert list_web_chat_sessions(old_id, " EEE ", 1) == [{"id": owner.web_session_id, "title": "Mine"}]
        assert get_web_chat_session(old_id, "EEE", 2, workdir, owner.web_session_id).bot_alias == "eee"
        assert not session_store.load_session(old_id, chat_session_user_id(), owner.storage_scope, bot_alias="fcf")

    # The manager's early alias update precedes snapshot migration and live rekey.
    update_bot_alias("eee", new_alias)
    assert session_store.rename_bot_sessions(old_id, new_id, old_alias="EEE", new_alias=new_alias) == 1
    assert rekey_bot_sessions(old_id, new_id, old_alias="eee", new_alias=new_alias) == 1
    assert session_store.rename_bot_sessions(old_id, new_id, old_alias="eee", new_alias=new_alias) == 0
    for cold in (False, True):
        if cold:
            unload_bot_sessions(new_alias)
            session_store.close_session_store()
        assert list_web_chat_sessions(old_id, "eee", 2) == []
        with pytest.raises(KeyError):
            get_web_chat_session(old_id, "eee", 2, workdir, owner.web_session_id)
        assert get_web_chat_session(new_id, new_alias, 1, workdir, owner.web_session_id).codex_session_id == "native-Mine"
        assert get_web_chat_session(old_id, "fcf", 1, workdir, neighbor.web_session_id).codex_session_id == "native-Theirs"

    clear_bot_sessions(new_id, bot_alias=new_alias)
    assert list_web_chat_sessions(new_id, new_alias, 2) == []
    unload_bot_sessions("fcf")
    assert get_web_chat_session(old_id, "fcf", 1, workdir, neighbor.web_session_id).codex_session_id == "native-Theirs"


@pytest.mark.parametrize("backend", ["sqlite", "json"])
def test_named_snapshot_without_alias_cannot_be_claimed_by_lookup_or_shared_migration(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("SESSION_STORE_BACKEND", backend)
    session_id = "ses_" + "a" * 32
    user_id = chat_session_user_id()
    key = f"1:{user_id}:@{session_id}"
    old_user_key = f"1:{user_id + 1}:@{session_id}"
    session_store.save_session_ids({
        key: {"web_session_id": session_id, "web_session_title": "Unknown owner"},
        old_user_key: {"web_session_id": session_id, "web_session_title": "Foreign row", "bot_alias": "other"},
    })
    assert session_store.migrate_sessions_to_shared(1, user_id) == 0
    for alias in ("other", "new", ""):
        assert list_web_chat_sessions(1, alias, user_id) == []
        with pytest.raises(KeyError):
            get_web_chat_session(1, alias, user_id, str(tmp_path), session_id)
    assert set(session_store.load_session_ids()) == {key, old_user_key}


@pytest.mark.parametrize("new_id", [33, 44])
def test_favorite_rename_handles_bot_checksum_collisions_and_retries(tmp_path, new_id):
    from bot.web.chat_favorite_store import ChatFavoriteStore, FavoriteScope, build_favorite_item

    store = ChatFavoriteStore(tmp_path)
    scopes = ["main", "@ses_" + "1" * 32, "@ses_" + "2" * 32]
    for alias, scope in [("old", scope) for scope in scopes] + [("neighbor", scopes[0])]:
        favorite = build_favorite_item(
            scope=FavoriteScope(33, 2, scope, bot_alias=alias), bot_alias=alias,
            conversation_id="conv", message_id="msg", message_key="key", answer_text=alias + scope,
        )
        store.upsert_favorite(favorite)
    assert store.rename_bot(33, new_id, " OLD ", "New") == 3
    assert store.rename_bot(33, new_id, "old", "new") == 0
    for scope in scopes:
        target = FavoriteScope(new_id, 2, scope, bot_alias="new")
        saved, = store.list_favorites(target)
        assert (saved["bot_alias"], saved["answer_text"]) == ("new", "old" + scope)
        assert store.list_favorites(FavoriteScope(33, 2, scope, bot_alias="old")) == []
        assert store.upsert_favorite(saved)["id"] == saved["id"]
        assert len(store.list_favorites(target)) == 1
    assert store.delete_favorites_for_bot(bot_id=new_id, bot_alias="new") == 3
    kept, = store.list_favorites(FavoriteScope(33, 2, bot_alias="neighbor"))
    assert kept["answer_text"] == "neighbormain"


def test_same_hash_rename_invalidates_inflight_old_owner_restore(tmp_path, monkeypatch):
    import bot.sessions as session_module

    workdir = str(tmp_path)
    session_id = create_web_chat_session(33, "old", 1, workdir, "Mine").web_session_id
    unload_bot_sessions("old")
    read = threading.Event()
    release = threading.Event()
    build = session_module._build_session_from_store

    def delayed_build(**kwargs):
        if kwargs["bot_alias"] == "old":
            read.set()
            assert release.wait(5)
        return build(**kwargs)

    monkeypatch.setattr(session_module, "_build_session_from_store", delayed_build)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(get_web_chat_session, 33, "old", 1, workdir, session_id)
        try:
            assert read.wait(5)
            assert session_store.rename_bot_sessions(33, 33, old_alias="old", new_alias="new") == 1
            rekey_bot_sessions(33, 33, old_alias="old", new_alias="new")
        finally:
            release.set()
        with pytest.raises(KeyError):
            pending.result(timeout=5)
    assert get_web_chat_session(33, "new", 1, workdir, session_id).bot_alias == "new"
