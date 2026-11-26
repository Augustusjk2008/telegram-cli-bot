"""Exercise named chat admission, cancellation and native resume through the normal turn pipeline."""

import asyncio
import sys
import threading
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.sessions import unload_bot_sessions
from bot.web import api_service as api
from bot.web.api_common import WebApiError
from bot.web.chat_targets import create_chat_session, resolve_named_chat_target


@pytest.fixture
def chat_bot(tmp_path, monkeypatch):
    profile = BotProfile(alias="main", cli_type="codex", cli_path="codex", working_dir=str(tmp_path))
    profile.cluster = replace(profile.cluster, enabled=True, max_parallel_agents=2)
    manager = MultiBotManager(profile, str(tmp_path / "bots.json"))
    # A real child process exercises process ownership, stop and cleanup without a provider account.
    executable = tmp_path / "fixture_cli.py"
    executable.write_text(
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "text, thread = sys.argv[1:]\n"
        "print(json.dumps({'type':'thread.started','thread_id':thread}), flush=True)\n"
        "if text.startswith('hold'):\n"
        "    Path(text + '.started').touch()\n"
        "    while not Path(text + '.finish').exists(): time.sleep(0.02)\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'assistant_message','text':text}}), flush=True)\n"
        "print(json.dumps({'type':'turn.completed'}), flush=True)\n",
        encoding="utf-8",
    )
    bindings = {}

    def command(*, user_text, session_id, **kwargs):
        bindings[user_text] = session_id
        return [sys.executable, "-u", str(executable), user_text, session_id or f"native-{user_text}"], False

    monkeypatch.setattr(api, "resolve_cli_executable", lambda *_: sys.executable)
    monkeypatch.setattr(api, "build_cli_command", command)
    monkeypatch.setattr(api, "_start_codex_rate_limit_capture", AsyncMock(return_value=None))
    monkeypatch.setattr(api, "resolve_cli_context_usage", lambda *args, **kwargs: None)
    return manager, bindings


async def _send(manager, target, prompt):
    return [event async for event in api.stream_chat(manager, "main", 1, prompt, target=target)]


def _create(manager, title):
    item = create_chat_session(manager, "main", 1, title)
    return resolve_named_chat_target(manager, "main", 1, item["id"])


async def _started(marker, task):
    async def wait_for_marker():
        while not marker.exists():
            if task.done():
                pytest.fail(f"CLI exited before startup: {task.result()}")
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait_for_marker(), 8)


@pytest.mark.asyncio
async def test_parallel_turns_stop_independently_and_resume_their_native_threads(chat_bot, tmp_path):
    manager, bindings = chat_bot
    a, b = (_create(manager, name) for name in ("A", "B"))
    for target, text in ((a, "A"), (b, "B")):
        assert (await _send(manager, target, text))[-1]["output"] == text
    active_a = asyncio.create_task(_send(manager, a, "hold-A"))
    active_b = asyncio.create_task(_send(manager, b, "hold-B"))
    try:
        await asyncio.gather(_started(tmp_path / "hold-A.started", active_a), _started(tmp_path / "hold-B.started", active_b))
        assert (await _send(manager, a, "duplicate"))[-1]["code"] == "session_busy"
        stopped = await api.kill_user_process(manager, "main", 1, target=b)
        assert stopped["killed"]
        assert (await asyncio.wait_for(active_b, 8))[-1]["message"]["meta"]["completion_state"] == "cancelled"
        assert a.session.is_processing and not active_a.done()
    finally:
        (tmp_path / "hold-A.finish").touch()
        (tmp_path / "hold-B.finish").touch()
        await asyncio.wait_for(asyncio.gather(active_a, active_b), 10)
    assert active_a.result()[-1]["output"] == "hold-A"

    unload_bot_sessions("main")
    for original, label in ((a, "A"), (b, "B")):
        restored = resolve_named_chat_target(manager, "main", 1, original.session.web_session_id)
        assert restored.session is not original.session
        assert restored.session.active_conversation_id == original.session.active_conversation_id
        history = api.get_history(manager, "main", 1, target=restored)
        assert [item["content"] for item in history["items"] if item["role"] == "user"] == [label, f"hold-{label}"]
        delta = api.get_history_delta(manager, "main", 1, "", target=restored, revision=0)
        assert delta["revision"] == history["revision"]
        assert api.get_overview(manager, "main", 1, target=restored)["session"]["history_count"] == len(history["items"])
        assert (await _send(manager, restored, f"continue-{label}"))[-1]["output"] == f"continue-{label}"
        assert bindings[f"continue-{label}"] == f"native-{label}"
    assert not api.get_history(manager, "main", 1)["items"]


