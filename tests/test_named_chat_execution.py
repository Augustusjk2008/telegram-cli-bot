"""Exercise named chat admission, cancellation and native resume through the normal turn pipeline."""

import asyncio
import json
import os
import shlex
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from bot import app_settings, config, session_store
from bot.manager import MultiBotManager
from bot.models import BotProfile, flush_pending_session_persistence
from bot.sessions import unload_bot_sessions
from bot.web import api_service as api
from bot.web.api_common import WebApiError
from bot.web.chat_targets import create_chat_session, list_chat_sessions, resolve_named_chat_target


def _install_cli(directory, name, cli_type):
    program = Path(__file__).parent / "fixtures" / "named_chat_cli.py"
    if os.name == "nt":
        path = directory / (name + ".cmd")
        path.write_text(f'@"{sys.executable}" -u "{program}" {cli_type} %*\n', encoding="utf-8")
    else:
        path = directory / name
        invocation = shlex.join([sys.executable, "-u", str(program), cli_type])
        path.write_text(f'#!/bin/sh\nexec {invocation} "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return path


def _isolate_providers(monkeypatch):
    monkeypatch.setattr(config, "CLI_TYPE", "codex")
    monkeypatch.setattr(config, "CLI_PATH", "codex")
    monkeypatch.setattr(api, "_start_codex_rate_limit_capture", AsyncMock(return_value=None))
    monkeypatch.setattr(api, "_start_claude_rate_limit_capture", AsyncMock(return_value=None))


@pytest.fixture
def chat_bot(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex = _install_cli(bin_dir, "custom-codex", "codex")
    # An accidental fallback from the pinned custom path must fail inside the fixture.
    _install_cli(bin_dir, "codex", "unexpected-default-codex")
    _install_cli(bin_dir, "claude", "claude")
    _install_cli(bin_dir, "agy", "antigravity")
    _install_cli(bin_dir, "dsh", "deepseek")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    _isolate_providers(monkeypatch)
    profile = BotProfile(alias="main", cli_type="codex", cli_path=str(codex), working_dir=str(tmp_path),
                         chat_translation_enabled=False)
    profile.cluster = replace(profile.cluster, enabled=True, max_parallel_agents=2)
    return MultiBotManager(profile, str(tmp_path / "bots.json"))


async def _send(manager, target, prompt, *, user_id=1, **kwargs):
    return [event async for event in api.stream_chat(manager, "main", user_id, prompt, target=target, **kwargs)]


def _create(manager, title, cli_type=None):
    if cli_type is None:
        item = create_chat_session(manager, "main", 1, title)
    else:
        item = create_chat_session(manager, "main", 1, title, cli_type=cli_type)
    return resolve_named_chat_target(manager, "main", 1, item["id"])


def _launch(tmp_path, prompt):
    return json.loads((tmp_path / f"{prompt}.json").read_text(encoding="utf-8"))


async def _resume_in_fresh_process(workspace):
    workspace = Path(workspace)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "home", staticmethod(lambda: workspace / "provider-home"))
        _isolate_providers(patch)
        patch.setattr(session_store, "STORE_FILE", workspace / ".session_store.json")
        patch.setattr(app_settings, "APP_SETTINGS_FILE", workspace / ".web_admin_settings.json")
        manager = MultiBotManager(BotProfile(alias="main"), str(workspace / "bots.json"))
        assert manager.main_profile.cli_type == "antigravity"
        catalog = list_chat_sessions(manager, "main", 1)
        for item in catalog["items"]:
            target = None if item["id"] == "main" else resolve_named_chat_target(manager, "main", 1, item["id"])
            title = item["title"] if target else "main"
            if title in {"codex", "claude"}:
                assert item["selected_cli_type"] == item["effective_cli_type"] == title
                history = api.get_history(manager, "main", 1, target=target)["items"]
                assert [m["content"] for m in history] == [title, title]
                prompt = "continue-" + title
            else:
                assert item["selected_cli_type"] is None
                assert item["effective_cli_type"] == "antigravity"
                prompt = title + "-80"
            result = await _send(manager, target, prompt)
            assert result[-1].get("output") == prompt, result[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "json"])
