"""Web API 相关测试。"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import subprocess
import threading
import time
import zipfile
import zlib
from datetime import datetime, timedelta
from itertools import chain, repeat
from pathlib import Path
from typing import cast
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer
from aiohttp.client_exceptions import ClientConnectionResetError, WSServerHandshakeError

import bot.runtime_paths as runtime_paths
from bot.assistant.context import AssistantPromptPayload
from bot.assistant.cron.service import AssistantCronService
from bot.assistant.cron.store import load_job_runtime_state, read_job_run_audit, save_job_runtime_state
from bot.assistant.cron.types import AssistantCronJob, AssistantCronJobState
from bot.assistant.dream.service import AssistantDreamPreparedPrompt, AssistantDreamApplyResult
from bot.assistant.dream.managed_context import ManagedBotDreamContext
from bot.assistant.docs import ManagedPromptSyncResult
from bot.assistant.home import bootstrap_assistant_home
from bot.assistant.runtime import AssistantRunRequest
from bot.assistant.state import save_assistant_runtime_state
from bot.chat_identity import chat_session_user_id
from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import AgentProfile, BotProfile, UserSession
from bot.plugins.service import PluginService
from bot.session_store import load_session, save_session
from bot.web.auth_store import WebAuthStore
from bot.web.server import WebApiServer
from bot.web.api_service import (
    AuthContext,
    _stream_cli_chat,
    _build_stream_status_event,
    _extract_codex_stream_preview,
    stream_assistant_run_request,
    WebApiError,
    build_bot_summary,
    build_session_snapshot,
    change_working_directory,
    create_agent,
    create_conversation,
    delete_all_conversations,
    delete_conversation,
    delete_agent,
    get_directory_listing,
    get_chat_session_for_alias,
    get_history,
    get_history_trace,
    get_cluster_status,
    get_session_for_alias,
    get_overview,
    get_processing_sessions,
    resolve_session_bot_id,
    get_working_directory,
    kill_user_process,
    list_conversations,
    list_agents,
    list_bots,
    execute_shell_command,
    copy_path,
    create_text_file,
    delete_chat_attachment,
    execute_assistant_run_request,
    read_file_content,
    move_path,
    rename_path,
    run_chat,
    run_cli_chat,
    save_chat_attachment,
    save_uploaded_file,
    select_conversation,
    update_agent,
    update_bot_workdir,
    write_file_content,
)
from bot.app_settings import get_git_proxy_settings, update_git_proxy_address, update_git_proxy_port
from bot.web import api_service
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore
from bot.web.git_service import (
    GIT_COMMIT_MESSAGE_TIMEOUT_SECONDS,
    GIT_SMART_COMMIT_UNTRACKED_PREVIEW_LIMIT,
    _read_untracked_file_preview,
    apply_git_stash,
    commit_git_changes,
    create_git_branch,
    discard_all_git_changes,
    discard_git_paths,
    drop_git_stash,
    generate_git_commit_message,
    get_git_blame,
    get_git_commit_graph,
    get_git_commit_message_cli_config,
    get_git_diff,
    get_git_identity_config,
    get_git_overview,
    get_git_tree_status,
    init_git_repository,
    list_git_branches,
    list_git_stashes,
    reset_git_commit_message_cli_config,
    reset_git_branch_to_commit,
    stage_git_paths,
    switch_git_branch,
    update_git_commit_message_cli_config,
    update_git_identity_config,
)
from bot.web.git_commit_message import (
    build_commit_message_prompt,
    extract_commit_message,
)
from bot.web.native_history_locator import LocatedTranscript
from bot.assistant.proposals import create_proposal


def _png_bytes(width: int, height: int) -> bytes:
    row = b"\x00" + (b"\x00\x00\x00" * width)
    raw = row * height
    compressed = zlib.compress(raw)

    def chunk(tag: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", checksum)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )

@pytest.fixture
def web_manager(temp_dir: Path) -> MultiBotManager:
    storage_file = temp_dir / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(temp_dir),
        enabled=True,
    )
    return MultiBotManager(main_profile=profile, storage_file=str(storage_file))


@pytest.fixture
def isolated_web_auth_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebAuthStore:
    store = WebAuthStore(
        users_path=tmp_path / ".web_users.json",
        register_codes_path=tmp_path / ".web_register_codes.json",
        secret_path=tmp_path / ".web_auth_secret.json",
    )
    monkeypatch.setattr("bot.web.server._WEB_AUTH_STORE", store)
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    return store


@pytest.fixture(autouse=True)
def default_web_auth_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebAuthStore:
    store = WebAuthStore(
        users_path=tmp_path / ".web_users.default.json",
        register_codes_path=tmp_path / ".web_register_codes.default.json",
        secret_path=tmp_path / ".web_auth_secret.default.json",
    )
    monkeypatch.setattr("bot.web.server._WEB_AUTH_STORE", store)
    return store


def _seed_chat_turn(
    web_manager: MultiBotManager,
    workspace: Path,
    *,
    user_text: str,
    assistant_text: str,
    user_id: int = 1001,
    context_usage: dict[str, Any] | None = None,
) -> None:
    web_manager.main_profile.working_dir = str(workspace)
    session = get_session_for_alias(web_manager, "main", user_id)
    session.working_dir = str(workspace)
    session.session_epoch = 1
    service = ChatHistoryService(ChatStore(workspace))
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text=user_text,
        native_provider=web_manager.main_profile.cli_type,
    )
    service.complete_turn(handle, content=assistant_text, completion_state="completed", context_usage=context_usage)

@pytest.mark.asyncio
async def test_stream_chat_cluster_requires_enabled_cluster(web_manager: MultiBotManager):
    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post(
                "/api/bots/main/chat/stream",
                json={"message": "@reviewer 看一下", "cluster": True, "mentions": [{"agent_id": "reviewer"}]},
            )
            text = await resp.text()

    assert resp.status == 200
    assert "cluster_not_enabled" in text


@pytest.mark.asyncio
async def test_run_chat_cluster_finishes_runtime_run(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True)
    captured = {}

    async def fake_run_cli_chat(_manager, _alias, _user_id, _text, *, cluster_run_id="", **_kwargs):
        captured["run_id"] = cluster_run_id
        assert api_service._CLUSTER_RUNTIME.get_run(cluster_run_id) is not None
        return {"output": "ok"}

    monkeypatch.setattr(api_service, "run_cli_chat", fake_run_cli_chat)

    result = await api_service.run_chat(web_manager, "main", 1001, "hi", cluster=True)

    assert result["output"] == "ok"
    run = api_service._CLUSTER_RUNTIME.get_run(captured["run_id"])
    assert run is not None
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_cluster_ask_agent_returns_task_without_waiting(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True, max_parallel_agents=2)
    await web_manager.create_bot_agent("main", {"id": "tester", "name": "测试专家"})
    run = api_service._CLUSTER_RUNTIME.start_run(
        api_service.ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile)
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_stream_cli_chat(*_args, **_kwargs):
        started.set()
        await release.wait()
        yield {"type": "done", "output": "done", "returncode": 0}

    monkeypatch.setattr(api_service, "_stream_cli_chat", fake_stream_cli_chat)

    result = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "ask_agent",
        {"agent_id": "tester", "message": "跑测试"},
    )

    assert result["ok"] is True
    task_id = result["data"]["task_id"]
    assert result["data"]["status"] == "queued"
    await asyncio.wait_for(started.wait(), timeout=1)

    poll = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "poll_agent_tasks",
        {"task_ids": [task_id]},
    )
    assert poll["data"]["running_count"] == 1

    release.set()
    await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "poll_agent_tasks",
        {"task_ids": [task_id], "wait_seconds": 1, "include_output": True},
    )


@pytest.mark.asyncio
async def test_cluster_mcp_tools_report_effective_agent_timeout(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True, default_timeout_seconds=900, max_parallel_agents=2)
    await web_manager.create_bot_agent(
        "main",
        {
            "id": "tester",
            "name": "测试专家",
            "cluster": {"session_policy": "ephemeral", "timeout_seconds": 180},
        },
    )
    run = api_service._CLUSTER_RUNTIME.start_run(
        api_service.ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile)
    )

    async def fake_stream_cli_chat(*_args, **_kwargs):
        yield {"type": "done", "output": "done", "returncode": 0}

    monkeypatch.setattr(api_service, "_stream_cli_chat", fake_stream_cli_chat)

    result = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "ask_agent",
        {"agent_id": "tester", "message": "跑测试"},
    )
    task_id = result["data"]["task_id"]

    assert result["data"]["timeout_seconds"] == 180
    poll = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "poll_agent_tasks",
        {"task_ids": [task_id], "wait_seconds": 1, "include_output": True},
    )
    assert poll["data"]["tasks"][0]["timeout_seconds"] == 180

    explicit = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "ask_agent",
        {"agent_id": "tester", "message": "跑测试", "timeout_seconds": 240},
    )
    explicit_task_id = explicit["data"]["task_id"]
    assert explicit["data"]["timeout_seconds"] == 240
    explicit_poll = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "poll_agent_tasks",
        {"task_ids": [explicit_task_id], "wait_seconds": 1, "include_output": True},
    )
    assert explicit_poll["data"]["tasks"][0]["timeout_seconds"] == 240

    status = await api_service.handle_cluster_mcp_tool(web_manager, run.run_id, "cluster_status", {})
    listed = await api_service.handle_cluster_mcp_tool(web_manager, run.run_id, "list_agents", {})
    web_status = get_cluster_status(web_manager, "main")
    status_agent = status["data"]["agents"][0]
    listed_agent = listed["data"][0]
    web_status_agent = web_status["agents"][0]
    assert status_agent["session_policy"] == "ephemeral"
    assert status_agent["timeout_seconds"] == 180
    assert listed_agent["session_policy"] == "ephemeral"
    assert listed_agent["timeout_seconds"] == 180
    assert web_status_agent["session_policy"] == "ephemeral"
    assert web_status_agent["timeout_seconds"] == 180


@pytest.mark.asyncio
async def test_cluster_poll_agent_tasks_can_wait_for_completion(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True, max_parallel_agents=1)
    await web_manager.create_bot_agent("main", {"id": "tester", "name": "测试专家"})
    run = api_service._CLUSTER_RUNTIME.start_run(
        api_service.ClusterRunRequest(bot_alias="main", user_id=1001, profile=profile)
    )

    async def fake_stream_cli_chat(*_args, **_kwargs):
        await asyncio.sleep(0.05)
        yield {"type": "done", "output": "done", "returncode": 0}

    monkeypatch.setattr(api_service, "_stream_cli_chat", fake_stream_cli_chat)
    result = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "ask_agent",
        {"agent_id": "tester", "message": "跑测试"},
    )
    task_id = result["data"]["task_id"]

    poll = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "poll_agent_tasks",
        {"task_ids": [task_id], "wait_seconds": 1, "include_output": True},
    )

    assert poll["data"]["pending_count"] == 0
    assert poll["data"]["tasks"][0]["status"] == "completed"
    assert poll["data"]["tasks"][0]["output"] == "done"


def test_overview_and_directory_listing(web_manager: MultiBotManager, temp_dir: Path):
    subdir = temp_dir / "workspace"
    subdir.mkdir()
    (subdir / "hello.txt").write_text("hello", encoding="utf-8")

    change_working_directory(web_manager, "main", 1001, str(subdir))
    overview = get_overview(web_manager, "main", 1001)
    assert overview["session"]["working_dir"] == str(temp_dir)

    listing = get_directory_listing(web_manager, "main", 1001)
    assert listing["working_dir"] == str(subdir)
    assert any(item["name"] == "hello.txt" for item in listing["entries"])

class _FakeAssistantRuntimeCoordinator:
    def __init__(self) -> None:
        self.requests = []

    async def submit_background(self, request):
        self.requests.append(request)
        return {"run_id": request.run_id, "status": "queued"}

    async def wait_for_run(self, run_id: str):
        return {"run_id": run_id, "elapsed_seconds": 0}

class _FailingAssistantRuntimeCoordinator(_FakeAssistantRuntimeCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def wait_for_run(self, run_id: str):
        await self.release.wait()
        raise RuntimeError("dream 结果处理失败")

def _build_assistant_cron_job(job_id: str, prompt: str) -> AssistantCronJob:
    return AssistantCronJob.from_dict(
        {
            "id": job_id,
            "enabled": True,
            "title": "测试任务",
            "schedule": {
                "type": "interval",
                "every_seconds": 300,
                "timezone": "Asia/Shanghai",
                "misfire_policy": "skip",
            },
            "task": {"prompt": prompt},
            "execution": {"timeout_seconds": 600},
        }
    )

def _build_dream_assistant_cron_job(job_id: str, prompt: str) -> AssistantCronJob:
    return AssistantCronJob.from_dict(
        {
            "id": job_id,
            "enabled": True,
            "title": "Dream 任务",
            "schedule": {
                "type": "interval",
                "every_seconds": 600,
                "timezone": "Asia/Shanghai",
                "misfire_policy": "skip",
            },
            "task": {
                "prompt": prompt,
                "mode": "dream",
                "lookback_hours": 24,
                "history_limit": 40,
                "capture_limit": 20,
                "deliver_mode": "silent",
            },
            "execution": {"timeout_seconds": 600},
        }
    )

def test_read_file_content_rejects_absolute_path_outside_browser_dir(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    outside_dir = temp_dir / "outside"
    outside_dir.mkdir()
    target = outside_dir / "notes.txt"
    target.write_text("outside\n", encoding="utf-8")

    change_working_directory(web_manager, "main", 1001, str(workspace))

    with pytest.raises(WebApiError) as exc_info:
        read_file_content(web_manager, "main", 1001, str(target), mode="cat", lines=0)

    assert exc_info.value.code == "unsafe_path"

def test_write_file_content_updates_text_and_returns_version(web_manager: MultiBotManager, temp_dir: Path):
    save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"line1\n")
    previous = read_file_content(web_manager, "main", 1001, "notes.txt", mode="cat", lines=0)

    result = write_file_content(
        web_manager,
        "main",
        1001,
        "notes.txt",
        "line1\nline2\n",
        expected_mtime_ns=previous["last_modified_ns"],
    )

    content = read_file_content(web_manager, "main", 1001, "notes.txt", mode="cat", lines=0)

    assert result["path"] == "notes.txt"
    assert result["file_size_bytes"] == len("line1\nline2\n".encode("utf-8"))
    assert isinstance(result["last_modified_ns"], int)
    assert result["last_modified_ns"] >= previous["last_modified_ns"]
    assert content["content"] == "line1\nline2\n"
    assert content["last_modified_ns"] == result["last_modified_ns"]

def _run_git_command(repo_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

def _init_git_repo(repo_dir: Path):
    _run_git_command(repo_dir, "init")
    _run_git_command(repo_dir, "config", "user.name", "Web Bot Test")
    _run_git_command(repo_dir, "config", "user.email", "web-bot@example.com")


def _commit_repo_file(repo_dir: Path, filename: str, content: str, message: str) -> str:
    target = repo_dir / filename
    target.write_text(content, encoding="utf-8")
    _run_git_command(repo_dir, "add", filename)
    _run_git_command(repo_dir, "commit", "-m", message)
    return _run_git_command(repo_dir, "rev-parse", "HEAD").stdout.strip()


def _use_repo(web_manager: MultiBotManager, repo_dir: Path) -> None:
    web_manager.main_profile.working_dir = str(repo_dir)
    change_working_directory(web_manager, "main", 1001, str(repo_dir))


def _current_git_branch(repo_dir: Path) -> str:
    return _run_git_command(repo_dir, "branch", "--show-current").stdout.strip()


@pytest.mark.asyncio
async def test_auth_route_requires_token(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/auth/me")
            assert resp.status == 401

            resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer secret"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["user_id"] == 1001

@pytest.mark.asyncio
async def test_bot_overview_route(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots/main")
            assert resp.status == 200
            payload = await resp.json()
    assert payload["data"]["bot"]["alias"] == "main"
    assert payload["data"]["session"]["working_dir"] == web_manager.main_profile.working_dir

@pytest.mark.asyncio
async def test_web_api_lists_plugins_and_resolves_vcd_handler(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    repo_root = temp_dir / "repo"
    repo_root.mkdir()
    plugins_root = temp_dir / "home" / ".tcb" / "plugins"
    plugin_dir = plugins_root / "vivado-waveform"
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text(
        """