@pytest.mark.asyncio
async def test_one_slot_is_shared_by_named_and_default_chat_and_released_after_stop(chat_bot, tmp_path):
    manager, _ = chat_bot
    profile = manager.main_profile
    profile.cluster = replace(profile.cluster, enabled=False, max_parallel_agents=1)
    first, second = (_create(manager, name) for name in ("A", "B"))
    active = asyncio.create_task(_send(manager, None, "hold-default"))
    try:
        await _started(tmp_path / "hold-default.started", active)
        with pytest.raises(WebApiError, match="Bot") as denied:
            await api.run_chat(manager, "main", 1, "no slot", target=first)
        assert denied.value.code == "bot_chat_capacity"
        assert (await _send(manager, second, "still full"))[-1]["code"] == "bot_chat_capacity"
        assert not api.get_history(manager, "main", 1, target=second)["items"]
        await api.kill_user_process(manager, "main", 1)
    finally:
        (tmp_path / "hold-default.finish").touch()
        await asyncio.wait_for(active, 10)
    assert (await api.run_chat(manager, "main", 1, "next", target=second))["output"] == "next"


@pytest.mark.asyncio
async def test_legacy_agent_reset_cannot_remove_a_loaded_named_chat(chat_bot):
    manager, _ = chat_bot
    chat = _create(manager, "Keep history")
    await _send(manager, chat, "keep")
    with pytest.raises(WebApiError) as rejected:
        await api.reset_user_session(manager, "main", 1, agent_id=chat.session.storage_scope)
    assert rejected.value.code == "agent_not_found"
    assert api.get_history(manager, "main", 1, target=chat)["items"][-1]["content"] == "keep"


@pytest.mark.asyncio
async def test_workspace_move_and_named_session_creation_cannot_interleave(chat_bot, tmp_path, monkeypatch):
    manager, _ = chat_bot
    previous = _create(manager, "Before move")
    new_workspace = tmp_path / "new"
    new_workspace.mkdir()
    entered, resume = asyncio.Event(), asyncio.Event()
    update = manager.set_bot_workdir

    async def hold_update(*args, **kwargs):
        entered.set()
        await resume.wait()
        return await update(*args, **kwargs)

    monkeypatch.setattr(manager, "set_bot_workdir", hold_update)
    move = asyncio.create_task(api.update_bot_workdir(manager, "main", str(new_workspace)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        with pytest.raises(WebApiError) as rejected:
            create_chat_session(manager, "main", 1, "During move")
        assert rejected.value.code == "chat_catalog_busy"
        with pytest.raises(WebApiError) as rejected:
            await api.create_conversation(manager, "main", 1, target=previous)
        assert rejected.value.code == "chat_catalog_busy"
    finally:
        resume.set()
        await move
    assert _create(manager, "After move").session.working_dir == str(new_workspace)
    with pytest.raises(WebApiError) as stale:
        await api.create_conversation(manager, "main", 1, target=previous)
    assert stale.value.code == "session_workdir_changed"


@pytest.mark.asyncio
async def test_active_named_conversation_write_holds_its_workspace(chat_bot, tmp_path, monkeypatch):
    manager, _ = chat_bot
    target = _create(manager, "A")
    entered, resume = threading.Event(), threading.Event()
    create = api._create_agent_conversation

    def slow_create(*args, **kwargs):
        entered.set()
        assert resume.wait(5)
        return create(*args, **kwargs)

    monkeypatch.setattr(api, "_create_agent_conversation", slow_create)
    writing = asyncio.create_task(api.create_conversation(manager, "main", 1, target=target))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        with pytest.raises(WebApiError) as rejected:
            await api.update_bot_workdir(manager, "main", str(tmp_path / "elsewhere"))
        assert rejected.value.code == "chat_catalog_busy"
    finally:
        resume.set()
        created = await writing
    assert api.list_conversations(manager, "main", 1, target=target)["active_conversation_id"] == created["conversation"]["id"]


@pytest.mark.asyncio
async def test_managed_bot_rename_waits_for_default_admission_and_keeps_named_favorites(chat_bot):
    manager, _ = chat_bot
    profile = replace(manager.main_profile, alias="worker", cluster=replace(manager.main_profile.cluster, enabled=False))
    manager.managed_profiles[profile.alias] = profile
    item = create_chat_session(manager, "worker", 1, "Review")
    target = resolve_named_chat_target(manager, "worker", 1, item["id"])
    result = await api.run_chat(manager, "worker", 1, "review", target=target)
    api.upsert_favorite_answer(manager, "worker", 1, {
        "conversation_id": target.session.active_conversation_id, "message_id": result["message"]["id"],
    }, target=target)
    with api.reserve_bot_chat_slot(manager, profile):
        with pytest.raises(WebApiError) as denied:
            await api.rename_managed_bot(manager, "worker", "renamed")
        assert denied.value.code == "chat_catalog_busy"
    await api.rename_managed_bot(manager, "worker", "renamed")
    unload_bot_sessions("renamed")
    restored = resolve_named_chat_target(manager, "renamed", 1, item["id"])
    assert restored.session.codex_session_id == "native-review"
    favorites = api.list_favorite_answers(manager, "renamed", 1, target=restored)["items"]
    assert [f["message_id"] for f in favorites] == [result["message"]["id"]]