async def test_pinned_native_resumes_after_default_change_in_fresh_process(chat_bot, tmp_path, monkeypatch, backend):
    monkeypatch.setenv("SESSION_STORE_BACKEND", backend)
    monkeypatch.setenv("TCB_PORTABLE_ROOT", str(tmp_path / "test-install"))
    manager = chat_bot
    manager.main_profile.cluster = replace(manager.main_profile.cluster, enabled=False)
    _create(manager, "Legacy")
    native = {}
    for cli in ("codex", "claude"):
        chat = _create(manager, cli, cli)
        assert (await _send(manager, chat, cli))[-1]["output"] == cli
        native[cli] = getattr(chat.session, cli + "_session_id")
    await manager.set_bot_cli("main", "antigravity", "agy")
    flush_pending_session_persistence()
    session_store.close_session_store()
    env = {
        **os.environ,
        "TCB_ANTIGRAVITY_STATUSLINE_PATH": str(tmp_path / "telemetry" / "status.jsonl"),
    }
    child = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", "import asyncio, sys; from tests.test_named_chat_execution import "
         "_resume_in_fresh_process; asyncio.run(_resume_in_fresh_process(sys.argv[1]))", str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=25,
    )
    assert child.returncode == 0, child.stderr
    for cli, flag in (("codex", "resume"), ("claude", "-r")):
        launch = _launch(tmp_path, "continue-" + cli)
        assert launch["cli"] == cli
        assert launch["args"][launch["args"].index(flag) + 1] == native[cli]
    for prompt in ("main-80", "Legacy-80"):
        assert _launch(tmp_path, prompt)["cli"] == "antigravity"


async def _started(marker, task):
    async def wait_for_marker():
        while not marker.exists():
            if task.done():
                pytest.fail(f"CLI exited before startup: {task.result()}")
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait_for_marker(), 8)


@pytest.mark.asyncio
async def test_parallel_turns_stop_independently_and_resume_their_native_threads(chat_bot, tmp_path):
    manager = chat_bot
    a, b = _create(manager, "Implementation", "codex"), _create(manager, "Review", "claude")
    for target, text in ((a, "A"), (b, "B")):
        assert (await _send(manager, target, text))[-1]["output"] == text
    codex_id, claude_id = a.session.codex_session_id, b.session.claude_session_id
    assert codex_id and claude_id and codex_id != claude_id
    assert _launch(tmp_path, "A")["cli"] == "codex"
    assert _launch(tmp_path, "B")["cli"] == "claude"
    assert "--session-id" in _launch(tmp_path, "B")["args"]
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
        args = _launch(tmp_path, f"continue-{label}")["args"]
        flag, native = ("resume", codex_id) if label == "A" else ("-r", claude_id)
        assert args[args.index(flag) + 1] == native
    assert not api.get_history(manager, "main", 1)["items"]


@pytest.mark.asyncio
async def test_one_slot_is_shared_by_named_and_default_chat_and_released_after_stop(chat_bot, tmp_path):
    manager = chat_bot
    profile = manager.main_profile
    profile.cluster = replace(profile.cluster, enabled=False, max_parallel_agents=1)
    first, second = _create(manager, "A", "codex"), _create(manager, "B", "claude")
    active = asyncio.create_task(_send(manager, first, "hold-implementation"))
    try:
        await _started(tmp_path / "hold-implementation.started", active)
        with pytest.raises(WebApiError, match="Bot") as denied:
            await api.run_chat(manager, "main", 1, "no slot")
        assert denied.value.code == "bot_chat_capacity"
        assert (await _send(manager, second, "still full"))[-1]["code"] == "bot_chat_capacity"
        assert not api.get_history(manager, "main", 1, target=second)["items"]
        await api.kill_user_process(manager, "main", 1, target=first)
    finally:
        (tmp_path / "hold-implementation.finish").touch()
        await asyncio.wait_for(active, 10)
    assert (await api.run_chat(manager, "main", 1, "next", target=second))["output"] == "next"