import json
import sys
from pathlib import Path

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    params = request.get("params") or {}
    if method == "plugin.initialize":
        result = {"ok": True}
    elif method == "plugin.open_view":
        path = Path(params["input"]["path"]).resolve()
        result = {
            "renderer": "waveform",
            "title": path.name,
            "mode": "session",
            "sessionId": "session-1",
            "summary": {
                "path": str(path),
                "timescale": "1ns",
                "startTime": 0,
                "endTime": 120,
                "signals": [{"signalId": "tb.clk", "label": "tb.clk", "width": 1, "kind": "scalar"}],
                "defaultSignalIds": ["tb.clk"],
                "padding": "x" * 40000,
            },
            "initialWindow": {"startTime": 0, "endTime": 40, "tracks": []},
        }
    elif method == "plugin.get_view_window":
        result = {
            "startTime": params["startTime"],
            "endTime": params["endTime"],
            "tracks": [{"signalId": "tb.clk", "label": "tb.clk", "width": 1, "segments": [{"start": 0, "end": 20, "value": "0"}]}],
        }
    elif method == "plugin.dispose_view":
        result = {"disposed": True}
    elif method == "plugin.render_view":
        path = Path(params["input"]["path"]).resolve()
        result = {
            "renderer": "waveform",
            "title": path.name,
            "payload": {
                "path": str(path),
                "timescale": "1ns",
                "startTime": 0,
                "endTime": 10,
                "tracks": [],
            },
        }
    else:
        result = {"ok": True}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\\n")
    sys.stdout.flush()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "vivado-waveform",
                "name": "Vivado Waveform",
                "version": "0.1.0",
                "description": "wave plugin",
                "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
                "views": [{"id": "waveform", "title": "波形预览", "renderer": "waveform", "viewMode": "session", "dataProfile": "heavy"}],
                "fileHandlers": [{"id": "wave-vcd", "label": "VCD 波形预览", "extensions": [".vcd"], "viewId": "waveform"}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    wave_dir = repo_root / "waves"
    wave_dir.mkdir()
    wave_file = wave_dir / "demo.vcd"
    wave_file.write_text("$timescale 1ns $end\n", encoding="utf-8")

    web_manager.plugin_service = PluginService(repo_root, plugins_root=plugins_root)
    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            plugins_response = await client.get("/api/plugins")
            plugins_payload = await plugins_response.json()
            assert plugins_payload["ok"] is True
            assert plugins_payload["data"][0]["id"] == "vivado-waveform"

            fresh_plugin_dir = plugins_root / "fresh-plugin"
            fresh_plugin_dir.mkdir()
            (fresh_plugin_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "id": "fresh-plugin",
                        "name": "Fresh Plugin",
                        "version": "0.1.0",
                        "description": "fresh plugin",
                        "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
                        "views": [],
                        "fileHandlers": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            cached_plugins_response = await client.get("/api/plugins")
            cached_plugins_payload = await cached_plugins_response.json()
            assert {item["id"] for item in cached_plugins_payload["data"]} == {"vivado-waveform"}

            refreshed_plugins_response = await client.get("/api/plugins?refresh=1")
            refreshed_plugins_payload = await refreshed_plugins_response.json()
            assert {item["id"] for item in refreshed_plugins_payload["data"]} == {
                "fresh-plugin",
                "vivado-waveform",
            }

            resolve_response = await client.post(
                "/api/bots/main/plugins/resolve-file-target",
                json={"path": "waves/demo.vcd"},
            )
            resolve_payload = await resolve_response.json()
            assert resolve_payload["data"]["kind"] == "plugin_view"

            open_response = await client.post(
                "/api/bots/main/plugins/vivado-waveform/views/waveform/open",
                json={"input": {"path": "waves/demo.vcd"}},
                headers={"Accept-Encoding": "gzip"},
            )
            open_payload = await open_response.json()
            assert open_payload["data"]["renderer"] == "waveform"
            assert open_payload["data"]["mode"] == "session"
            assert open_payload["data"]["summary"]["path"] == str(wave_file.resolve())
            assert open_response.headers.get("Content-Encoding") == "gzip"

            window_response = await client.post(
                "/api/bots/main/plugins/vivado-waveform/sessions/session-1/window",
                json={"startTime": 0, "endTime": 20, "signalIds": ["tb.clk"], "pixelWidth": 800},
            )
            window_payload = await window_response.json()
            assert window_payload["data"]["tracks"][0]["signalId"] == "tb.clk"

            dispose_response = await client.delete("/api/bots/main/plugins/vivado-waveform/sessions/session-1")
            dispose_payload = await dispose_response.json()
            assert dispose_payload["data"]["disposed"] is True

            patch_response = await client.patch(
                "/api/plugins/vivado-waveform",
                json={"enabled": False, "config": {"lodEnabled": False}},
            )
            patch_payload = await patch_response.json()
            assert patch_payload["ok"] is True
            assert patch_payload["data"]["enabled"] is False
            assert patch_payload["data"]["config"]["lodEnabled"] is False
            saved_manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
            assert saved_manifest["enabled"] is False
            assert saved_manifest["config"]["lodEnabled"] is False

            disabled_resolve_response = await client.post(
                "/api/bots/main/plugins/resolve-file-target",
                json={"path": "waves/demo.vcd"},
            )
            disabled_resolve_payload = await disabled_resolve_response.json()
            assert disabled_resolve_payload["data"] == {"kind": "file"}

    await web_manager.plugin_service.shutdown()


@pytest.mark.asyncio
async def test_web_api_lists_installable_plugins_and_installs_plugin(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    repo_root = temp_dir / "repo"
    repo_root.mkdir()
    plugins_root = temp_dir / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    source_plugins_root = repo_root / "examples" / "plugins"
    source_plugin_dir = source_plugins_root / "fresh-plugin"
    source_backend_dir = source_plugin_dir / "backend"
    source_backend_dir.mkdir(parents=True)
    (source_backend_dir / "main.py").write_text("print('plugin')\n", encoding="utf-8")
    (source_plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "fresh-plugin",
                "name": "Fresh Plugin",
                "version": "0.1.0",
                "description": "fresh plugin",
                "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
                "views": [],
                "fileHandlers": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    web_manager.plugin_service = PluginService(repo_root, plugins_root=plugins_root)
    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            installable_response = await client.get("/api/plugins/installable")
            installable_payload = await installable_response.json()
            assert installable_payload["ok"] is True
            assert installable_payload["data"] == [
                {
                    "id": "fresh-plugin",
                    "pluginId": "fresh-plugin",
                    "name": "Fresh Plugin",
                    "version": "0.1.0",
                    "description": "fresh plugin",
                    "installed": False,
                }
            ]

            source_path_response = await client.post("/api/plugins/install", json={"sourcePath": str(source_plugin_dir)})
            source_path_payload = await source_path_response.json()
            assert source_path_response.status == 403
            assert source_path_payload["error"]["code"] == "plugin_source_path_forbidden"

            install_response = await client.post("/api/plugins/install", json={"pluginId": "fresh-plugin"})
            install_payload = await install_response.json()
            assert install_payload["ok"] is True
            assert install_payload["data"]["id"] == "fresh-plugin"
            assert (plugins_root / "fresh-plugin" / "plugin.json").exists()

            plugins_response = await client.get("/api/plugins")
            plugins_payload = await plugins_response.json()
            assert {item["id"] for item in plugins_payload["data"]} == {"fresh-plugin"}

    await web_manager.plugin_service.shutdown()


@pytest.mark.asyncio
async def test_git_tree_status_route_returns_decoration_payload(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    tracked = repo_dir / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", ".")
    _run_git_command(repo_dir, "commit", "-m", "init")

    tracked.write_text("after\n", encoding="utf-8")
    (repo_dir / "scratch.tmp").write_text("ignore me\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(repo_dir)
    change_working_directory(web_manager, "main", 1001, str(repo_dir))

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots/main/git/tree-status")
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["repo_found"] is True
    assert payload["data"]["repo_path"] == str(repo_dir)
    assert payload["data"]["items"] == {
        "tracked.txt": "modified",
        "scratch.tmp": "ignored",
    }


def test_git_commit_graph_linear_history_returns_parents_and_lanes(
    web_manager: MultiBotManager,
    temp_dir: Path,
):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    second_sha = _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    _use_repo(web_manager, repo_dir)

    result = get_git_commit_graph(web_manager, "main", 1001, scope="current")

    assert result["repo_found"] is True
    assert result["scope"] == "current"
    assert result["has_more"] is False
    assert [node["hash"] for node in result["nodes"]] == [second_sha, first_sha]
    assert result["nodes"][0]["parents"] == [first_sha]
    assert result["nodes"][0]["short_hash"] == second_sha[:7]
    assert result["nodes"][0]["author_name"] == "Web Bot Test"
    assert result["nodes"][0]["subject"] == "second"
    assert result["nodes"][0]["graph"]["column"] == 0
    assert result["nodes"][0]["graph"]["width"] >= 1
    assert result["nodes"][1]["parents"] == []


def test_git_commit_graph_merge_history_and_refs(
    web_manager: MultiBotManager,
    temp_dir: Path,
):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    base_sha = _commit_repo_file(repo_dir, "base.txt", "base\n", "base")
    current_branch = _current_git_branch(repo_dir)
    _run_git_command(repo_dir, "tag", "-a", "v-base", base_sha, "-m", "v-base")
    _run_git_command(repo_dir, "switch", "-c", "feature")
    feature_sha = _commit_repo_file(repo_dir, "feature.txt", "feature\n", "feature")
    _run_git_command(repo_dir, "update-ref", "refs/remotes/origin/feature", feature_sha)
    _run_git_command(repo_dir, "switch", current_branch)
    main_sha = _commit_repo_file(repo_dir, "main.txt", "main\n", "main")
    _run_git_command(repo_dir, "tag", "v-main", main_sha)
    _run_git_command(repo_dir, "merge", "--no-ff", "feature", "-m", "merge feature")
    merge_sha = _run_git_command(repo_dir, "rev-parse", "HEAD").stdout.strip()
    _use_repo(web_manager, repo_dir)

    result = get_git_commit_graph(web_manager, "main", 1001, scope="all")
    nodes_by_hash = {node["hash"]: node for node in result["nodes"]}
    merge_node = nodes_by_hash[merge_sha]

    assert set(merge_node["parents"]) == {main_sha, feature_sha}
    assert len(merge_node["graph"]["edges"]) == 2
    assert merge_node["graph"]["width"] >= 2

    def has_ref(commit: str, name: str, kind: str, current: bool | None = None) -> bool:
        for ref in nodes_by_hash[commit]["refs"]:
            if ref["name"] == name and ref["kind"] == kind and (current is None or ref["current"] is current):
                return True
        return False

    assert has_ref(merge_sha, "HEAD", "head", True)
    assert has_ref(merge_sha, current_branch, "local_branch", True)
    assert has_ref(feature_sha, "feature", "local_branch", False)
    assert has_ref(feature_sha, "origin/feature", "remote_branch", False)
    assert has_ref(main_sha, "v-main", "tag", False)
    assert has_ref(base_sha, "v-base", "tag", False)


def test_git_commit_graph_scope_filters_current_branch(
    web_manager: MultiBotManager,
    temp_dir: Path,
):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    base_sha = _commit_repo_file(repo_dir, "base.txt", "base\n", "base")
    current_branch = _current_git_branch(repo_dir)
    _run_git_command(repo_dir, "switch", "-c", "side", base_sha)
    side_sha = _commit_repo_file(repo_dir, "side.txt", "side\n", "side")
    _run_git_command(repo_dir, "switch", current_branch)
    main_sha = _commit_repo_file(repo_dir, "main.txt", "main\n", "main")
    _use_repo(web_manager, repo_dir)

    current_graph = get_git_commit_graph(web_manager, "main", 1001, scope="current")
    all_graph = get_git_commit_graph(web_manager, "main", 1001, scope="all")

    current_hashes = {node["hash"] for node in current_graph["nodes"]}
    all_hashes = {node["hash"] for node in all_graph["nodes"]}
    assert {main_sha, base_sha}.issubset(current_hashes)
    assert side_sha not in current_hashes
    assert {main_sha, side_sha, base_sha}.issubset(all_hashes)


@pytest.mark.asyncio
async def test_git_commit_graph_route_paginates_and_validates(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    second_sha = _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    third_sha = _commit_repo_file(repo_dir, "tracked.txt", "three\n", "third")
    _use_repo(web_manager, repo_dir)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            first_resp = await client.get("/api/bots/main/git/graph?scope=current&limit=2")
            first_payload = await first_resp.json()
            second_resp = await client.get(
                "/api/bots/main/git/graph",
                params={"scope": "current", "limit": "2", "cursor": first_payload["data"]["next_cursor"]},
            )
            second_payload = await second_resp.json()
            bad_limit_resp = await client.get("/api/bots/main/git/graph?limit=301")
            bad_limit_payload = await bad_limit_resp.json()
            bad_cursor_resp = await client.get("/api/bots/main/git/graph?cursor=not-base64")
            bad_cursor_payload = await bad_cursor_resp.json()

    assert first_resp.status == 200
    assert first_payload["data"]["has_more"] is True
    assert first_payload["data"]["next_cursor"]
    assert [node["hash"] for node in first_payload["data"]["nodes"]] == [third_sha, second_sha]
    assert second_resp.status == 200
    assert second_payload["data"]["has_more"] is False
    assert second_payload["data"]["next_cursor"] == ""
    assert [node["hash"] for node in second_payload["data"]["nodes"]] == [first_sha]
    assert bad_limit_resp.status == 400
    assert bad_limit_payload["error"]["code"] == "invalid_limit"
    assert bad_cursor_resp.status == 400
    assert bad_cursor_payload["error"]["code"] == "invalid_cursor"


@pytest.mark.asyncio
async def test_git_commit_graph_route_returns_not_git_repo(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    _use_repo(web_manager, temp_dir)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots/main/git/graph")
            payload = await resp.json()

    assert resp.status == 409
    assert payload["error"]["code"] == "not_git_repo"


def test_git_overview_recent_commits_remains_latest_eight(
    web_manager: MultiBotManager,
    temp_dir: Path,
):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    commits = [
        _commit_repo_file(repo_dir, "tracked.txt", f"{index}\n", f"commit {index}")
        for index in range(10)
    ]
    _use_repo(web_manager, repo_dir)

    overview = get_git_overview(web_manager, "main", 1001)

    assert [item["hash"] for item in overview["recent_commits"]] == list(reversed(commits[-8:]))


def test_create_git_branch_from_full_sha(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    _use_repo(web_manager, repo_dir)

    result = create_git_branch(web_manager, "main", 1001, "from-first", first_sha)

    created = next(item for item in result["branches"] if item["name"] == "from-first")
    assert created["short_hash"] == first_sha[:7]
    assert created["subject"] == "first"


def test_create_git_branch_from_short_sha(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    _use_repo(web_manager, repo_dir)

    result = create_git_branch(web_manager, "main", 1001, "from-short", first_sha[:7])

    created = next(item for item in result["branches"] if item["name"] == "from-short")
    assert created["short_hash"] == first_sha[:7]


def test_create_git_branch_from_invalid_commit_returns_code(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _use_repo(web_manager, repo_dir)

    with pytest.raises(WebApiError) as exc_info:
        create_git_branch(web_manager, "main", 1001, "bad-start", "not-a-sha")

    assert exc_info.value.code == "invalid_git_commit"


def test_reset_git_branch_to_ancestor_commit(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    _use_repo(web_manager, repo_dir)

    result = reset_git_branch_to_commit(web_manager, "main", 1001, first_sha, "mixed")

    head = _run_git_command(repo_dir, "rev-parse", "HEAD").stdout.strip()
    assert head == first_sha
    assert result["head_commit"] == first_sha
    assert result["current_branch"] in {"main", "master"}
    assert result["overview"]["recent_commits"][0]["hash"] == first_sha


def test_reset_git_branch_rejects_dirty_worktree(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    (repo_dir / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    _use_repo(web_manager, repo_dir)

    with pytest.raises(WebApiError) as exc_info:
        reset_git_branch_to_commit(web_manager, "main", 1001, first_sha, "mixed")

    assert exc_info.value.code == "git_dirty_worktree"


def test_reset_git_branch_rejects_detached_head(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    _run_git_command(repo_dir, "checkout", first_sha)
    _use_repo(web_manager, repo_dir)

    with pytest.raises(WebApiError) as exc_info:
        reset_git_branch_to_commit(web_manager, "main", 1001, first_sha, "mixed")

    assert exc_info.value.code == "git_detached_head"


def test_reset_git_branch_rejects_non_ancestor_commit(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _run_git_command(repo_dir, "switch", "-c", "other")
    other_sha = _commit_repo_file(repo_dir, "other.txt", "other\n", "other")
    _run_git_command(repo_dir, "switch", "-")
    _use_repo(web_manager, repo_dir)

    with pytest.raises(WebApiError) as exc_info:
        reset_git_branch_to_commit(web_manager, "main", 1001, other_sha, "mixed")

    assert exc_info.value.code == "git_commit_not_ancestor"


@pytest.mark.asyncio
async def test_history_delta_route_returns_items_after_last_id(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    workspace.mkdir()
    _seed_chat_turn(web_manager, workspace, user_text="第一问", assistant_text="第一答", user_id=1001)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            history_resp = await client.get("/api/bots/main/history?limit=10")
            assert history_resp.status == 200
            history_payload = await history_resp.json()
            last_id = history_payload["data"]["items"][-1]["id"]

            _seed_chat_turn(web_manager, workspace, user_text="第二问", assistant_text="增量回复", user_id=1001)

            delta_resp = await client.get(f"/api/bots/main/history/delta?after_id={last_id}&limit=10")
            assert delta_resp.status == 200
            delta_payload = await delta_resp.json()

    assert delta_payload["data"]["reset"] is False
    assert [item["content"] for item in delta_payload["data"]["items"]] == ["第二问", "增量回复"]


@pytest.mark.asyncio
async def test_ungranted_bot_file_read_write_and_terminal_rebuild_are_forbidden(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    from bot.web.permission_store import BotPermissionStore

    web_manager.managed_profiles["sub1"] = BotProfile(
        alias="sub1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(temp_dir),
        enabled=True,
    )
    (temp_dir / "notes.md").write_text("# hello\n", encoding="utf-8")
    change_working_directory(web_manager, "sub1", 1001, str(temp_dir))

    permissions = BotPermissionStore(temp_dir / ".web_permissions.json")
    permissions.set_allowed_bots("member", ["main"])
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permissions)

    def member_auth(_self, _request):
        return AuthContext(
            user_id=1001,
            token_used=True,
            account_id="member",
            username="member",
            role="member",
            capabilities={"view_file_tree", "read_file_content", "write_files", "terminal_exec"},
        )

    monkeypatch.setattr("bot.web.server.WebApiServer._auth_context", member_auth)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            read_resp = await client.get("/api/bots/sub1/files/read?filename=notes.md&mode=cat&lines=0")
            write_resp = await client.post(
                "/api/bots/sub1/files/write",
                json={"path": "notes.md", "content": "# updated\n"},
            )
            rebuild_resp = await client.post(
                "/api/bots/sub1/terminal/session/rebuild",
                json={"owner_id": "owner-1", "cwd": str(temp_dir), "shell": "bash"},
            )
            read_payload = await read_resp.json()
            write_payload = await write_resp.json()
            rebuild_payload = await rebuild_resp.json()

    assert read_resp.status == 403
    assert read_payload["error"]["code"] == "forbidden"
    assert write_resp.status == 403
    assert write_payload["error"]["code"] == "forbidden"
    assert rebuild_resp.status == 403
    assert rebuild_payload["error"]["code"] == "forbidden"
    assert (temp_dir / "notes.md").read_text(encoding="utf-8") == "# hello\n"

@pytest.mark.asyncio
async def test_chat_stream_route_returns_sse_events(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_stream_chat(manager, alias, user_id, message, **kwargs):
        assert user_id == chat_session_user_id(None)
        assert kwargs["actor"]["user_id"] == 1001
        yield {"type": "meta", "alias": alias}
        yield {"type": "delta", "text": "hello"}
        yield {"type": "done", "returncode": 0, "timed_out": False}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.stream_chat", fake_stream_chat):
                resp = await client.post("/api/bots/main/chat/stream", json={"message": "hi"})
                assert resp.status == 200
                body = await resp.text()
                assert "event: meta" in body
                assert "event: delta" in body
                assert "event: done" in body

@pytest.mark.asyncio
async def test_terminal_session_routes_and_websocket_attach(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    state: dict[str, object] = {"writes": []}

    class FakeProcess:
        is_pty = False
        pid = 4321

        def __init__(self) -> None:
            self.reads = [b"PS C:\\demo> ", b"output\r\n"]

        def read(self, timeout: int = 1000) -> bytes:
            if self.reads:
                return self.reads.pop(0)
            return b""

        def write(self, data: bytes) -> None:
            cast(list[bytes], state["writes"]).append(data)

        def isalive(self) -> bool:
            return True

        def terminate(self) -> None:
            state["terminated"] = True

        def close(self) -> None:
            state["closed"] = True

    def fake_create_shell_process(
        shell_type: str,
        cwd: str,
        use_pty: bool = True,
        cols: int | None = None,
        rows: int | None = None,
    ):
        state["shell_type"] = shell_type
        state["cwd"] = cwd
        state["use_pty"] = use_pty
        state["initial_size"] = (cols, rows)
        return FakeProcess()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.terminal_manager.create_shell_process", side_effect=fake_create_shell_process), \
                 patch("bot.web.server.get_default_shell", return_value="bash"):
                owner_id = "shared-terminal"
                resp = await client.get(f"/api/terminal/session?token=secret&owner_id={owner_id}")
                assert resp.status == 200
                payload = await resp.json()
                assert payload["data"]["started"] is False
                assert payload["data"]["connection_text"] == "未启动"

                rebuild_resp = await client.post(
                    "/api/terminal/session/rebuild?token=secret",
                    json={"owner_id": owner_id, "cwd": str(temp_dir), "shell": "bash"},
                )
                assert rebuild_resp.status == 200
                rebuild_payload = await rebuild_resp.json()
                assert rebuild_payload["data"]["started"] is True
                assert rebuild_payload["data"]["connection_text"] == "运行中"

                ws = await client.ws_connect("/terminal/ws?token=secret")
                await ws.send_json({"owner_id": owner_id})
                first_message = await ws.receive_json()
                assert first_message == {"pty_mode": False, "connection_text": "运行中"}

                output_message = await ws.receive()
                assert output_message.data.startswith(b"PS C:\\demo> ")

                await ws.send_str("pwd\r")
                for _ in range(20):
                    if state["writes"]:
                        break
                    await asyncio.sleep(0.01)

                assert state["cwd"] == str(temp_dir)
                assert state["shell_type"] == "bash"
                assert state["use_pty"] is True
                assert state["initial_size"] == (None, None)
                assert state["writes"] == [b"pwd\r"]
                assert state.get("terminated") is not True
                assert state.get("closed") is not True
                await ws.close()

@pytest.mark.asyncio
async def test_admin_update_routes_proxy_update_service(web_manager, monkeypatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    base_status = {
        "current_version": "1.0.0",
        "current_package_kind": "installer",
        "update_enabled": True,
        "update_channel": "release",
        "last_checked_at": "",
        "last_available_version": "",
        "last_available_release_url": "",
        "last_available_notes": "",
        "pending_update_version": "",
        "pending_update_path": "",
        "pending_update_notes": "",
        "pending_update_platform": "",
        "pending_update_package_kind": "",
        "update_last_error": "",
    }

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.get_update_status", return_value=base_status), \
                 patch("bot.web.server.set_update_enabled", return_value={**base_status, "update_enabled": False}) as toggle_mock, \
                 patch("bot.web.server.check_for_updates", return_value={**base_status, "last_available_version": "1.0.1"}) as check_mock, \
                 patch("bot.web.server.download_latest_update", return_value={**base_status, "pending_update_version": "1.0.1"}) as download_mock:
                resp = await client.get("/api/admin/update")
                assert resp.status == 200
                resp = await client.patch("/api/admin/update", json={"update_enabled": False})
                assert resp.status == 200
                resp = await client.post("/api/admin/update/check")
                assert resp.status == 200
                resp = await client.post("/api/admin/update/download")
                assert resp.status == 200

    toggle_mock.assert_called_once()
    assert toggle_mock.call_args.args[0] is False
    check_mock.assert_called_once()
    download_mock.assert_called_once()

@pytest.mark.asyncio
async def test_run_chat_routes_assistant_mode_to_assistant_runtime(
    web_manager: MultiBotManager, temp_dir: Path
):
    workdir = temp_dir / "assistant-cli"
    workdir.mkdir()
    web_manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(workdir),
        enabled=True,
        bot_mode="assistant",
    )
    runtime = MagicMock()
    runtime.submit_interactive = AsyncMock(
        return_value={"output": "assistant runtime result", "elapsed_seconds": 1},
    )
    web_manager.assistant_runtime = runtime

    data = await run_chat(web_manager, "assistant1", 1001, "hello")

    runtime.submit_interactive.assert_awaited_once()
    request = runtime.submit_interactive.await_args.args[0]
    assert request.bot_alias == "assistant1"
    assert request.user_id == chat_session_user_id(None)
    assert request.context_user_id == chat_session_user_id(None)
    assert request.text == "hello"
    assert request.interactive is True
    assert data["output"] == "assistant runtime result"


@pytest.mark.asyncio
async def test_admin_assistant_proposal_routes_list_and_approve(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    web_manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(workdir),
        enabled=True,
        bot_mode="assistant",
    )

    home = bootstrap_assistant_home(workdir)
    proposal = create_proposal(home, kind="knowledge", title="scope", body="assistant 单例")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/bots/assistant1/assistant/proposals")
            assert resp.status == 200
            listing = await resp.json()
            assert listing["data"]["items"][0]["id"] == proposal["id"]

            resp = await client.post(
                f"/api/admin/bots/assistant1/assistant/proposals/{proposal['id']}/approve"
            )
            assert resp.status == 200

def test_conversation_api_create_list_and_select(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)

    created = create_conversation(web_manager, "main", 1001, "新任务")
    conversation_id = created["conversation"]["id"]
    listed = list_conversations(web_manager, "main", 1001)
    selected = select_conversation(web_manager, "main", 1001, conversation_id)

    assert listed["items"][0]["id"] == conversation_id
    assert listed["items"][0]["active"] is True
    assert selected["conversation"]["active"] is True
    assert selected["messages"] == []
    assert session.active_conversation_id == conversation_id


def test_conversation_api_delete_all_clears_bot_workspace_sessions(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)

    first = create_conversation(web_manager, "main", 1001, "第一")
    second = create_conversation(web_manager, "main", 1001, "第二")
    session.codex_session_id = "thread-1"
    session.active_conversation_id = second["conversation"]["id"]
    session.persist()

    result = delete_all_conversations(web_manager, "main", 1001, delete_native_session=True)

    assert result["deleted_count"] == 2
    assert result["items"] == []
    assert result["messages"] == []
    assert result["native_session_cleared"] is True
    assert session.active_conversation_id is None
    assert session.codex_session_id is None
    assert list_conversations(web_manager, "main", 1001)["items"] == []
    assert first["conversation"]["id"] != second["conversation"]["id"]


@pytest.mark.asyncio
async def test_agent_api_create_update_delete(web_manager: MultiBotManager):
    listed = list_agents(web_manager, "main")
    assert listed["items"][0]["id"] == "main"
    assert listed["items"][0]["is_main"] is True

    created = await create_agent(
        web_manager,
        "main",
        {"id": "reviewer", "name": "代码审查", "system_prompt": "先列风险"},
    )
    assert created["agent"]["id"] == "reviewer"

    updated = await update_agent(web_manager, "main", "reviewer", {"enabled": False})
    assert updated["agent"]["enabled"] is False

    deleted = await delete_agent(web_manager, "main", "reviewer")
    assert deleted["deleted"] is True


@pytest.mark.asyncio
async def test_execute_shell_command_uses_exec_argv_without_shell(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return ("stdout", "stderr")

    async def fake_create_subprocess_exec(*argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(api_service.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await execute_shell_command(web_manager, "main", 1001, 'python -c "print(1)"')

    assert result["command"] == 'python -c "print(1)"'
    assert result["returncode"] == 0
    assert result["output"] == "stdout\n\n[stderr]\nstderr"
    assert captured["argv"] == ["python", "-c", "print(1)"]
    assert "shell" not in captured["kwargs"]
    assert captured["kwargs"]["cwd"] == web_manager.main_profile.working_dir


@pytest.mark.asyncio
async def test_stream_cli_chat_emits_trace_events_and_done_message(web_manager: MultiBotManager):
    web_manager.main_profile.cli_type = "codex"

    class FakeStdout:
        def __init__(self, owner):
            self._owner = owner
            self._lines = [
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.delta","item":{"type":"assistant_message","delta":"我先检查目录结构。"}}\n',
                '{"type":"item.completed","item":{"type":"function_call","name":"shell_command","arguments":"{\\"command\\":\\"Get-ChildItem -Force\\"}","call_id":"call_1"}}\n',
                '{"type":"item.completed","item":{"type":"function_call_output","call_id":"call_1","output":"README.md\\nbot\\nfront"}}\n',
                '{"type":"item.completed","item":{"type":"assistant_message","text":"目录已读取完成。"}}\n',
            ]

        def readline(self):
            if self._lines:
                return self._lines.pop(0)
            self._owner.returncode = 0
            return ""

        def read(self):
            return ""

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.stdout = FakeStdout(self)
            self.stdin = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    fake_process = FakeProcess()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "main", 1001, "列出当前目录")]

    trace_events = [event for event in events if event["type"] == "trace"]
    done_event = next(event for event in events if event["type"] == "done")

    assert trace_events
    assert trace_events[0]["event"]["kind"] == "tool_call"
    assert trace_events[0]["event"]["summary"] == "Get-ChildItem -Force"
    assert trace_events[1]["event"]["kind"] == "tool_result"
    assert done_event["message"]["role"] == "assistant"
    assert done_event["message"]["content"] == "目录已读取完成。"


def _codex_context_usage(left_percent: int) -> dict[str, object]:
    return {
        "provider": "codex",
        "source": "codex_session_token_count",
        "session_id": "thread-1",
        "used_tokens": 76593,
        "context_window": 258400,
        "context_left_percent": left_percent,
        "used_display": "76.6K",
        "window_display": "258K",
        "status_text": f"{left_percent}% context left · 76.6K / 258K",
    }


class _ScheduledFakeStdout:
    def __init__(self, owner, schedule: list[tuple[float, str]]):
        self._owner = owner
        self._schedule = list(schedule)

    def readline(self):
        if not self._schedule:
            self._owner.returncode = 0
            return ""
        delay, line = self._schedule.pop(0)
        if delay:
            time.sleep(delay)
        return line

    def read(self):
        return ""

    def close(self):
        pass


class _ScheduledFakeProcess:
    def __init__(self, schedule: list[tuple[float, str]]):
        self.returncode = None
        self.stdout = _ScheduledFakeStdout(self, schedule)
        self.stdin = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9


def _quick_codex_schedule() -> list[tuple[float, str]]:
    return [
        (0, '{"type":"thread.started","thread_id":"thread-1"}\n'),
        (0.02, '{"type":"item.completed","item":{"type":"assistant_message","text":"完成回复"}}\n'),
    ]


class BlockingAfterFinalStdout:
    def __init__(self):
        self.closed = threading.Event()
        self._lines = [
            '{"type":"thread.started","thread_id":"thread-final"}\n',
            '{"type":"item.completed","item":{"type":"assistant_message","text":"完成回复"}}\n',
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',
        ]

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        self.closed.wait(30)
        return ""

    def read(self):
        return ""

    def close(self):
        self.closed.set()


class FakeCodexProcessWithBlockingStdout:
    def __init__(self):
        self.stdout = BlockingAfterFinalStdout()
        self.stdin = None
        self.returncode = None
        self.terminate = MagicMock(side_effect=self._terminate)

    def _terminate(self):
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("codex", timeout or 0)
        return self.returncode

    def kill(self):
        self.returncode = -9


class RecordingStream:
    def __init__(self, *, fail_write: bool = False):
        self.closed = False
        self.fail_write = fail_write

    def write(self, _value):
        if self.fail_write:
            raise BrokenPipeError("pipe closed")

    def flush(self):
        return None

    def close(self):
        self.closed = True


class RecordingStdout:
    def __init__(self, owner, lines: list[str] | None = None, *, fail_read: bool = False):
        self._owner = owner
        self._lines = list(lines or [])
        self.closed = False
        self.fail_read = fail_read

    def readline(self):
        if self.fail_read:
            raise OSError("read failed")
        if self._lines:
            return self._lines.pop(0)
        self._owner.returncode = 0
        return ""

    def read(self):
        return ""

    def close(self):
        self.closed = True


class RecordingProcess:
    def __init__(self, lines: list[str] | None = None, *, stdin_fails: bool = False, stdout_fails: bool = False):
        self.returncode = None
        self.stdin = RecordingStream(fail_write=stdin_fails)
        self.stdout = RecordingStdout(self, lines, fail_read=stdout_fails)
        self.stderr = RecordingStream()
        self.terminate = MagicMock(side_effect=self._terminate)
        self.kill = MagicMock(side_effect=self._kill)

    def _terminate(self):
        self.returncode = -15

    def _kill(self):
        self.returncode = -9

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def assert_recording_process_closed(process: RecordingProcess):
    assert process.stdin.closed is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True


@pytest.mark.asyncio
async def test_plan_execute_endpoint_returns_plan_path(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: True)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/bots/main/plans/execute",
                json={"content": "# 方案\n\n- step", "title": "Plan Mode"},
            )
            payload = await response.json()

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["data"]["plan_path"].startswith("docs/plan/")
    assert payload["data"]["execution_message"].startswith("请按方案执行。方案文件：")
    assert payload["data"]["plan_path"] in payload["data"]["execution_message"]
    assert payload["data"]["bot_mode"] == "cli"
    assert payload["data"]["conversation"]["active"] is True
    assert payload["data"]["messages"] == []


@pytest.mark.asyncio
async def test_plugin_install_force_and_uninstall_routes(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_plugins_root = repo_root / "examples" / "plugins"
    source_plugins_root.mkdir(parents=True)
    source_dir = source_plugins_root / "demo-plugin"
    source_dir.mkdir()
    (source_dir / "plugin.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "demo-plugin",
                "name": "Demo",
                "version": "1.0.0",
                "description": "old",
                "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
                "views": [],
                "fileHandlers": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    plugins_root = tmp_path / "plugins"
    web_manager.plugin_service = PluginService(repo_root, plugins_root=plugins_root, source_plugins_root=source_plugins_root)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            first_install = await client.post("/api/plugins/install", json={"pluginId": "demo-plugin"})
            assert first_install.status == 200

            (source_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "id": "demo-plugin",
                        "name": "Demo",
                        "version": "2.0.0",
                        "description": "new",
                        "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},
                        "views": [],
                        "fileHandlers": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            force_install = await client.post("/api/plugins/install", json={"pluginId": "demo-plugin", "force": True})
            force_payload = await force_install.json()
            assert force_install.status == 200
            assert force_payload["data"]["version"] == "2.0.0"

            uninstall_response = await client.delete("/api/plugins/demo-plugin")
            uninstall_payload = await uninstall_response.json()
            assert uninstall_response.status == 200
            assert uninstall_payload["data"] == {"id": "demo-plugin", "deleted": True}

    await web_manager.plugin_service.shutdown()


@pytest.mark.asyncio
async def test_admin_update_offline_package_routes(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    package = tmp_path / "offline.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("bot/version.py", "APP_VERSION = '1.2.3'\n")

    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    with patch(
        "bot.web.server.list_offline_update_packages",
        return_value={
            "artifacts_dir": str(tmp_path),
            "items": [{"name": package.name, "path": str(package), "valid": True, "size": package.stat().st_size, "error": ""}],
        },
    ) as list_packages_mock, patch(
        "bot.web.server.asyncio.to_thread",
        new=AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)),
    ) as to_thread_mock, patch(
        "bot.web.server.prepare_offline_update",
        return_value={"pending_update_version": "1.2.3", "pending_update_path": str(package)},
    ) as prepare_mock:
        app = WebApiServer(web_manager)._build_app()
        async with TestServer(app) as test_server:
            async with TestClient(test_server) as client:
                packages_response = await client.get("/api/admin/update/offline-packages")
                packages_payload = await packages_response.json()
                assert packages_response.status == 200
                assert packages_payload["data"]["items"][0]["name"] == package.name
                to_thread_mock.assert_any_call(list_packages_mock, ANY)

                prepare_response = await client.post(
                    "/api/admin/update/offline/prepare",
                    json={"path": str(package), "version": "1.2.3"},
                )
                prepare_payload = await prepare_response.json()
                assert prepare_response.status == 200
                assert prepare_payload["data"]["pending_update_version"] == "1.2.3"
                prepare_mock.assert_called()