@pytest.mark.asyncio
async def test_legacy_agent_reset_cannot_remove_a_loaded_named_chat(chat_bot):
    manager = chat_bot
    chat = _create(manager, "Keep history")
    await _send(manager, chat, "keep")
    with pytest.raises(WebApiError) as rejected:
        await api.reset_user_session(manager, "main", 1, agent_id=chat.session.storage_scope)
    assert rejected.value.code == "agent_not_found"
    assert api.get_history(manager, "main", 1, target=chat)["items"][-1]["content"] == "keep"


@pytest.mark.asyncio
async def test_workspace_move_and_named_session_creation_cannot_interleave(chat_bot, tmp_path, monkeypatch):
    manager = chat_bot
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
    manager = chat_bot
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
    manager = chat_bot
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


@pytest.mark.asyncio
async def test_pinned_claude_reads_current_model_and_requester_permissions(chat_bot, tmp_path, monkeypatch):
    manager = chat_bot
    manager.main_profile.cli_params.claude.update(yolo=True, model="first-model")
    chat = _create(manager, "Review", "claude")
    cost = AsyncMock()
    monkeypatch.setattr(api, "_record_turn_cost", cost)
    for prompt, allowed, model in (("privileged", True, "first-model"), ("restricted", False, "next-model")):
        if not allowed:
            await manager.set_bot_cli_param("main", "claude", "model", model)
        user_id = 1 if allowed else 2
        target = resolve_named_chat_target(manager, "main", user_id, chat.session.web_session_id)
        actor = {"username": prompt}
        done = (await _send(manager, target, prompt, user_id=user_id, allow_unsafe_cli=allowed, actor=actor))[-1]
        assert done["output"] == prompt
        args = _launch(tmp_path, prompt)["args"]
        assert args[args.index("--model") + 1] == model
        assert ("--dangerously-skip-permissions" in args) == allowed
        row = cost.await_args.kwargs
        assert (row["provider"], row["user"], row["native_session_id"]) == ("claude", prompt, chat.session.claude_session_id)


@pytest.mark.asyncio
async def test_missing_pinned_executable_preserves_history_without_fallback(chat_bot, tmp_path):
    manager = chat_bot
    manager.main_profile.cli_params.codex["extra_args"] = ["-c", 'private_fixture_setting="123"']
    chat = _create(manager, "Implementation", "codex")
    done = (await _send(manager, chat, "initial"))[-1]
    assert done["output"] == "initial"
    overview = api.get_overview(manager, "main", 1, target=chat)
    for private in ("custom-codex", "private_fixture_setting"):
        assert private not in json.dumps([overview, done])
    await manager.set_bot_cli("main", "claude", "claude")
    Path(chat.profile.cli_path).unlink()
    chat = resolve_named_chat_target(manager, "main", 1, chat.session.web_session_id)
    result = (await _send(manager, chat, "missing"))[-1]
    assert result["type"] == "error" and result["code"] == "chat_cli_unavailable"
    assert "custom-codex" not in json.dumps(result)
    assert not (tmp_path / "missing.json").exists()
    history = api.get_history(manager, "main", 1, target=chat)["items"]
    assert [m["content"] for m in history] == ["initial", "initial"]


@pytest.mark.asyncio
async def test_pinned_antigravity_reads_each_chats_own_statusline(chat_bot, tmp_path, monkeypatch):
    monkeypatch.setenv("TCB_ANTIGRAVITY_STATUSLINE_PATH", str(tmp_path / "usage.jsonl"))
    chats = [_create(chat_bot, f"Usage {percent}", "antigravity") for percent in (85, 33)]
    paths = []
    for chat, percent in zip(chats, (85, 33)):
        prompt = f"usage-{percent}"
        result = (await _send(chat_bot, chat, prompt))[-1]
        usage = result["message"]["meta"]["context_usage"]
        assert (usage["session_id"], usage["context_left_percent"]) == (f"agy-{prompt}", percent)
        paths.append(_launch(tmp_path, prompt)["telemetry"])
    assert paths[0] != paths[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_turn", [False, True], ids=["safe-turn", "unsafe-turn"])
async def test_pinned_app_server_steer_permissions_follow_the_running_turn(chat_bot, monkeypatch, unsafe_turn):
    from bot.codex_server import runtime
    from tests.test_codex_server_runtime import FakeClient

    class ManualClient(FakeClient):
        instances = []

        def __init__(self):
            super().__init__()
            self.auto_complete = False

    registry = runtime.CodexServerRegistry()
    monkeypatch.setattr(runtime, "CodexServerClient", ManualClient)
    monkeypatch.setattr(runtime, "get_codex_server_registry", lambda: registry)
    chat_bot.main_profile.cli_params.codex_server["yolo"] = unsafe_turn
    chat = _create(chat_bot, "Server", "codex_server")
    owner = (chat.session.bot_id, chat.session.user_id, chat.session.storage_scope)

    async def drive_turn():
        steered = False
        async for event in api.stream_chat(chat_bot, "main", 1, "work", target=chat, allow_unsafe_cli=True):
            if event.get("preview_text") and not steered:
                await chat_bot.set_bot_cli("main", "claude", "claude")
                # The next turn's settings must not change who can steer this one.
                await chat_bot.set_bot_cli_param("main", "codex_server", "yolo", not unsafe_turn)
                member = resolve_named_chat_target(chat_bot, "main", 2, chat.session.web_session_id)
                calls = ManualClient.instances[0].calls
                thread = next(params for method, params in calls if method == "thread/start")
                assert (thread.get("sandbox") == "danger-full-access") == unsafe_turn
                if unsafe_turn:
                    with pytest.raises(WebApiError) as denied:
                        await api.steer_chat(
                            chat_bot, "main", 2, "denied", target=member,
                            turn_id=event["turn_id"], allow_unsafe_cli=False,
                        )
                    assert (denied.value.status, denied.value.code) == (403, "unsafe_steering_forbidden")
                    assert all(method != "turn/steer" for method, _ in calls)
                writer = 1 if unsafe_turn else 2
                target = resolve_named_chat_target(chat_bot, "main", writer, chat.session.web_session_id)
                steer = await api.steer_chat(
                    chat_bot, "main", writer, "follow-up", target=target,
                    turn_id=event["turn_id"], allow_unsafe_cli=(writer == 1),
                )
                assert steer["user_message"]["content"] == "follow-up"
                assert registry._runtimes[owner].thread_id == ManualClient.instances[0].thread_id
                assert (await api.kill_user_process(chat_bot, "main", 2, target=member))["stop_requested"]
                steered = True
        assert steered
        assert event["message"]["meta"]["completion_state"] == "cancelled"

    try:
        await asyncio.wait_for(drive_turn(), 8)
        calls = ManualClient.instances[0].calls
        assert [method for method, _ in calls if method in {"turn/steer", "turn/interrupt"}] == [
            "turn/steer", "turn/interrupt",
        ]
        history = api.get_history(chat_bot, "main", 1, target=chat)["items"]
        assert [m["content"] for m in history if m["role"] == "user"] == ["work", "follow-up"]
        data = api.list_conversations(chat_bot, "main", 1, target=chat)["items"][0]
        assert (data["cli_type"], data["native_provider"]) == ("codex_server", "codex")
    finally:
        await registry.aclose()


@pytest.mark.asyncio
async def test_inherited_exec_and_app_server_keep_separate_conversations_and_native_bindings(chat_bot, monkeypatch):
    from bot.codex_server import runtime
    from tests.test_codex_server_runtime import FakeClient

    monkeypatch.setattr(FakeClient, "instances", [])
    monkeypatch.setattr(runtime, "CodexServerClient", FakeClient)
    registry = runtime.CodexServerRegistry()
    monkeypatch.setattr(runtime, "get_codex_server_registry", lambda: registry)
    chat = _create(chat_bot, "Inherited")
    assert (await _send(chat_bot, chat, "exec"))[-1]["output"] == "exec"
    saved = api.list_conversations(chat_bot, "main", 1, target=chat)["items"][0]
    assert (saved["cli_type"], saved["native_provider"]) == ("codex", "codex")
    await chat_bot.set_bot_cli("main", "codex_server", chat_bot.main_profile.cli_path)
    inherited = resolve_named_chat_target(chat_bot, "main", 1, chat.session.web_session_id)
    with pytest.raises(WebApiError) as rejected:
        await api.select_conversation(chat_bot, "main", 1, saved["id"], target=inherited)
    assert rejected.value.code == "conversation_cli_type_mismatch"
    try:
        done = (await _send(chat_bot, inherited, "server"))[-1]
        assert done["message"]["meta"]["completion_state"] == "completed"
        assert inherited.session.active_conversation_id != saved["id"]
        assert [method for method, _ in FakeClient.instances[0].calls if method.startswith("thread/")] == ["thread/start"]
        await chat_bot.set_bot_cli("main", "codex", chat_bot.main_profile.cli_path)
        restored = resolve_named_chat_target(chat_bot, "main", 1, chat.session.web_session_id)
        await api.select_conversation(chat_bot, "main", 1, saved["id"], target=restored)
        assert (await _send(chat_bot, restored, "resume-exec"))[-1]["output"] == "resume-exec"
        args = _launch(Path(chat.session.working_dir), "resume-exec")["args"]
        assert args[args.index("resume") + 1] == saved["native_session_id"]
    finally:
        await registry.aclose()


@pytest.mark.asyncio
async def test_pinned_deepseek_resumes_only_for_matching_provider(chat_bot, monkeypatch):
    from tests.test_cli_streaming import _DeepSeekProcess, _deepseek_events

    chat_bot.main_profile.cli_params.deepseek["provider"] = "account-a"
    chat = _create(chat_bot, "Harness", "deepseek")
    # Replace Harness model-patch discovery and its process only. Keep the real
    # command builder, turn pipeline and durable conversation selection.
    monkeypatch.setattr("bot.cli_params.build_deepseek_invocation", lambda path, params: [path])
    processes = [
        _DeepSeekProcess([{"type": "orbit_model", "provider": provider, "model": "deepseek-flash"},
                          *_deepseek_events(thread, text=prompt)])
        for provider, thread, prompt in [
            ("account-a", "thread-a", "first"), ("account-a", "thread-a", "resume"),
            ("account-b", "thread-b", "switch"), ("account-b", "thread-b", "again"),
        ]
    ]
    spawn = Mock(side_effect=processes)
    monkeypatch.setattr(api.subprocess, "Popen", spawn)
    for prompt, expected in [("first", None), ("resume", "thread-a"), ("switch", None), ("again", "thread-b")]:
        if prompt == "switch":
            await chat_bot.set_bot_cli_param("main", "deepseek", "provider", "account-b")
        target = resolve_named_chat_target(chat_bot, "main", 1, chat.session.web_session_id)
        done = (await _send(chat_bot, target, prompt))[-1]
        assert done["output"] == prompt
        argv = spawn.call_args.args[0]
        actual = argv[argv.index("--session-id") + 1] if "--session-id" in argv else None
        assert actual == expected
