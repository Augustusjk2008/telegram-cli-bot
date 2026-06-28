"""Web API 相关测试。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
import struct
import subprocess
import threading
import time
import zipfile
import zlib
from datetime import datetime, timedelta
from itertools import chain, repeat
from pathlib import Path
from typing import Any, cast
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from ag_ui import core
from pydantic import TypeAdapter
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
from bot.cluster.config import BotClusterConfig
from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import AgentProfile, BotProfile, UserSession
from bot.plugins.service import PluginService
from bot.session_store import load_session, save_session
from bot.web.auth_store import (
    CAP_ADMIN_OPS,
    CAP_CHAT_SEND,
    CAP_CREATE_WORKDIR_DIRECTORY,
    CAP_DEBUG_EXEC,
    CAP_MANAGE_BOTS,
    CAP_MANAGE_CLI_PARAMS,
    CAP_RUN_UNSAFE_CLI,
    CAP_VIEW_BOTS,
    CAP_VIEW_FILE_TREE,
    MEMBER_CAPABILITIES,
    WebAuthStore,
)
from bot.web.server import WebApiServer
from bot.web.api_service import (
    AuthContext,
    _stream_cli_chat,
    _build_stream_status_event,
    _communicate_claude_process,
    _communicate_process,
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
    get_native_agent_history_changes,
    get_native_agent_history_diff,
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
    reply_native_agent_permission,
    rollback_native_agent_history,
    run_chat,
    run_cli_chat,
    reset_user_session,
    save_chat_attachment,
    save_uploaded_file,
    select_conversation,
    update_agent,
    update_bot_workdir,
    write_file_content,
)


class _FixedForwardTunnelService:
    def should_autostart(self) -> bool:
        return False

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": "disabled",
            "status": "stopped",
            "phase": "stopped",
            "source": "disabled",
            "public_url": "",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "verified": False,
            "pid": None,
        }

    async def start(self) -> dict[str, object]:
        return self.snapshot()

    async def stop(self) -> dict[str, object]:
        return self.snapshot()

    async def restart(self) -> dict[str, object]:
        return self.snapshot()

    def preserve_for_restart(self) -> dict[str, object]:
        return self.snapshot()


class _RecordingFixedForwardService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def should_autostart(self) -> bool:
        return False

    def snapshot(self) -> dict[str, object]:
        return self._snapshot("snapshot")

    async def start(self) -> dict[str, object]:
        self.calls.append("start")
        return self._snapshot("running")

    async def stop(self) -> dict[str, object]:
        self.calls.append("stop")
        return self._snapshot("stopped")

    async def restart(self) -> dict[str, object]:
        self.calls.append("restart")
        return self._snapshot("running")

    def preserve_for_restart(self) -> dict[str, object]:
        return self.snapshot()

    def _snapshot(self, status: str) -> dict[str, object]:
        return {
            "mode": "fixed_public_forward",
            "status": status,
            "phase": status,
            "source": "fixed_public_forward",
            "public_url": "http://124.221.226.63:18088/node/nanjing-laptop",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "verified": status == "running",
            "pid": 1234 if status == "running" else None,
            "fixed_public_forward_enabled": True,
            "node_id": "nanjing-laptop",
            "base_path": "/node/nanjing-laptop",
        }


class _NoopRunner:
    async def cleanup(self) -> None:
        return None


from bot.app_settings import get_git_proxy_settings, update_git_proxy_address, update_git_proxy_port
from bot.web import api_service
from bot.web.chat_history_service import ChatHistoryService, StreamingPersistenceBuffer
from bot.web.chat_store import ChatStore, ChatTurnHandle
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
from bot.web.native_history_adapter import consume_stream_trace_chunk, create_stream_trace_state, load_native_transcript
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


def test_list_avatar_assets_prefixes_web_base_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    avatar_path = tmp_path / "avatar_01.png"
    avatar_path.write_bytes(_png_bytes(64, 64))
    monkeypatch.setattr(api_service, "_avatar_asset_dirs", lambda: [tmp_path])

    payload = api_service.list_avatar_assets(base_path="/node/nanjing-laptop")

    assert payload == {
        "items": [
            {
                "name": "avatar_01.png",
                "url": "/node/nanjing-laptop/assets/avatars/avatar_01.png",
            }
        ]
    }


def test_create_native_conversation_allows_child_agent(web_manager: MultiBotManager):
    web_manager.main_profile.agents = [
        AgentProfile(id="reviewer", name="审查专家", system_prompt="先列风险"),
    ]
    result = create_conversation(
        web_manager,
        "main",
        1001,
        "审查",
        agent_id="reviewer",
        execution_mode="native_agent",
    )

    assert result["conversation"]["agent_id"] == "reviewer"
    assert result["conversation"]["execution_mode"] == "native_agent"

    listed = list_conversations(
        web_manager,
        "main",
        1001,
        agent_id="reviewer",
        execution_mode="native_agent",
    )
    assert listed["items"][0]["id"] == result["conversation"]["id"]


def test_create_native_main_conversation_syncs_cluster_child_agents(web_manager: MultiBotManager, tmp_path: Path):
    profile = web_manager.main_profile
    profile.working_dir = str(tmp_path)
    profile.cluster = BotClusterConfig(enabled=True)
    profile.agents = [
        AgentProfile(id="reviewer", name="审查专家", system_prompt="先列风险"),
        AgentProfile(id="tester", name="测试专家", system_prompt="优先跑测试"),
    ]
    main_session = get_session_for_alias(web_manager, "main", 1001)
    main_session.working_dir = str(tmp_path)
    _profile, _agent, reviewer_session = get_chat_session_for_alias(web_manager, "main", 1001, "reviewer")
    _profile, _agent, tester_session = get_chat_session_for_alias(web_manager, "main", 1001, "tester")
    with reviewer_session._lock:
        reviewer_session.active_conversation_id = "conv-old-reviewer"
        reviewer_session.native_agent_session_id = "native-old-reviewer"
    with tester_session._lock:
        tester_session.active_conversation_id = "conv-old-tester"
        tester_session.native_agent_session_id = "native-old-tester"
    reviewer_session.persist()
    tester_session.persist()

    result = create_conversation(web_manager, "main", 1001, "原生主任务", execution_mode="native_agent")

    assert result["conversation"]["agent_id"] == "main"
    assert result["conversation"]["execution_mode"] == "native_agent"
    reviewer_listed = list_conversations(
        web_manager,
        "main",
        1001,
        agent_id="reviewer",
        execution_mode="native_agent",
    )
    tester_listed = list_conversations(
        web_manager,
        "main",
        1001,
        agent_id="tester",
        execution_mode="native_agent",
    )
    assert len(reviewer_listed["items"]) == 1
    assert len(tester_listed["items"]) == 1
    assert reviewer_listed["items"][0]["execution_mode"] == "native_agent"
    assert tester_listed["items"][0]["execution_mode"] == "native_agent"
    assert reviewer_session.active_conversation_id == reviewer_listed["items"][0]["id"]
    assert tester_session.active_conversation_id == tester_listed["items"][0]["id"]
    assert reviewer_session.native_agent_session_id is None
    assert tester_session.native_agent_session_id is None


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
        supported_execution_modes=["cli", "native_agent"],
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
async def test_admin_tunnel_reports_fixed_forward_and_controls_fixed_service(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_ENABLED", True)
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_URL", "http://124.221.226.63:18088/node/nanjing-laptop")
    monkeypatch.setattr("bot.web.server.TCB_HUB_NODE_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.TCB_NODE_ID", "nanjing-laptop")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "/node/nanjing-laptop")

    fixed_service = _RecordingFixedForwardService()
    app = WebApiServer(
        web_manager,
        tunnel_service=_FixedForwardTunnelService(),
        fixed_forward_service=fixed_service,
    )._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            status_response = await client.get("/api/admin/tunnel")
            payload = await status_response.json()
            start_response = await client.post("/api/admin/tunnel/start")
            start_payload = await start_response.json()
            restart_response = await client.post("/api/admin/tunnel/restart")
            restart_payload = await restart_response.json()
            stop_response = await client.post("/api/admin/tunnel/stop")
            stop_payload = await stop_response.json()

    assert status_response.status == 200
    assert payload["data"]["mode"] == "fixed_public_forward"
    assert payload["data"]["source"] == "fixed_public_forward"
    assert payload["data"]["public_url"] == "http://124.221.226.63:18088/node/nanjing-laptop"
    assert start_response.status == 200
    assert start_payload["data"]["status"] == "running"
    assert restart_response.status == 200
    assert restart_payload["data"]["status"] == "running"
    assert stop_response.status == 200
    assert stop_payload["data"]["status"] == "stopped"
    assert fixed_service.calls == ["start", "restart", "stop"]


@pytest.mark.asyncio
async def test_web_server_stop_preserve_tunnel_stops_fixed_forward(web_manager: MultiBotManager):
    fixed_service = _RecordingFixedForwardService()
    server = WebApiServer(
        web_manager,
        tunnel_service=_FixedForwardTunnelService(),
        fixed_forward_service=fixed_service,
    )
    server._runner = cast(Any, _NoopRunner())

    await server.stop(preserve_tunnel=True)

    assert fixed_service.calls == ["stop"]


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
async def test_run_chat_native_agent_cluster_starts_run_and_injects_prompt(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True)
    profile.supported_execution_modes = ["cli", "native_agent"]
    captured: dict[str, Any] = {}

    class FakeNativeAgentService:
        async def run_chat(self, **kwargs):
            captured.update(kwargs)
            return {"output": "ok", "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeAgentService())

    result = await api_service.run_chat(
        web_manager,
        "main",
        1001,
        "hi",
        execution_mode="native_agent",
        cluster=True,
        mentions=[{"agent_id": "reviewer"}],
    )

    assert result["output"] == "ok"
    prompt = captured["prompt_text"]
    assert "run_id:" in prompt
    assert "reviewer" in prompt
    assert captured["user_text"] == "hi"
    run_id = captured["cluster_run_id"]
    run = api_service._CLUSTER_RUNTIME.get_run(run_id)
    assert run is not None
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_stream_chat_native_agent_cluster_emits_cluster_run_id_and_finishes(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True)
    profile.supported_execution_modes = ["cli", "native_agent"]
    captured: dict[str, Any] = {}

    class FakeNativeAgentService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {"type": "meta", "native_session_id": "sess-1", "cluster_run_id": kwargs.get("cluster_run_id")}
            yield {"type": "done", "output": "ok", "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeAgentService())

    events = [
        event async for event in api_service.stream_chat(
            web_manager,
            "main",
            1001,
            "@reviewer hi",
            execution_mode="native_agent",
            cluster=True,
            mentions=[{"agent_id": "reviewer"}],
        )
    ]

    meta = next(event for event in events if event["type"] == "meta")
    assert meta["cluster_run_id"] == captured["cluster_run_id"]
    assert "reviewer" in captured["prompt_text"]
    run = api_service._CLUSTER_RUNTIME.get_run(captured["cluster_run_id"])
    assert run is not None
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_run_chat_native_agent_plan_cluster_prompt_contains_run_id_and_mentions(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True)
    profile.supported_execution_modes = ["cli", "native_agent"]
    captured: dict[str, Any] = {}

    class FakeNativeAgentService:
        async def run_chat(self, **kwargs):
            captured.update(kwargs)
            return {"output": "ok", "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeAgentService())

    await api_service.run_chat(
        web_manager,
        "main",
        1001,
        "按方案执行",
        task_mode="plan",
        execution_mode="native_agent",
        cluster=True,
        mentions=[{"agent_id": "reviewer"}],
    )

    prompt = captured["prompt_text"]
    assert captured["cluster_run_id"] in prompt
    assert "reviewer" in prompt
    assert "按方案执行" in prompt
    assert captured["user_text"] == "按方案执行"


@pytest.mark.asyncio
async def test_get_cluster_status_native_agent_reports_pi_extension_target(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = web_manager.main_profile
    profile.default_execution_mode = "native_agent"
    profile.supported_execution_modes = ["native_agent"]
    launcher = tmp_path / ".tcb" / "bin" / "tcb-cluster-mcp.cmd"
    config_path = tmp_path / ".tcb" / "cluster-mcp" / "config.json"
    token_path = tmp_path / ".tcb" / "cluster-mcp" / "token"
    extension_path = tmp_path / ".pi" / "agent" / "extensions" / "tcb-cluster.ts"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("@echo off\r\n", encoding="utf-8")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({
        "schema_version": 1,
        "repo_root": str(tmp_path),
        "bridge_url": "http://127.0.0.1:8765",
        "token_file": str(token_path),
        "server_name": "tcb-cluster",
    }), encoding="utf-8")
    token_path.write_text("token", encoding="utf-8")
    extension_path.parent.mkdir(parents=True, exist_ok=True)
    extension_path.write_text("export default function () {}\n", encoding="utf-8")
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(tmp_path / ".pi" / "agent" / "settings.json"))
    monkeypatch.setattr(api_service, "_cluster_launcher_path", lambda: launcher)
    monkeypatch.setattr(api_service, "_cluster_mcp_config_path", lambda: config_path)
    monkeypatch.setattr(api_service, "_cluster_token_path", lambda: token_path)
    monkeypatch.setattr(api_service, "get_pi_cluster_extension_path", lambda: extension_path)
    monkeypatch.setattr(api_service, "build_pi_mcp_self_test_command", lambda cfg: ["python", str(cfg), "--self-test"])
    monkeypatch.setattr(api_service.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr=""))

    status = api_service.get_cluster_status(web_manager, "main")

    assert status["mcp"]["active_cli_type"] == "pi"
    assert status["mcp"]["pi"]["state"] == "installed"
    assert status["mcp"]["pi"]["message"] == "Pi 集群扩展已配置"


@pytest.mark.asyncio
async def test_prepare_cluster_setup_returns_pi_extension_paths(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    profile = web_manager.main_profile
    profile.default_execution_mode = "native_agent"
    profile.supported_execution_modes = ["native_agent"]
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(tmp_path / ".pi" / "agent" / "settings.json"))

    class FakeLauncher:
        launcher_path = tmp_path / ".tcb" / "bin" / "tcb-cluster-mcp.cmd"
        config_path = tmp_path / ".tcb" / "cluster-mcp" / "config.json"
        token_path = tmp_path / ".tcb" / "cluster-mcp" / "token"

        def to_dict(self):
            return {
                "server_name": "tcb-cluster",
                "launcher_path": str(self.launcher_path),
                "config_path": str(self.config_path),
                "token_path": str(self.token_path),
            }

    monkeypatch.setattr(api_service, "prepare_cluster_mcp_launcher", lambda **kwargs: FakeLauncher())
    extension_path = tmp_path / ".pi" / "agent" / "extensions" / "tcb-cluster.ts"
    monkeypatch.setattr(api_service, "write_pi_cluster_extension", lambda **kwargs: extension_path)
    result = api_service.prepare_cluster_setup(web_manager, "main")

    assert result["pi_extension_path"].endswith(".pi\\agent\\extensions\\tcb-cluster.ts") or result["pi_extension_path"].endswith(".pi/agent/extensions/tcb-cluster.ts")
    assert result["pi_extension_name"] == "tcb-cluster.ts"
    assert "self_test_command" in result


@pytest.mark.asyncio
async def test_run_chat_routes_assistant_native_agent_execution_mode(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    web_manager.main_profile.bot_mode = "assistant"
    web_manager.main_profile.working_dir = str(temp_dir)
    web_manager.main_profile.supported_execution_modes = ["native_agent"]
    web_manager.main_profile.default_execution_mode = "native_agent"
    web_manager.assistant_runtime = MagicMock()
    web_manager.assistant_runtime.submit_interactive = AsyncMock(return_value={"output": "assistant"})
    captured: dict[str, Any] = {}

    class FakeNativeService:
        async def run_chat(self, **kwargs):
            captured.update(kwargs)
            return {"output": "native", "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    result = await run_chat(web_manager, "main", 1001, "你好", execution_mode="native_agent")

    assert result["output"] == "native"
    assert captured["profile"] is web_manager.main_profile
    assert captured["prompt_text"] == "你好"
    web_manager.assistant_runtime.submit_interactive.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_chat_assistant_proposal_patch_stays_on_assistant_runtime_when_default_native(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    web_manager.main_profile.bot_mode = "assistant"
    web_manager.main_profile.supported_execution_modes = ["native_agent"]
    web_manager.main_profile.default_execution_mode = "native_agent"
    runtime = MagicMock()
    runtime.submit_interactive = AsyncMock(return_value={"output": "assistant"})
    web_manager.assistant_runtime = runtime
    monkeypatch.setattr(api_service, "_ensure_proposal_patch_chat_available", lambda *args, **kwargs: None)

    result = await run_chat(web_manager, "main", 1001, "生成 patch", task_mode="proposal_patch")

    assert result["output"] == "assistant"
    runtime.submit_interactive.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_chat_routes_assistant_native_agent_execution_mode(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    web_manager.main_profile.bot_mode = "assistant"
    web_manager.main_profile.working_dir = str(temp_dir)
    web_manager.main_profile.supported_execution_modes = ["native_agent"]
    web_manager.main_profile.default_execution_mode = "native_agent"
    web_manager.assistant_runtime = MagicMock()
    web_manager.assistant_runtime.stream_interactive = AsyncMock()
    captured: dict[str, Any] = {}

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {"type": "done", "output": "native", "message": {"id": "assistant-native", "role": "assistant", "content": "native", "meta": {}}, "elapsed_seconds": 1, "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    events = [
        event async for event in api_service.stream_chat(
            web_manager,
            "main",
            1001,
            "你好",
            execution_mode="native_agent",
        )
    ]

    assert events[-1]["type"] == "done"
    assert captured["profile"] is web_manager.main_profile
    assert captured["prompt_text"] == "你好"


@pytest.mark.asyncio
async def test_execute_assistant_run_request_routes_default_native_agent(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    profile = web_manager.main_profile
    profile.bot_mode = "assistant"
    profile.working_dir = str(temp_dir)
    profile.cli_type = "codex"
    profile.cli_path = "codex"
    profile.supported_execution_modes = ["cli", "native_agent"]
    profile.default_execution_mode = "native_agent"
    captured: dict[str, Any] = {}

    async def fail_run_cli_chat(*_args, **_kwargs):
        raise AssertionError("run_cli_chat should not be called")

    def fake_prepare_assistant_prompt(_profile, _session, *, user_id, user_text, cli_type):
        captured["prepared_user_id"] = user_id
        captured["prepared_user_text"] = user_text
        captured["prepared_cli_type"] = cli_type
        return object(), {}, f"prepared:{user_text}", False, {"sync_ms": 3}

    def fake_finalize_assistant_chat_turn(_assistant_home, **kwargs):
        captured["finalized_response"] = kwargs["response"]

    class FakeNativeService:
        async def run_chat(self, **kwargs):
            captured.update(kwargs)
            return {"output": "native", "returncode": 0}

    monkeypatch.setattr(api_service, "run_cli_chat", fail_run_cli_chat)
    monkeypatch.setattr(api_service, "_prepare_assistant_prompt", fake_prepare_assistant_prompt)
    monkeypatch.setattr(api_service, "_finalize_assistant_chat_turn", fake_finalize_assistant_chat_turn)
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    request = AssistantRunRequest(
        run_id="run-native-cron",
        source="cron",
        bot_alias="main",
        user_id=1001,
        text="cron prompt",
        interactive=False,
        visible_text="cron prompt",
    )

    result = await execute_assistant_run_request(web_manager, request)

    assert result["output"] == "native"
    assert result["assistant_stage_durations"] == {"sync_ms": 3}
    assert captured["profile"] is profile
    assert captured["user_text"] == "cron prompt"
    assert captured["prompt_text"] == "prepared:cron prompt"
    assert captured["prepared_cli_type"] == "codex"
    assert captured["finalized_response"] == "native"


@pytest.mark.asyncio
async def test_execute_assistant_run_request_native_dream_uses_prepared_prompt(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    profile = web_manager.main_profile
    profile.bot_mode = "assistant"
    profile.working_dir = str(temp_dir)
    profile.supported_execution_modes = ["cli", "native_agent"]
    profile.default_execution_mode = "native_agent"
    captured: dict[str, Any] = {}
    finalized: dict[str, Any] = {}

    async def fail_run_cli_chat(*_args, **_kwargs):
        raise AssertionError("run_cli_chat should not be called")

    def fake_prepare_dream(_manager, _profile, _session, _request, *, user_text):
        captured["dream_prepare_user_text"] = user_text
        return object(), "prepared dream prompt", {"history_count": 2}, {"dream_ms": 9}

    def fake_finalize(_manager, _request, result):
        finalized["result"] = dict(result)
        return {"output": "final dream", "message": result.get("message")}

    class FakeNativeService:
        async def run_chat(self, **kwargs):
            captured.update(kwargs)
            return {"output": "raw dream", "message": {"id": "m1", "content": "raw dream"}, "returncode": 0}

    monkeypatch.setattr(api_service, "run_cli_chat", fail_run_cli_chat)
    monkeypatch.setattr(api_service, "_prepare_dream_assistant_prompt", fake_prepare_dream)
    monkeypatch.setattr(api_service, "_finalize_dream_execution", fake_finalize)
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    request = AssistantRunRequest(
        run_id="run-native-dream",
        source="cron",
        bot_alias="main",
        user_id=-123,
        text="raw cron dream",
        interactive=False,
        visible_text="raw cron dream",
        context_user_id=1001,
        task_mode="dream",
        task_payload={"mode": "dream"},
    )

    result = await execute_assistant_run_request(web_manager, request)

    assert result["output"] == "final dream"
    assert captured["prompt_text"] == "prepared dream prompt"
    assert captured["dream_prepare_user_text"] == "raw cron dream"
    assert finalized["result"]["dream_context_stats"] == {"history_count": 2}
    assert finalized["result"]["dream_prompt_text"] == "prepared dream prompt"
    assert finalized["result"]["assistant_stage_durations"] == {"dream_ms": 9}


@pytest.mark.asyncio
async def test_execute_assistant_run_request_default_cli_stays_cli(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    profile = web_manager.main_profile
    profile.bot_mode = "assistant"
    profile.supported_execution_modes = ["cli", "native_agent"]
    profile.default_execution_mode = "cli"
    captured: dict[str, Any] = {}

    async def fake_run_cli_chat(_manager, alias, user_id, text, *, request=None, **_kwargs):
        captured["alias"] = alias
        captured["user_id"] = user_id
        captured["text"] = text
        captured["request"] = request
        return {"output": "cli", "returncode": 0}

    monkeypatch.setattr(api_service, "run_cli_chat", fake_run_cli_chat)
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: (_ for _ in ()).throw(AssertionError("native should not be called")))

    request = AssistantRunRequest(
        run_id="run-cli-cron",
        source="cron",
        bot_alias="main",
        user_id=1001,
        text="cron prompt",
        interactive=False,
    )

    result = await execute_assistant_run_request(web_manager, request)

    assert result["output"] == "cli"
    assert captured["alias"] == "main"
    assert captured["text"] == "cron prompt"
    assert captured["request"] is request


@pytest.mark.asyncio
async def test_stream_assistant_run_request_routes_default_native_agent(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    profile = web_manager.main_profile
    profile.bot_mode = "assistant"
    profile.working_dir = str(temp_dir)
    profile.supported_execution_modes = ["cli", "native_agent"]
    profile.default_execution_mode = "native_agent"
    captured: dict[str, Any] = {}

    async def fail_stream_cli_chat(*_args, **_kwargs):
        raise AssertionError("_stream_cli_chat should not be called")
        yield {}

    def fake_prepare_assistant_prompt(_profile, _session, *, user_id, user_text, cli_type):
        return object(), {}, f"prepared stream:{user_text}", False, {"sync_ms": 5}

    def fake_schedule_assistant_chat_turn_finalization(_assistant_home, **kwargs):
        captured["scheduled_response"] = kwargs["response"]

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {"type": "done", "output": "native stream", "message": {"id": "m1", "content": "native stream"}, "returncode": 0}

    monkeypatch.setattr(api_service, "_stream_cli_chat", fail_stream_cli_chat)
    monkeypatch.setattr(api_service, "_prepare_assistant_prompt", fake_prepare_assistant_prompt)
    monkeypatch.setattr(api_service, "_schedule_assistant_chat_turn_finalization", fake_schedule_assistant_chat_turn_finalization)
    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    request = AssistantRunRequest(
        run_id="run-native-stream",
        source="web",
        bot_alias="main",
        user_id=1001,
        text="stream prompt",
        interactive=True,
        visible_text="stream prompt",
    )

    events = [event async for event in stream_assistant_run_request(web_manager, request)]

    assert events[-1]["type"] == "done"
    assert events[-1]["output"] == "native stream"
    assert events[-1]["assistant_stage_durations"] == {"sync_ms": 5}
    assert captured["prompt_text"] == "prepared stream:stream prompt"
    assert captured["scheduled_response"] == "native stream"


def test_pi_cluster_extension_path_uses_pi_agent_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from bot.cluster.setup import get_pi_cluster_extension_path

    settings_path = tmp_path / "data" / "pi-home" / ".pi" / "agent" / "settings.json"
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(settings_path))

    assert get_pi_cluster_extension_path() == settings_path.parent / "extensions" / "tcb-cluster.ts"


@pytest.mark.asyncio
async def test_kill_native_agent_cluster_marks_run_and_tasks_cancelled(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.cluster.config import BotClusterConfig
    from bot.cluster.runtime import AskAgentRequest

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True)
    run = api_service._CLUSTER_RUNTIME.start_run(
        api_service.ClusterRunRequest(bot_alias="main", user_id=chat_session_user_id(1001), profile=profile)
    )
    queued = api_service._CLUSTER_RUNTIME.create_agent_task(
        run.run_id,
        AskAgentRequest(agent_id="reviewer", message="看一下", model_tier="medium", timeout_seconds=60, allow_write=False),
    )
    running = api_service._CLUSTER_RUNTIME.create_agent_task(
        run.run_id,
        AskAgentRequest(agent_id="tester", message="测一下", model_tier="medium", timeout_seconds=60, allow_write=False),
    )
    api_service._CLUSTER_RUNTIME.mark_agent_task_running(run.run_id, running.task_id)
    api_service._CLUSTER_RUN_CONTROLS[run.run_id] = api_service._ClusterRunControl(asyncio.Semaphore(1))

    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True
        session.native_agent_session_id = "sess-1"
        session.stop_requested = False
    monkeypatch.setattr(api_service.get_native_agent_service(), "abort", AsyncMock(return_value=True))

    result = await api_service.kill_user_process(web_manager, "main", 1001, execution_mode="native_agent")

    assert result["cluster_run_cancelled"] == run.run_id
    assert run.status == "cancelled"
    assert run.tasks[queued.task_id].status == "cancelled"
    assert run.tasks[running.task_id].status == "cancelled"
    assert run.run_id not in api_service._CLUSTER_RUN_CONTROLS


@pytest.mark.asyncio
async def test_native_agent_cluster_child_task_uses_native_runner(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True, max_parallel_agents=1)
    profile.supported_execution_modes = ["cli", "native_agent"]
    await web_manager.create_bot_agent("main", {"id": "tester", "name": "测试专家"})
    captured: dict[str, Any] = {}

    class FakeNativeAgentService:
        async def run_chat(self, **kwargs):
            captured["run_id"] = kwargs["cluster_run_id"]
            return {"output": "ok", "returncode": 0}

        async def stream_chat(self, **kwargs):
            captured["child_agent_id"] = kwargs["session"].agent_id
            captured["child_solo_mode"] = kwargs.get("solo_mode")
            yield {"type": "done", "output": "done", "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeAgentService())

    await api_service.run_chat(
        web_manager,
        "main",
        1001,
        "hi",
        execution_mode="native_agent",
        cluster=True,
        allow_unsafe_cli=True,
    )
    result = await api_service.handle_cluster_mcp_tool(
        web_manager,
        captured["run_id"],
        "ask_agent",
        {"agent_id": "tester", "message": "跑测试"},
    )
    task_id = result["data"]["task_id"]
    await api_service.handle_cluster_mcp_tool(
        web_manager,
        captured["run_id"],
        "poll_agent_tasks",
        {"task_ids": [task_id], "wait_seconds": 1, "include_output": True},
    )

    assert captured["child_agent_id"] == "tester"
    assert captured["child_solo_mode"] is True


@pytest.mark.asyncio
async def test_native_agent_cluster_child_task_respects_write_policy(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True, write_policy="main_only")
    profile.supported_execution_modes = ["cli", "native_agent"]
    await web_manager.create_bot_agent("main", {"id": "tester", "name": "测试专家", "cluster": {"allow_write": True}})
    captured: dict[str, Any] = {}

    class FakeNativeAgentService:
        async def run_chat(self, **kwargs):
            captured["run_id"] = kwargs["cluster_run_id"]
            return {"output": "ok", "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeAgentService())

    await api_service.run_chat(
        web_manager,
        "main",
        1001,
        "hi",
        execution_mode="native_agent",
        cluster=True,
    )

    with pytest.raises(WebApiError) as exc_info:
        await api_service.handle_cluster_mcp_tool(
            web_manager,
            captured["run_id"],
            "ask_agent",
            {"agent_id": "tester", "message": "改文件", "allow_write": True},
        )

    assert exc_info.value.code == "cluster_tool_forbidden"


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
async def test_cluster_agent_task_inherits_unsafe_cli_permission(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    from bot.cluster.config import BotClusterConfig

    profile = web_manager.main_profile
    profile.cluster = BotClusterConfig(enabled=True, max_parallel_agents=1)
    await web_manager.create_bot_agent("main", {"id": "tester", "name": "测试专家"})
    run = api_service._CLUSTER_RUNTIME.start_run(
        api_service.ClusterRunRequest(
            bot_alias="main",
            user_id=1001,
            profile=profile,
            allow_unsafe_cli=True,
        )
    )
    captured: dict[str, Any] = {}

    async def fake_stream_cli_chat(*_args, **kwargs):
        captured["allow_unsafe_cli"] = kwargs.get("allow_unsafe_cli")
        yield {"type": "done", "output": "done", "returncode": 0}

    monkeypatch.setattr(api_service, "_stream_cli_chat", fake_stream_cli_chat)

    result = await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "ask_agent",
        {"agent_id": "tester", "message": "跑测试"},
    )
    task_id = result["data"]["task_id"]
    await api_service.handle_cluster_mcp_tool(
        web_manager,
        run.run_id,
        "poll_agent_tasks",
        {"task_ids": [task_id], "wait_seconds": 1, "include_output": True},
    )

    assert captured["allow_unsafe_cli"] is True


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


def test_directory_listing_supports_windows_virtual_drive_root(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.browse_dir = "C:\\"

    monkeypatch.setattr("bot.web.files_service.os.path.isdir", lambda path: str(path) in {"C:\\", "D:\\"})

    listing = get_directory_listing(web_manager, "main", 1001, path="::windows-drives::")

    assert listing["working_dir"] == "盘符列表"
    assert listing["is_virtual_root"] is True
    assert [item["name"] for item in listing["entries"]] == ["C:\\", "D:\\"]


def test_guest_directory_listing_rejects_windows_virtual_drive_root(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.browse_dir = "C:\\"

    with pytest.raises(WebApiError) as exc_info:
        get_directory_listing(
            web_manager,
            "main",
            1001,
            path="::windows-drives::",
            base_dir="C:\\",
            restrict_to_base_dir=True,
        )

    assert exc_info.value.status == 403
    assert exc_info.value.code == "forbidden_path"


@pytest.mark.asyncio
async def test_streaming_persistence_buffer_flushes_in_background_without_blocking(tmp_path: Path):
    class SlowService:
        def __init__(self) -> None:
            self.preview_calls = 0
            self.trace_calls = 0

        def replace_assistant_preview(self, _handle, _preview_text):
            time.sleep(0.15)
            self.preview_calls += 1

        def append_trace_events(self, _handle, _events):
            time.sleep(0.15)
            self.trace_calls += 1

    loop = asyncio.get_running_loop()
    service = SlowService()
    handle = ChatTurnHandle("conv-1", "turn-1", "msg-u", "msg-a")
    buffer = StreamingPersistenceBuffer(service, handle, loop=loop, flush_interval_seconds=0.05)

    buffer.queue_preview("preview")
    buffer.queue_trace({"kind": "trace", "summary": "x" * 100})
    start = loop.time()
    buffer.maybe_flush()
    elapsed = loop.time() - start
    assert elapsed < 0.05
    await buffer.close()
    assert service.preview_calls == 1
    assert service.trace_calls == 1

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


@pytest.mark.asyncio
async def test_update_bot_workdir_resets_all_related_sessions(web_manager: MultiBotManager, temp_dir: Path):
    old_dir = temp_dir / "old"
    new_dir = temp_dir / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    web_manager.main_profile.working_dir = str(old_dir)
    web_manager.main_profile.agents = [AgentProfile(id="reviewer", name="审查专家", system_prompt="先看")]
    if "reviewer" not in {agent.id for agent in web_manager.main_profile.normalized_agents()}:
        web_manager.main_profile.agents.append(AgentProfile(id="reviewer", name="审查专家", system_prompt="先看"))
    session = get_session_for_alias(web_manager, "main", 1001)
    _profile, _agent, reviewer_session = get_chat_session_for_alias(web_manager, "main", 1001, "reviewer")
    with session._lock:
        session.working_dir = str(old_dir)
        session.active_conversation_id = "conv-main"
        session.native_agent_session_id = "native-main"
        session.is_processing = True
        session.running_user_text = "main"
    with reviewer_session._lock:
        reviewer_session.working_dir = str(old_dir)
        reviewer_session.active_conversation_id = "conv-reviewer"
        reviewer_session.native_agent_session_id = "native-reviewer"
        reviewer_session.is_processing = True

    with pytest.raises(WebApiError) as exc_info:
        await update_bot_workdir(web_manager, "main", str(new_dir), 1001)

    assert exc_info.value.code == "workdir_change_blocked_processing"
    with session._lock:
        session.is_processing = False
    with reviewer_session._lock:
        reviewer_session.is_processing = False
    result = await update_bot_workdir(web_manager, "main", str(new_dir), 1001, force_reset=True)

    assert result["bot"]["working_dir"] == str(new_dir)
    assert session.working_dir == str(new_dir)
    assert reviewer_session.working_dir == str(new_dir)
    assert session.active_conversation_id is None
    assert reviewer_session.active_conversation_id is None
    assert session.native_agent_session_id is None
    assert reviewer_session.native_agent_session_id is None

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


@pytest.mark.asyncio
async def test_member_manage_bots_can_create_workdir_without_write_files(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    updated = isolated_web_auth_store.update_member(
        session.account.account_id,
        capabilities=[CAP_VIEW_FILE_TREE, CAP_MANAGE_BOTS, CAP_CREATE_WORKDIR_DIRECTORY],
    )
    assert "write_files" not in updated["capabilities"]
    assert "admin_ops" not in updated["capabilities"]
    refreshed = isolated_web_auth_store.login_member("alice", "pw-123")
    headers = {"Authorization": f"Bearer {refreshed.token}"}
    from bot.web.permission_store import BotPermissionStore

    permissions = BotPermissionStore(temp_dir / ".web_permissions.json")
    permissions.grant_bot_to_account(refreshed.account.account_id, "main")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permissions)

    parent_dir = temp_dir / "workdirs"
    parent_dir.mkdir()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            list_response = await client.get("/api/bots/main/ls", params={"path": str(temp_dir)}, headers=headers)
            workdir_mkdir_response = await client.post(
                "/api/bots/main/workdir/mkdir",
                json={"parent_path": str(parent_dir), "name": "agent-one"},
                headers=headers,
            )
            files_mkdir_response = await client.post(
                "/api/bots/main/files/mkdir",
                json={"parent_path": str(parent_dir), "name": "blocked"},
                headers=headers,
            )
            create_response = await client.post(
                "/api/admin/bots",
                json={
                    "alias": "agentone",
                    "bot_mode": "cli",
                    "cli_type": "codex",
                    "cli_path": "codex",
                    "working_dir": str(parent_dir / "agent-one"),
                },
                headers=headers,
            )
            create_payload = await create_response.json()

    assert list_response.status == 200
    assert workdir_mkdir_response.status == 200
    assert (parent_dir / "agent-one").is_dir()
    assert files_mkdir_response.status == 403
    assert create_response.status == 200
    assert create_payload["data"]["bot"]["alias"] == "agentone"

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
async def test_remote_empty_account_store_requires_setup_without_bootstrap_admin(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/auth/me")
            payload = await resp.json()

    assert resp.status == 401
    assert payload["error"]["code"] == "setup_required"


@pytest.mark.asyncio
async def test_loopback_empty_account_store_keeps_local_bootstrap(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: True)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/auth/me")
            payload = await resp.json()

    assert resp.status == 200
    assert payload["data"]["is_local_admin"] is True


@pytest.mark.asyncio
async def test_query_token_is_rejected(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/auth/me?token=secret")
            payload = await resp.json()

    assert resp.status == 401
    assert payload["error"]["code"] == "query_token_disabled"


@pytest.mark.asyncio
async def test_login_sets_http_only_cookie_without_token_payload(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/auth/login", json={"username": "alice", "password": "pw-123"})
            payload = await resp.json()

    cookie = resp.cookies.get("tcb_web_session")
    assert resp.status == 200
    assert "token" not in payload["data"]
    assert cookie is not None
    assert cookie["httponly"]


@pytest.mark.asyncio
async def test_cookie_auth_write_requires_origin(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    isolated_web_auth_store.update_member(session.account.account_id, capabilities=[CAP_CHAT_SEND])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            client.session.cookie_jar.update_cookies({"tcb_web_session": session.token})
            resp = await client.post("/api/bots/main/chat", json={"message": "hi"})
            payload = await resp.json()

    assert resp.status == 403
    assert payload["error"]["code"] == "csrf_origin_rejected"


@pytest.mark.asyncio
async def test_auth_cookie_issue_rejects_cross_origin(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            login_resp = await client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "pw-123"},
                headers={"Origin": "https://evil.example.test"},
            )
            guest_resp = await client.post(
                "/api/auth/guest",
                headers={"Origin": "https://evil.example.test"},
            )
            login_payload = await login_resp.json()
            guest_payload = await guest_resp.json()

    assert login_resp.status == 403
    assert login_payload["error"]["code"] == "csrf_origin_rejected"
    assert "tcb_web_session" not in login_resp.cookies
    assert guest_resp.status == 403
    assert guest_payload["error"]["code"] == "csrf_origin_rejected"
    assert "tcb_web_session" not in guest_resp.cookies


@pytest.mark.asyncio
async def test_guest_cannot_list_bots(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    session = isolated_web_auth_store.create_guest_session()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots", headers={"Authorization": f"Bearer {session.token}"})
            payload = await resp.json()

    assert resp.status == 403
    assert payload["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_default_member_can_configure_authorized_bot_cli_params_only(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    from bot.web.permission_store import BotPermissionStore

    permission_store = BotPermissionStore(temp_dir / ".web_permissions.json")
    permission_store.grant_bot_to_account(session.account.account_id, "main")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permission_store)
    headers = {"Authorization": f"Bearer {session.token}"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            chat_resp = await client.post("/api/bots/main/chat", json={"message": "hi"}, headers=headers)
            add_bot_resp = await client.post(
                "/api/admin/bots",
                json={"alias": "memberbot", "working_dir": str(temp_dir)},
                headers=headers,
            )
            cli_get_resp = await client.get("/api/bots/main/cli-params", headers=headers)
            cli_resp = await client.patch(
                "/api/bots/main/cli-params",
                json={"cli_type": "codex", "key": "yolo", "value": True},
                headers=headers,
            )
            cli_reset_resp = await client.post(
                "/api/bots/main/cli-params/reset",
                json={"cli_type": "codex"},
                headers=headers,
            )
            workdir_resp = await client.post(
                "/api/bots/main/workdir/mkdir",
                json={"parent_path": str(temp_dir), "name": "member-workdir"},
                headers=headers,
            )
            start_resp = await client.post("/api/admin/bots/main/start", headers=headers)
            stop_resp = await client.post("/api/admin/bots/main/stop", headers=headers)
            delete_resp = await client.delete("/api/admin/bots/main", headers=headers)
            admin_cli_resp = await client.patch(
                "/api/admin/bots/main/cli",
                json={"cli_type": "codex", "cli_path": "codex"},
                headers=headers,
            )
            env_resp = await client.get("/api/admin/env", headers=headers)
            update_resp = await client.get("/api/admin/update", headers=headers)

    assert chat_resp.status == 403
    assert add_bot_resp.status == 403
    assert cli_get_resp.status == 200
    assert cli_resp.status == 200
    assert cli_reset_resp.status == 200
    assert workdir_resp.status == 403
    assert start_resp.status == 403
    assert stop_resp.status == 403
    assert delete_resp.status == 403
    assert admin_cli_resp.status == 403
    assert env_resp.status == 403
    assert update_resp.status == 403


@pytest.mark.asyncio
async def test_guest_with_bot_access_cannot_configure_bot(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    session = isolated_web_auth_store.create_guest_session()
    from bot.web.permission_store import BotPermissionStore

    permission_store = BotPermissionStore(temp_dir / ".web_permissions.json")
    permission_store.grant_bot_to_account(session.account.account_id, "main")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permission_store)
    headers = {"Authorization": f"Bearer {session.token}"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            cli_resp = await client.get("/api/bots/main/cli-params", headers=headers)
            cluster_resp = await client.get("/api/admin/bots/main/cluster/schema", headers=headers)

    assert cli_resp.status == 403
    assert cluster_resp.status == 403


@pytest.mark.asyncio
async def test_member_explicit_capabilities_restore_host_level_actions(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    isolated_web_auth_store.update_member(
        session.account.account_id,
        capabilities=[*MEMBER_CAPABILITIES, CAP_CHAT_SEND, CAP_MANAGE_BOTS, CAP_MANAGE_CLI_PARAMS, CAP_CREATE_WORKDIR_DIRECTORY],
    )
    refreshed = isolated_web_auth_store.login_member("alice", "pw-123")
    from bot.web.permission_store import BotPermissionStore

    permission_store = BotPermissionStore(temp_dir / ".web_permissions.json")
    permission_store.grant_bot_to_account(refreshed.account.account_id, "main")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permission_store)
    monkeypatch.setattr("bot.web.server.run_chat", AsyncMock(return_value={"id": "msg-1", "content": "ok"}))
    headers = {"Authorization": f"Bearer {refreshed.token}"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            chat_resp = await client.post("/api/bots/main/chat", json={"message": "hi"}, headers=headers)
            add_bot_resp = await client.post(
                "/api/admin/bots",
                json={"alias": "memberbot", "working_dir": str(temp_dir)},
                headers=headers,
            )
            cli_resp = await client.patch(
                "/api/bots/main/cli-params",
                json={"cli_type": "codex", "key": "yolo", "value": True},
                headers=headers,
            )
            workdir_resp = await client.post(
                "/api/bots/main/workdir/mkdir",
                json={"parent_path": str(temp_dir), "name": "member-workdir"},
                headers=headers,
            )

    assert chat_resp.status == 200
    assert add_bot_resp.status == 200
    assert cli_resp.status == 200
    assert workdir_resp.status == 200


@pytest.mark.asyncio
async def test_member_cannot_read_unallowed_bot(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    await web_manager.add_bot("team", "", "codex", "codex", str(temp_dir), "cli")
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    from bot.web.permission_store import BotPermissionStore

    permission_store = BotPermissionStore(temp_dir / ".web_permissions.json")
    permission_store.grant_bot_to_account(session.account.account_id, "main")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permission_store)
    headers = {"Authorization": f"Bearer {session.token}"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            list_resp = await client.get("/api/bots", headers=headers)
            list_payload = await list_resp.json()
            team_resp = await client.get("/api/bots/team/history", headers=headers)
            team_payload = await team_resp.json()
            team_cli_resp = await client.get("/api/bots/team/cli-params", headers=headers)
            team_cli_payload = await team_cli_resp.json()
            team_cli_patch_resp = await client.patch(
                "/api/bots/team/cli-params",
                json={"cli_type": "codex", "key": "yolo", "value": True},
                headers=headers,
            )
            team_cli_patch_payload = await team_cli_patch_resp.json()
            team_cli_reset_resp = await client.post(
                "/api/bots/team/cli-params/reset",
                json={"cli_type": "codex"},
                headers=headers,
            )
            team_cli_reset_payload = await team_cli_reset_resp.json()
            team_cluster_resp = await client.get("/api/admin/bots/team/cluster/schema", headers=headers)
            team_cluster_payload = await team_cluster_resp.json()

    assert list_resp.status == 200
    assert [item["alias"] for item in list_payload["data"]] == ["main"]
    assert team_resp.status == 403
    assert team_payload["error"]["code"] == "bot_forbidden"
    assert team_cli_resp.status == 403
    assert team_cli_payload["error"]["code"] == "bot_forbidden"
    assert team_cli_patch_resp.status == 403
    assert team_cli_patch_payload["error"]["code"] == "bot_forbidden"
    assert team_cli_reset_resp.status == 403
    assert team_cli_reset_payload["error"]["code"] == "bot_forbidden"
    assert team_cluster_resp.status == 403
    assert team_cluster_payload["error"]["code"] == "bot_forbidden"


@pytest.mark.asyncio
async def test_member_with_bot_access_can_access_bot_scoped_cluster_routes(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    refreshed = isolated_web_auth_store.login_member("alice", "pw-123")
    from bot.web.permission_store import BotPermissionStore

    permission_store = BotPermissionStore(temp_dir / ".web_permissions.json")
    permission_store.grant_bot_to_account(refreshed.account.account_id, "main")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permission_store)
    monkeypatch.setattr("bot.web.server.prepare_cluster_setup", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr("bot.web.server.get_cluster_templates", lambda *_args, **_kwargs: {"items": []})
    headers = {"Authorization": f"Bearer {refreshed.token}"}
    bundle = {
        "id": "member_review",
        "name": "成员复核集群",
        "description": "",
        "cluster": {
            "enabled": True,
            "write_policy": "selected_agents",
            "conflict_policy": "snapshot_diff",
            "max_parallel_agents": 1,
            "default_timeout_seconds": 600,
            "model_tiers": {"low": "", "medium": "", "high": ""},
        },
        "agents": [
            {
                "id": "reviewer",
                "name": "复核",
                "system_prompt": "只读复核当前改动，输出风险和建议。",
                "enabled": True,
                "cluster": {
                    "allow_cluster": True,
                    "allow_write": False,
                    "session_policy": "ephemeral",
                    "timeout_seconds": 600,
                },
            }
        ],
    }

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            prepare_resp = await client.post("/api/admin/bots/main/cluster/setup/prepare", headers=headers)
            config_resp = await client.post(
                "/api/admin/bots/main/cluster/config",
                json={"cluster": {"enabled": True}},
                headers=headers,
            )
            templates_resp = await client.get("/api/admin/bots/main/cluster/templates", headers=headers)
            bot_schema_resp = await client.get("/api/admin/bots/main/cluster/schema", headers=headers)
            template_preview_resp = await client.post(
                "/api/admin/bots/main/cluster/templates/preview",
                json={"template_id": "full_test"},
                headers=headers,
            )
            template_apply_resp = await client.post(
                "/api/admin/bots/main/cluster/templates/apply",
                json={"template_id": "full_test", "confirm_overwrite_agents": True},
                headers=headers,
            )
            bundle_preview_resp = await client.post(
                "/api/admin/bots/main/cluster/config-bundle/preview",
                json={"bundle": bundle},
                headers=headers,
            )
            bundle_apply_resp = await client.post(
                "/api/admin/bots/main/cluster/config-bundle/apply",
                json={"bundle": bundle, "confirm_overwrite_agents": True},
                headers=headers,
            )
            schema_resp = await client.get("/api/admin/cluster/schema", headers=headers)

    assert prepare_resp.status == 200
    assert config_resp.status == 200
    assert templates_resp.status == 200
    assert bot_schema_resp.status == 200
    assert template_preview_resp.status == 200
    assert template_apply_resp.status == 200
    assert bundle_preview_resp.status == 200
    assert bundle_apply_resp.status == 200
    assert schema_resp.status == 403


@pytest.mark.asyncio
async def test_member_without_bot_access_cannot_access_bot_scoped_cluster_routes(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    isolated_web_auth_store.update_member(
        session.account.account_id,
        capabilities=[*MEMBER_CAPABILITIES, CAP_MANAGE_BOTS],
    )
    refreshed = isolated_web_auth_store.login_member("alice", "pw-123")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", __import__("bot.web.permission_store", fromlist=["BotPermissionStore"]).BotPermissionStore(temp_dir / ".web_permissions.json"))
    headers = {"Authorization": f"Bearer {refreshed.token}"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            responses = [
                await client.post("/api/admin/bots/main/cluster/setup/prepare", headers=headers),
                await client.post("/api/admin/bots/main/cluster/config", json={"cluster": {"enabled": True}}, headers=headers),
                await client.get("/api/admin/bots/main/cluster/schema", headers=headers),
                await client.post(
                    "/api/admin/bots/main/cluster/templates/preview",
                    json={"template_id": "full_test"},
                    headers=headers,
                ),
                await client.post(
                    "/api/admin/bots/main/cluster/templates/apply",
                    json={"template_id": "full_test", "confirm_overwrite_agents": True},
                    headers=headers,
                ),
                await client.post(
                    "/api/admin/bots/main/cluster/config-bundle/preview",
                    json={"bundle": {}},
                    headers=headers,
                ),
                await client.post(
                    "/api/admin/bots/main/cluster/config-bundle/apply",
                    json={"bundle": {}, "confirm_overwrite_agents": True},
                    headers=headers,
                ),
            ]
            payloads = [await response.json() for response in responses]

    assert [response.status for response in responses] == [403] * len(responses)
    assert {payload["error"]["code"] for payload in payloads} == {"bot_forbidden"}


@pytest.mark.asyncio
async def test_member_without_manage_bots_or_admin_ops_cannot_access_cluster_schema(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    headers = {"Authorization": f"Bearer {session.token}"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/cluster/schema", headers=headers)
            payload = await resp.json()

    assert resp.status == 403
    assert payload["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_debug_websocket_rejects_unallowed_bot_alias(
    web_manager: MultiBotManager,
    isolated_web_auth_store: WebAuthStore,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)
    await web_manager.add_bot("team", "", "codex", "codex", str(temp_dir), "cli")
    isolated_web_auth_store.register_codes_path.write_text(
        json.dumps({"items": [{"code": "INVITE-001", "disabled": False}]}),
        encoding="utf-8",
    )
    session = isolated_web_auth_store.register_member("alice", "pw-123", "INVITE-001")
    isolated_web_auth_store.update_member(
        session.account.account_id,
        capabilities=[*MEMBER_CAPABILITIES, CAP_DEBUG_EXEC],
    )
    refreshed = isolated_web_auth_store.login_member("alice", "pw-123")
    from bot.web.permission_store import BotPermissionStore

    permission_store = BotPermissionStore(temp_dir / ".web_permissions.json")
    permission_store.grant_bot_to_account(refreshed.account.account_id, "main")
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", permission_store)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with pytest.raises(WSServerHandshakeError) as exc_info:
                await client.ws_connect(
                    "/debug/ws?alias=team",
                    headers={"Authorization": f"Bearer {refreshed.token}"},
                )

    assert exc_info.value.status == 403


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


def test_build_bot_summary_returns_native_agent_config_without_password(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    import bot.config as config

    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_COMMAND", "pi")
    monkeypatch.setattr(config, "NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")
    monkeypatch.setattr("bot.native_agent.configuration.first_configured_model", lambda _config=None: None)
    web_manager.main_profile.default_execution_mode = "native_agent"
    web_manager.main_profile.supported_execution_modes = ["native_agent"]
    web_manager.main_profile.native_agent = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "pi_agent": "reviewer",
        "base_url": "https://cdn.codeflow.asia/v1",
        "api_key": "sk-secret-1234",
    }

    summary = build_bot_summary(web_manager, "main")

    assert summary["supported_execution_modes"] == ["native_agent"]
    assert summary["default_execution_mode"] == "native_agent"
    assert summary["native_agent"]["backend"] == "pi"
    assert summary["native_agent"]["pi_agent"] == "reviewer"
    assert "provider" not in summary["native_agent"]
    assert summary["native_agent"]["model"] == "anthropic/claude-sonnet-4-5"
    assert "api_key" not in summary["native_agent"]
    assert "sk-secret-1234" not in json.dumps(summary, ensure_ascii=False)


@pytest.mark.asyncio
async def test_admin_native_agent_config_routes_save_config(
    web_manager: MultiBotManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.native_agent import config_store

    settings_path = tmp_path / "settings.json"
    models_path = tmp_path / "models.json"
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(settings_path))
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr(
        "bot.web.api_service.run_pi_windows_preflight",
        lambda request, **_kwargs: {
            "ok": True,
            "code": "ok",
            "message": "Pi 运行前置检查通过",
            "platform": "nt",
            "checks": [],
        },
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            patch_resp = await client.patch(
                "/api/admin/native-agent/config",
                json={
                    "config": {
                        "backend": "pi",
                        "model": "jojocode/gpt-5.4",
                        "workspace_history_enabled": True,
                        "system_prompt": "全局提示词",
                        "providers": {
                            "jojocode": {
                                "baseUrl": "https://max.jojocode.com",
                                "api": "openai-responses",
                                "headers": {"User-Agent": "Codex CLI"},
                                "models": [
                                    {
                                        "id": "gpt-5.4",
                                        "contextWindow": 1_000_000,
                                        "maxTokens": 128_000,
                                    }
                                ],
                            }
                        },
                    }
                },
            )
            patch_payload = await patch_resp.json()
            get_resp = await client.get("/api/admin/native-agent/config")
            get_payload = await get_resp.json()

            assert patch_resp.status == 200
            assert patch_payload["data"]["needs_restart"] is True
            assert patch_payload["data"]["backend"] == "pi"
            assert patch_payload["data"]["config_path"] == str(settings_path)
            assert patch_payload["data"]["selected_model"] == "jojocode/gpt-5.4"
            assert patch_payload["data"]["workspace_history_enabled"] is True
            assert patch_payload["data"]["config"]["system_prompt"] == "全局提示词"
            assert "backup_path" not in patch_payload["data"]
            assert patch_payload["data"]["models"][0]["id"] == "jojocode/gpt-5.4"
            assert patch_payload["data"]["config"]["providers"]["jojocode"]["headers"] == {"User-Agent": "Codex CLI"}
            assert json.loads(settings_path.read_text(encoding="utf-8")) == {
                "backend": "pi",
                "model": "jojocode/gpt-5.4",
                "system_prompt": "全局提示词",
                "workspace_history_enabled": True,
            }
            saved_provider = json.loads(models_path.read_text(encoding="utf-8"))["providers"]["jojocode"]
            assert saved_provider["headers"] == {"User-Agent": "Codex CLI"}
            assert saved_provider["models"][0] == {
                "id": "gpt-5.4",
                "contextWindow": 1_000_000,
                "maxTokens": 128_000,
            }
            assert patch_payload["data"]["config"]["providers"] == json.loads(models_path.read_text(encoding="utf-8"))["providers"]
            assert get_resp.status == 200
            assert get_payload["data"]["models"][0]["context_window"] == 1_000_000
            assert get_payload["data"]["config"]["system_prompt"] == "全局提示词"
            assert get_payload["data"]["config"]["providers"]["jojocode"]["headers"] == {"User-Agent": "Codex CLI"}
            assert json.loads(settings_path.read_text(encoding="utf-8")) == {
                "backend": "pi",
                "model": "jojocode/gpt-5.4",
                "system_prompt": "全局提示词",
                "workspace_history_enabled": True,
            }

            clear_resp = await client.patch(
                "/api/admin/native-agent/config",
                json={
                    "config": {
                        "backend": "pi",
                        "model": "jojocode/gpt-5.4",
                        "workspace_history_enabled": True,
                        "providers": {
                            "jojocode": {
                                "baseUrl": "https://max.jojocode.com",
                                "api": "openai-responses",
                                "headers": {"User-Agent": "Codex CLI"},
                                "models": [
                                    {
                                        "id": "gpt-5.4",
                                        "contextWindow": 1_000_000,
                                        "maxTokens": 128_000,
                                    }
                                ],
                            }
                        },
                    }
                },
            )
            clear_payload = await clear_resp.json()
            clear_get_resp = await client.get("/api/admin/native-agent/config")
            clear_get_payload = await clear_get_resp.json()
            assert clear_resp.status == 200
            assert "system_prompt" not in clear_payload["data"]["config"]
            assert "system_prompt" not in json.loads(settings_path.read_text(encoding="utf-8"))
            assert "system_prompt" not in clear_get_payload["data"]["config"]

    assert "preflight" in get_payload["data"]


@pytest.mark.asyncio
async def test_admin_native_agent_preflight_route(
    web_manager: MultiBotManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.native_agent import config_store

    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("PI_AGENT_SETTINGS", str(settings_path))
    config_store.save_native_agent_config({"pi_command": "pi-from-config", "workspace_history_enabled": False})
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    captured: dict[str, str] = {}

    def fake_preflight(request, **_kwargs):
        captured["cwd"] = str(request.cwd)
        captured["pi_command"] = request.pi_command
        return {
            "ok": True,
            "code": "ok",
            "message": "Pi 运行前置检查通过",
            "platform": "nt",
            "checks": [],
        }

    monkeypatch.setattr("bot.web.api_service.run_pi_windows_preflight", fake_preflight)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get(
                "/api/admin/native-agent/preflight",
                params={"cwd": str(tmp_path), "pi_command": "C:/Program Files/Pi/pi.cmd"},
            )
            payload = await resp.json()

    assert resp.status == 200
    assert payload["data"]["ok"] is True
    assert captured["cwd"] == str(tmp_path)
    assert captured["pi_command"] == "C:/Program Files/Pi/pi.cmd"


@pytest.mark.asyncio
async def test_bot_native_agent_model_routes_save_selection(
    web_manager: MultiBotManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.native_agent import config_store

    monkeypatch.setenv("PI_AGENT_SETTINGS", str(tmp_path / "settings.json"))
    config_store.save_native_agent_config({
        "models": [
            {
                "id": "jojocode_max/gpt-5.4",
                "provider": "jojocode_max",
                "model": "gpt-5.4",
                "name": "gpt-5.4",
                "context_window": 1_000_000,
            },
            {
                "id": "jojocode_max/gpt-5.5",
                "provider": "jojocode_max",
                "model": "gpt-5.5",
                "name": "gpt-5.5",
                "reasoning_efforts": ["low", "medium", "high"],
                "default_reasoning_effort": "medium",
            },
        ]
    })
    web_manager.main_profile.supported_execution_modes = ["native_agent"]
    web_manager.main_profile.default_execution_mode = "native_agent"
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            list_resp = await client.get("/api/bots/main/native-agent/models")
            list_payload = await list_resp.json()
            patch_resp = await client.patch(
                "/api/bots/main/native-agent/model",
                json={"model": "jojocode_max/gpt-5.5", "reasoning_effort": "high"},
            )
            patch_payload = await patch_resp.json()

    assert list_resp.status == 200
    assert list_payload["data"]["selected_model"] == "jojocode_max/gpt-5.4"
    assert list_payload["data"]["selected_reasoning_effort"] == ""
    assert patch_resp.status == 200
    assert patch_payload["data"]["selected_model"] == "jojocode_max/gpt-5.5"
    assert patch_payload["data"]["selected_reasoning_effort"] == "high"
    assert patch_payload["data"]["bot"]["native_agent"]["model"] == "jojocode_max/gpt-5.5"
    assert patch_payload["data"]["bot"]["native_agent"]["reasoning_effort"] == "high"
    assert web_manager.main_profile.native_agent == {
        "model": "jojocode_max/gpt-5.5",
        "reasoning_effort": "high",
    }


@pytest.mark.asyncio
async def test_bot_native_agent_model_routes_validate_and_clear_reasoning_effort(
    web_manager: MultiBotManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.native_agent import config_store

    monkeypatch.setenv("PI_AGENT_SETTINGS", str(tmp_path / "settings.json"))
    config_store.save_native_agent_config({
        "models": [
            {
                "id": "jojocode_max/gpt-5.4",
                "provider": "jojocode_max",
                "model": "gpt-5.4",
                "name": "gpt-5.4",
                "reasoning_efforts": ["low", "high"],
            },
            {
                "id": "jojocode_max/gpt-plain",
                "provider": "jojocode_max",
                "model": "gpt-plain",
                "name": "gpt-plain",
            },
        ]
    })
    web_manager.main_profile.supported_execution_modes = ["native_agent"]
    web_manager.main_profile.default_execution_mode = "native_agent"
    web_manager.main_profile.native_agent = {
        "model": "jojocode_max/gpt-5.4",
        "reasoning_effort": "high",
    }
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            invalid_resp = await client.patch(
                "/api/bots/main/native-agent/model",
                json={"model": "jojocode_max/gpt-5.4", "reasoning_effort": "medium"},
            )
            list_resp = await client.get("/api/bots/main/native-agent/models")
            list_payload = await list_resp.json()
            clear_resp = await client.patch(
                "/api/bots/main/native-agent/model",
                json={"model": "jojocode_max/gpt-plain"},
            )
            clear_payload = await clear_resp.json()

    assert invalid_resp.status == 400
    assert list_resp.status == 200
    assert list_payload["data"]["selected_reasoning_effort"] == "high"
    assert clear_resp.status == 200
    assert clear_payload["data"]["selected_model"] == "jojocode_max/gpt-plain"
    assert clear_payload["data"]["selected_reasoning_effort"] == ""
    assert web_manager.main_profile.native_agent == {"model": "jojocode_max/gpt-plain"}


@pytest.mark.asyncio
async def test_admin_execution_route_updates_native_agent_config_and_hides_password(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    import bot.config as config

    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_COMMAND", "pi")
    monkeypatch.setattr(config, "NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")
    monkeypatch.setattr("bot.native_agent.configuration.first_configured_model", lambda _config=None: None)
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch(
                "/api/admin/bots/main/execution",
                json={
                    "supported_execution_modes": ["native_agent"],
                    "default_execution_mode": "native_agent",
                    "native_agent": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-5",
                        "pi_agent": "reviewer",
                        "base_url": "https://cdn.codeflow.asia/v1/",
                        "api_key": "sk-route-1234",
                    },
                },
            )
            payload = await resp.json()
            keep_resp = await client.patch(
                "/api/admin/bots/main/execution",
                json={
                    "supported_execution_modes": ["native_agent"],
                    "default_execution_mode": "native_agent",
                    "nativeAgent": {
                        "provider": "openai",
                        "model": "gpt-5",
                        "piAgent": "main",
                        "baseUrl": "https://api.example.test/v1/",
                    },
                },
            )
            keep_payload = await keep_resp.json()
            clear_resp = await client.patch(
                "/api/admin/bots/main/execution",
                json={
                    "supportedExecutionModes": ["native_agent"],
                    "defaultExecutionMode": "native_agent",
                    "nativeAgent": {
                        "provider": "codeflow",
                        "model": "gpt-5.1-codex",
                        "piAgent": "main",
                        "baseUrl": "https://cdn.codeflow.asia/v1",
                        "clearApiKey": True,
                    },
                },
            )
            clear_payload = await clear_resp.json()

    assert resp.status == 200
    assert payload["data"]["bot"]["default_execution_mode"] == "native_agent"
    assert payload["data"]["bot"]["supported_execution_modes"] == ["native_agent"]
    assert payload["data"]["bot"]["native_agent"]["pi_agent"] == "reviewer"
    assert payload["data"]["bot"]["native_agent"]["backend"] == "pi"
    assert "api_key" not in payload["data"]["bot"]["native_agent"]
    assert "sk-route-1234" not in json.dumps(payload, ensure_ascii=False)
    assert keep_resp.status == 200
    assert keep_payload["data"]["bot"]["native_agent"]["pi_agent"] == "main"
    assert "sk-route-1234" not in json.dumps(keep_payload, ensure_ascii=False)
    assert clear_resp.status == 200
    assert clear_payload["data"]["bot"]["native_agent"]["pi_agent"] == "main"
    assert web_manager.main_profile.native_agent == {
        "pi_agent": "main",
    }


@pytest.mark.asyncio
async def test_admin_execution_route_ignores_bot_scoped_native_agent_api_key(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    import bot.config as config

    monkeypatch.setattr(config, "NATIVE_AGENT_PROVIDER", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_MODEL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_BASE_URL", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_API_KEY", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_AGENT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_PI_COMMAND", "pi")
    monkeypatch.setattr(config, "NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", True)
    monkeypatch.setattr(config, "NATIVE_AGENT_REASONING_EFFORT", "")
    monkeypatch.setattr(config, "NATIVE_AGENT_THINKING_DEPTH", "")
    monkeypatch.setattr("bot.native_agent.configuration.first_configured_model", lambda _config=None: None)
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    web_manager.main_profile.native_agent = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "pi_agent": "reviewer",
        "base_url": "https://cdn.codeflow.asia/v1",
        "api_key": "sk-old-1234",
    }

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch(
                "/api/admin/bots/main/execution",
                json={
                    "supported_execution_modes": ["native_agent"],
                    "default_execution_mode": "native_agent",
                    "native_agent": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-5",
                        "pi_agent": "reviewer",
                        "base_url": "https://cdn.codeflow.asia/v1",
                        "api_key": "sk-new-5678",
                    },
                },
            )
            payload = await resp.json()

    assert resp.status == 200
    assert payload["data"]["bot"]["native_agent"]["pi_agent"] == "reviewer"
    assert "api_key" not in payload["data"]["bot"]["native_agent"]
    assert "sk-new-5678" not in json.dumps(payload, ensure_ascii=False)
    assert web_manager.main_profile.native_agent == {"pi_agent": "reviewer"}
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
    second_sha = _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second\n\nbody line")
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
    assert result["nodes"][0]["message"] == "second\n\nbody line"
    assert result["nodes"][0]["graph"]["column"] == 0
    assert result["nodes"][0]["graph"]["width"] >= 1
    assert result["nodes"][1]["parents"] == []


def test_git_commit_graph_message_separator_does_not_break_records(
    web_manager: MultiBotManager,
    temp_dir: Path,
):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    first_sha = _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    second_sha = _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second\n\nbody line")
    _use_repo(web_manager, repo_dir)

    result = get_git_commit_graph(web_manager, "main", 1001, scope="current")

    assert [node["hash"] for node in result["nodes"]] == [second_sha, first_sha]
    assert result["nodes"][0]["subject"] == "second"
    assert result["nodes"][0]["message"] == "second\n\nbody line"


def test_git_commit_graph_page_uses_single_log_call(monkeypatch: pytest.MonkeyPatch, web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    _commit_repo_file(repo_dir, "tracked.txt", "one\n", "first")
    _commit_repo_file(repo_dir, "tracked.txt", "two\n", "second")
    _use_repo(web_manager, repo_dir)

    calls: list[list[str]] = []
    import bot.web.git_service as git_service_module

    real_run_git = git_service_module._run_git

    def traced_run_git(repo_root: str, args: list[str], *, check: bool = True, env=None):
        calls.append(list(args))
        return real_run_git(repo_root, args, check=check, env=env)

    monkeypatch.setattr(git_service_module, "_run_git", traced_run_git)

    result = get_git_commit_graph(web_manager, "main", 1001, scope="current", limit=1)

    assert result["nodes"]
    assert sum(1 for args in calls if args and args[0] == "log") == 1
    assert all(not args or args[0] != "show" for args in calls)


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
    assert read_payload["error"]["code"] == "bot_forbidden"
    assert write_resp.status == 403
    assert write_payload["error"]["code"] == "bot_forbidden"
    assert rebuild_resp.status == 403
    assert rebuild_payload["error"]["code"] == "bot_forbidden"
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
async def test_chat_stream_route_returns_ag_ui_sse_when_protocol_requested(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_stream_chat(manager, alias, user_id, message, **kwargs):
        assert kwargs["protocol"] == "ag-ui"
        yield {
            "type": "ag_ui",
            "event": core.RunStartedEvent(threadId="conv-1", runId="run-1"),
        }
        yield {
            "type": "ag_ui",
            "event": core.TextMessageStartEvent(messageId="msg-1"),
        }
        yield {
            "type": "ag_ui",
            "event": core.TextMessageContentEvent(messageId="msg-1", delta="hello"),
        }
        yield {
            "type": "ag_ui",
            "event": core.TextMessageEndEvent(messageId="msg-1"),
        }
        yield {
            "type": "done",
            "output": "hello",
            "message": {"id": "msg-1", "role": "assistant", "content": "hello", "meta": {}},
            "elapsed_seconds": 0,
            "returncode": 0,
        }

    event_adapter = TypeAdapter(core.Event)
    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.stream_chat", fake_stream_chat):
                resp = await client.post("/api/bots/main/chat/stream?protocol=ag-ui", json={"message": "hi"})
                assert resp.status == 200
                body = await resp.text()

    assert "event:" not in body
    payloads = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        assert block.startswith("data: ")
        payloads.append(json.loads(block[len("data: "):]))
    events = [event_adapter.validate_python(item) for item in payloads]
    assert [event.type for event in events] == [
        core.EventType.RUN_STARTED,
        core.EventType.TEXT_MESSAGE_START,
        core.EventType.TEXT_MESSAGE_CONTENT,
        core.EventType.TEXT_MESSAGE_END,
    ]


@pytest.mark.parametrize(
    ("capabilities", "expected_allow_unsafe"),
    [
        ({CAP_CHAT_SEND}, False),
        ({CAP_CHAT_SEND, CAP_RUN_UNSAFE_CLI}, True),
    ],
)
@pytest.mark.asyncio
async def test_chat_stream_route_passes_ag_ui_protocol_and_unsafe_capability(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    capabilities: set[str],
    expected_allow_unsafe: bool,
):
    captured: dict[str, Any] = {}

    def fake_auth(_self, _request):
        return AuthContext(
            user_id=1001,
            token_used=True,
            account_id="local-admin",
            username="local-admin",
            role="owner",
            capabilities=set(capabilities),
            is_local_admin=True,
        )

    async def fake_stream_chat(manager, alias, user_id, message, **kwargs):
        captured.update(kwargs)
        yield {
            "type": "done",
            "output": "hello",
            "message": {"id": "msg-1", "role": "assistant", "content": "hello", "meta": {}},
            "elapsed_seconds": 0,
            "returncode": 0,
        }

    monkeypatch.setattr("bot.web.server.WebApiServer._auth_context", fake_auth)
    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.stream_chat", fake_stream_chat):
                resp = await client.post("/api/bots/main/chat/stream?protocol=ag-ui", json={"message": "hi"})
                await resp.text()

    assert resp.status == 200
    assert captured["protocol"] == "ag-ui"
    assert captured["allow_unsafe_cli"] is expected_allow_unsafe


@pytest.mark.asyncio
async def test_terminal_session_routes_and_websocket_attach(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_TERMINAL_SHELL_PATH", "")

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
                headers = {"Authorization": "Bearer secret"}
                resp = await client.get(f"/api/terminal/session?owner_id={owner_id}", headers=headers)
                assert resp.status == 200
                payload = await resp.json()
                assert payload["data"]["started"] is False
                assert payload["data"]["connection_text"] == "未启动"

                rebuild_resp = await client.post(
                    "/api/terminal/session/rebuild",
                    json={"owner_id": owner_id, "cwd": str(temp_dir), "shell": "bash"},
                    headers=headers,
                )
                assert rebuild_resp.status == 200
                rebuild_payload = await rebuild_resp.json()
                assert rebuild_payload["data"]["started"] is True
                assert rebuild_payload["data"]["connection_text"] == "运行中"

                ws = await client.ws_connect("/terminal/ws", headers=headers)
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
async def test_terminal_rebuild_uses_configured_shell_path(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_TERMINAL_SHELL_PATH", "/usr/bin/zsh")

    state: dict[str, object] = {}

    class FakeProcess:
        is_pty = False
        pid = 4322

        def read(self, timeout: int = 1000) -> bytes:
            return b""

        def write(self, data: bytes) -> None:
            pass

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
        return FakeProcess()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.terminal_manager.create_shell_process", side_effect=fake_create_shell_process):
                resp = await client.post(
                    "/api/terminal/session/rebuild",
                    json={"owner_id": "configured-shell", "cwd": str(temp_dir), "shell": "bash"},
                    headers={"Authorization": "Bearer secret"},
                )

                assert resp.status == 200
                assert state["shell_type"] == "/usr/bin/zsh"
                assert state["cwd"] == str(temp_dir)


@pytest.mark.asyncio
async def test_terminal_websocket_closes_when_terminal_session_closes(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    class FakeProcess:
        is_pty = True
        pid = 4330

        def read(self, timeout: int = 1000) -> bytes:
            return b""

        def write(self, data: bytes) -> None:
            pass

        def isalive(self) -> bool:
            return True

        def terminate(self) -> None:
            pass

        def close(self) -> None:
            pass

    def fake_create_shell_process(
        shell_type: str,
        cwd: str,
        use_pty: bool = True,
        cols: int | None = None,
        rows: int | None = None,
    ):
        return FakeProcess()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.terminal_manager.create_shell_process", side_effect=fake_create_shell_process), \
                 patch("bot.web.server.get_default_shell", return_value="bash"):
                owner_id = "close-ws-terminal"
                headers = {"Authorization": "Bearer secret"}
                rebuild_resp = await client.post(
                    "/api/terminal/session/rebuild",
                    json={"owner_id": owner_id, "cwd": str(temp_dir), "shell": "auto"},
                    headers=headers,
                )
                ws = await client.ws_connect("/terminal/ws", headers=headers)
                await ws.send_json({"owner_id": owner_id})
                first_message = await ws.receive_json()

                close_resp = await client.post(
                    "/api/terminal/session/close",
                    json={"owner_id": owner_id},
                    headers=headers,
                )
                close_message = await asyncio.wait_for(ws.receive(), timeout=2)

    assert rebuild_resp.status == 200
    assert first_message == {"pty_mode": True, "connection_text": "运行中"}
    assert close_resp.status == 200
    assert close_message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED}


@pytest.mark.asyncio
async def test_diag_slow_request_skips_websocket_connections(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("TCB_DIAG_ENABLED", "1")
    monkeypatch.setenv("TCB_DIAG_SLOW_MS", "1")
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def slow_http(_request: web.Request) -> web.Response:
        await asyncio.sleep(0.01)
        return web.json_response({"ok": True})

    app = WebApiServer(web_manager)._build_app()
    app.router.add_get("/__test/slow-http", slow_http)

    caplog.set_level(logging.WARNING, logger="bot.web.server")
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            headers = {"Authorization": "Bearer secret"}
            ws = await client.ws_connect("/api/notifications/ws", headers=headers)
            hello = await ws.receive_json()
            assert hello["type"] == "hello"
            await asyncio.sleep(0.01)
            await ws.close()

            response = await client.get("/__test/slow-http", headers=headers)
            assert response.status == 200

    messages = [record.getMessage() for record in caplog.records]
    assert not any("event=web_request" in message and "route=/api/notifications/ws" in message for message in messages)
    assert any("event=web_request" in message and "route=/__test/slow-http" in message for message in messages)


@pytest.mark.asyncio
async def test_terminal_rebuild_auto_uses_default_shell_without_configured_path(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_TERMINAL_SHELL_PATH", "")

    state: dict[str, object] = {}

    class FakeProcess:
        is_pty = False
        pid = 4323

        def read(self, timeout: int = 1000) -> bytes:
            return b""

        def write(self, data: bytes) -> None:
            pass

        def isalive(self) -> bool:
            return True

        def terminate(self) -> None:
            pass

        def close(self) -> None:
            pass

    def fake_create_shell_process(
        shell_type: str,
        cwd: str,
        use_pty: bool = True,
        cols: int | None = None,
        rows: int | None = None,
    ):
        state["shell_type"] = shell_type
        return FakeProcess()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.terminal_manager.create_shell_process", side_effect=fake_create_shell_process), \
                 patch("bot.web.server.get_default_shell", return_value="bash"):
                resp = await client.post(
                    "/api/terminal/session/rebuild",
                    json={"owner_id": "default-shell", "cwd": str(temp_dir), "shell": "auto"},
                    headers={"Authorization": "Bearer secret"},
                )

                assert resp.status == 200
                assert state["shell_type"] == "bash"


@pytest.mark.asyncio
async def test_terminal_rebuild_reports_invalid_shell_without_starting_session(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_TERMINAL_SHELL_PATH", "")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            owner_id = "missing-shell"
            headers = {"Authorization": "Bearer secret"}
            resp = await client.post(
                "/api/terminal/session/rebuild",
                json={"owner_id": owner_id, "cwd": str(temp_dir), "shell": "definitely-missing-shell"},
                headers=headers,
            )
            payload = await resp.json()
            session_resp = await client.get(f"/api/terminal/session?owner_id={owner_id}", headers=headers)
            session_payload = await session_resp.json()

    assert resp.status == 400
    assert payload["error"]["code"] == "terminal_launch_failed"
    assert "未找到" in payload["error"]["message"]
    assert session_payload["data"]["started"] is False


@pytest.mark.asyncio
async def test_terminal_websocket_reports_not_running_before_attach(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            ws = await client.ws_connect("/terminal/ws", headers={"Authorization": "Bearer secret"})
            await ws.send_json({"owner_id": "not-started"})
            message = await ws.receive_json()
            await ws.close()

    assert message == {"error": "终端未启动"}


@pytest.mark.asyncio
async def test_terminal_websocket_accepts_configured_node_base_path(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "/node/local")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            ws = await client.ws_connect("/node/local/terminal/ws", headers={"Authorization": "Bearer secret"})
            await ws.send_json({"owner_id": "not-started"})
            message = await ws.receive_json()
            await ws.close()

            root_response = await client.get("/node/other/terminal/ws")
            root_text = await root_response.text()

    assert message == {"error": "终端未启动"}
    assert root_response.status == 404
    assert "Terminal WebSocket route not found" in root_text


@pytest.mark.asyncio
async def test_terminal_websocket_probe_reports_base_path_and_origin(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "/node/local")
    monkeypatch.setattr("bot.web.server.WEB_PUBLIC_URL", "")
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_URL", "")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.get(
                "/node/local/terminal/ws-probe",
                headers={
                    "Authorization": "Bearer secret",
                    "Origin": "https://proxy.example.test",
                    "Host": "127.0.0.1:8765",
                    "X-Forwarded-Host": "proxy.example.test",
                    "X-Forwarded-Proto": "https",
                },
            )
            payload = await response.json()

            root_response = await client.get("/node/other/terminal/ws-probe")
            root_text = await root_response.text()

    assert response.status == 200
    assert payload["data"]["path"] == "/node/local/terminal/ws-probe"
    assert payload["data"]["configured_base_path"] == "/node/local"
    assert payload["data"]["has_token"] is True
    assert payload["data"]["auth_status"] == "ok"
    assert payload["data"]["origin_allowed"] is True
    assert root_response.status == 404
    assert "Terminal WebSocket route not found" in root_text


@pytest.mark.asyncio
async def test_terminal_http_stream_and_input_fallback(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    state: dict[str, object] = {"writes": [], "resizes": []}
    output_queue: queue.Queue[bytes] = queue.Queue()

    class FakeProcess:
        is_pty = True
        pid = 4325

        def read(self, timeout: int = 1000) -> bytes:
            try:
                return output_queue.get(timeout=timeout / 1000)
            except queue.Empty:
                return b""

        def write(self, data: bytes) -> None:
            cast(list[bytes], state["writes"]).append(data)

        def resize(self, cols: int, rows: int) -> bool:
            cast(list[tuple[int, int]], state["resizes"]).append((cols, rows))
            return True

        def isalive(self) -> bool:
            return True

        def terminate(self) -> None:
            pass

        def close(self) -> None:
            pass

    def fake_create_shell_process(
        shell_type: str,
        cwd: str,
        use_pty: bool = True,
        cols: int | None = None,
        rows: int | None = None,
    ):
        return FakeProcess()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.terminal_manager.create_shell_process", side_effect=fake_create_shell_process), \
                 patch("bot.web.server.get_default_shell", return_value="bash"):
                owner_id = "http-fallback"
                headers = {"Authorization": "Bearer secret"}
                rebuild_resp = await client.post(
                    "/api/terminal/session/rebuild",
                    json={"owner_id": owner_id, "cwd": str(temp_dir), "shell": "auto"},
                    headers=headers,
                )
                stream_resp = await client.get(
                    f"/api/terminal/session/stream?owner_id={owner_id}",
                    headers=headers,
                    timeout=5,
                )
                ready = await stream_resp.content.readline()
                ready_data = await stream_resp.content.readline()
                await stream_resp.content.readline()

                input_resp = await client.post(
                    "/api/terminal/session/input",
                    json={"owner_id": owner_id, "data": "echo hi\r\n"},
                    headers=headers,
                )
                resize_resp = await client.post(
                    "/api/terminal/session/input",
                    json={"owner_id": owner_id, "type": "resize", "cols": 120, "rows": 32},
                    headers=headers,
                )

                output_queue.put(b"hello\n")
                output_event = await stream_resp.content.readline()
                output_data = await stream_resp.content.readline()
                stream_resp.close()

    assert rebuild_resp.status == 200
    assert stream_resp.status == 200
    assert ready == b"event: ready\n"
    assert json.loads(ready_data.decode("utf-8").removeprefix("data: "))["pty_mode"] is True
    assert input_resp.status == 200
    assert resize_resp.status == 200
    assert cast(list[bytes], state["writes"]) == [b"echo hi\r\n"]
    assert cast(list[tuple[int, int]], state["resizes"]) == [(120, 32)]
    assert output_event == b"event: output\n"
    assert json.loads(output_data.decode("utf-8").removeprefix("data: "))["data"] == base64.b64encode(b"hello\n").decode("ascii")


@pytest.mark.asyncio
async def test_terminal_websocket_allows_configured_public_url_origin(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_PUBLIC_URL", "http://proxy.example.test/node/local")
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_URL", "")

    state: dict[str, object] = {"writes": []}

    class FakeProcess:
        is_pty = True
        pid = 4324

        def read(self, timeout: int = 1000) -> bytes:
            return b""

        def write(self, data: bytes) -> None:
            cast(list[bytes], state["writes"]).append(data)

        def isalive(self) -> bool:
            return True

        def terminate(self) -> None:
            pass

        def close(self) -> None:
            pass

    def fake_create_shell_process(
        shell_type: str,
        cwd: str,
        use_pty: bool = True,
        cols: int | None = None,
        rows: int | None = None,
    ):
        return FakeProcess()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.terminal_manager.create_shell_process", side_effect=fake_create_shell_process), \
                 patch("bot.web.server.get_default_shell", return_value="bash"):
                owner_id = "public-origin"
                headers = {"Authorization": "Bearer secret"}
                rebuild_resp = await client.post(
                    "/api/terminal/session/rebuild",
                    json={"owner_id": owner_id, "cwd": str(temp_dir), "shell": "auto"},
                    headers=headers,
                )
                ws = await client.ws_connect(
                    "/terminal/ws",
                    headers={**headers, "Origin": "http://proxy.example.test"},
                )
                await ws.send_json({"owner_id": owner_id})
                first_message = await ws.receive_json()
                await ws.close()

    assert rebuild_resp.status == 200
    assert first_message == {"pty_mode": True, "connection_text": "运行中"}


@pytest.mark.asyncio
async def test_terminal_websocket_allows_forwarded_host_origin(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_PUBLIC_URL", "")
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_URL", "")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            ws = await client.ws_connect(
                "/terminal/ws",
                headers={
                    "Authorization": "Bearer secret",
                    "Origin": "https://proxy.example.test",
                    "Host": "127.0.0.1:8765",
                    "X-Forwarded-Host": "proxy.example.test",
                    "X-Forwarded-Proto": "https",
                },
            )
            await ws.send_json({"owner_id": "not-started"})
            message = await ws.receive_json()
            await ws.close()

    assert message == {"error": "终端未启动"}


@pytest.mark.asyncio
async def test_terminal_websocket_rejects_unmatched_forwarded_host_origin(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_PUBLIC_URL", "")
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_URL", "")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            ws = await client.ws_connect(
                "/terminal/ws",
                headers={
                    "Authorization": "Bearer secret",
                    "Origin": "https://proxy.example.test",
                    "Host": "127.0.0.1:8765",
                    "X-Forwarded-Host": "other.example.test",
                    "X-Forwarded-Proto": "https",
                },
            )
            await ws.send_json({"owner_id": "not-started"})
            message = await ws.receive_json()
            await ws.close()

    assert message == {"error": "终端未启动"}


@pytest.mark.asyncio
async def test_terminal_websocket_rejects_unmatched_forwarded_host_without_token(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_PUBLIC_URL", "")
    monkeypatch.setattr("bot.web.server.WEB_FIXED_PUBLIC_FORWARD_URL", "")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with pytest.raises(WSServerHandshakeError) as exc_info:
                await client.ws_connect(
                    "/terminal/ws",
                    headers={
                        "Origin": "https://proxy.example.test",
                        "Host": "127.0.0.1:8765",
                        "X-Forwarded-Host": "other.example.test",
                        "X-Forwarded-Proto": "https",
                    },
                )

    assert exc_info.value.status == 401


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


def test_native_agent_conversation_api_uses_native_provider(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)

    created = create_conversation(web_manager, "main", 1001, "原生任务", execution_mode="native_agent")
    conversation_id = created["conversation"]["id"]
    ChatStore(tmp_path).set_conversation_native_session(
        conversation_id,
        "native-1",
        {"cwd": str(tmp_path), "model_id": "anthropic/sonnet", "pi_agent": "reviewer"},
    )

    assert created["conversation"]["native_provider"] == "native_agent"
    assert created["conversation"]["execution_mode"] == "native_agent"

    with session._lock:
        session.native_agent_session_id = "native-old"
    session.persist()

    selected = select_conversation(web_manager, "main", 1001, conversation_id, execution_mode="native_agent")

    assert selected["conversation"]["execution_mode"] == "native_agent"
    assert session.native_agent_session_id == "native-1"
    assert selected["conversation"]["native_session_meta"]["model_id"] == "anthropic/sonnet"
    with pytest.raises(WebApiError) as exc_info:
        select_conversation(web_manager, "main", 1001, conversation_id, execution_mode="cli")
    assert exc_info.value.code == "conversation_execution_mode_mismatch"


def test_native_agent_select_and_delete_sync_pi_session_store(web_manager: MultiBotManager, tmp_path: Path):
    from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key

    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    created = create_conversation(web_manager, "main", 1001, "原生任务", execution_mode="native_agent")
    conversation_id = created["conversation"]["id"]
    ChatStore(tmp_path).set_conversation_native_session(conversation_id, "sqlite-native", {"cwd": str(tmp_path)})
    key = pi_session_key(cwd=str(tmp_path), bot_id=session.bot_id, user_id=session.user_id, conversation_id=conversation_id)
    pi_store = PiSessionStore()
    pi_store.upsert(PiSessionRecord(
        key=key,
        cwd=str(tmp_path),
        conversation_id=conversation_id,
        pi_session_id="pi-native",
        linear_index=3,
        workspace_history_head="head-3",
    ))

    selected = select_conversation(web_manager, "main", 1001, conversation_id, execution_mode="native_agent")

    assert session.native_agent_session_id == "pi-native"
    assert selected["conversation"]["workspace_history_head"] == "head-3"
    assert selected["conversation"]["linear_index"] == 3
    assert "changed_paths" not in json.dumps(selected, ensure_ascii=False)

    result = delete_conversation(
        web_manager,
        "main",
        1001,
        conversation_id,
        execution_mode="native_agent",
        delete_native_session=True,
    )

    assert result["native_session_cleared"] is True
    assert pi_store.get(key) is None


def test_native_agent_select_hides_rollback_after_binding_invalidation(web_manager: MultiBotManager, tmp_path: Path):
    from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key

    web_manager.main_profile.working_dir = str(tmp_path)
    profile = web_manager.main_profile
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    history = ChatHistoryService(ChatStore(tmp_path), native_provider_filter="native_agent")
    handle = history.start_turn(profile=profile, session=session, user_text="一", native_provider="native_agent")
    history.complete_turn(handle, content="一回", completion_state="completed", native_session_id="pi-old")
    history.store.update_turn_workspace_history(handle.turn_id, "head-1", 1)
    key = pi_session_key(cwd=str(tmp_path), bot_id=session.bot_id, user_id=session.user_id, conversation_id=handle.conversation_id)
    pi_store = PiSessionStore()
    pi_store.upsert(PiSessionRecord(
        key=key,
        cwd=str(tmp_path),
        conversation_id=handle.conversation_id,
        pi_session_id="pi-old",
        session_meta={
            "cwd": str(tmp_path),
            "model_id": "anthropic/claude-haiku-3",
            "pi_agent": "main",
            "reasoning_effort": "low",
        },
        linear_index=1,
        workspace_history_head="head-1",
    ))

    history.store.invalidate_conversation_workspace_history(handle.conversation_id)
    pi_store.invalidate_binding(key, "binding changed")
    selected = select_conversation(web_manager, "main", 1001, handle.conversation_id, execution_mode="native_agent")

    assert selected["conversation"]["rollback_supported"] is False
    assert selected["conversation"]["workspace_history_head"] == ""
    assert selected["messages"]


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


def test_history_and_trace_are_isolated_by_execution_mode(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    profile = web_manager.main_profile
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    history = ChatHistoryService(ChatStore(tmp_path))

    cli_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="CLI",
        native_provider="codex",
    )
    history.append_trace_event(cli_handle, {"kind": "tool_call", "summary": "cli trace"})
    cli_message = history.complete_turn(
        cli_handle,
        content="CLI 回复",
        completion_state="completed",
        native_session_id="thread-1",
    )

    native_handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="Native",
        native_provider="native_agent",
    )
    history.complete_turn(
        native_handle,
        content="原生回复",
        completion_state="completed",
        native_session_id="native-1",
    )

    native_history = get_history(web_manager, "main", 1001, execution_mode="native_agent")
    cli_history_when_native_active = get_history(web_manager, "main", 1001, execution_mode="cli")
    native_overview = get_overview(web_manager, "main", 1001, execution_mode="native_agent")
    cli_list = list_conversations(web_manager, "main", 1001, execution_mode="cli")
    native_list = list_conversations(web_manager, "main", 1001, execution_mode="native_agent")

    assert [item["content"] for item in native_history["items"]] == ["Native", "原生回复"]
    assert cli_history_when_native_active["items"] == []
    assert native_overview["session"]["history_count"] == 2
    assert [item["id"] for item in cli_list["items"]] == [cli_handle.conversation_id]
    assert [item["id"] for item in native_list["items"]] == [native_handle.conversation_id]

    with pytest.raises(WebApiError) as exc_info:
        get_history_trace(
            web_manager,
            "main",
            1001,
            str(cli_message["id"]),
            execution_mode="native_agent",
        )
    assert exc_info.value.code == "trace_not_found"

    select_conversation(
        web_manager,
        "main",
        1001,
        cli_handle.conversation_id,
        execution_mode="cli",
    )

    assert get_history(web_manager, "main", 1001, execution_mode="native_agent")["items"] == []
    assert [item["content"] for item in get_history(web_manager, "main", 1001, execution_mode="cli")["items"]] == [
        "CLI",
        "CLI 回复",
    ]


def test_history_user_message_does_not_expose_native_trace_meta(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    profile = web_manager.main_profile
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    history = ChatHistoryService(ChatStore(tmp_path), native_provider_filter="native_agent")

    handle = history.start_turn(
        profile=profile,
        session=session,
        user_text="Native",
        native_provider="native_agent",
    )
    history.append_trace_event(handle, {"kind": "tool_call", "summary": "native trace", "call_id": "call_1"})
    history.complete_turn(
        handle,
        content="原生回复",
        completion_state="completed",
        native_session_id="native-1",
    )

    user_message, assistant_message = get_history(web_manager, "main", 1001, execution_mode="native_agent")["items"]

    assert user_message["role"] == "user"
    assert "trace_count" not in user_message["meta"]
    assert "native_source" not in user_message["meta"]
    assert assistant_message["meta"]["trace_count"] == 1
    assert assistant_message["meta"]["native_source"]["provider"] == "native_agent"


def test_delete_all_conversations_scopes_agent_and_execution_mode(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    web_manager.main_profile.agents = [AgentProfile(id="reviewer", name="审查")]
    main_session = get_session_for_alias(web_manager, "main", 1001)
    main_session.working_dir = str(tmp_path)
    _profile, _agent, reviewer_session = get_chat_session_for_alias(web_manager, "main", 1001, "reviewer")
    reviewer_session.working_dir = str(tmp_path)

    main_cli = create_conversation(web_manager, "main", 1001, "主 CLI", execution_mode="cli")
    create_conversation(web_manager, "main", 1001, "主 Native", execution_mode="native_agent")
    reviewer_cli = create_conversation(web_manager, "main", 1001, "审查 CLI", agent_id="reviewer", execution_mode="cli")

    with main_session._lock:
        main_session.codex_session_id = "thread-1"
        main_session.native_agent_session_id = "native-1"
    main_session.persist()

    result = delete_all_conversations(
        web_manager,
        "main",
        1001,
        agent_id="main",
        execution_mode="native_agent",
        delete_native_session=True,
    )

    assert result["deleted_count"] == 1
    assert result["native_session_cleared"] is True
    assert main_session.native_agent_session_id is None
    assert main_session.codex_session_id == "thread-1"
    assert [item["id"] for item in list_conversations(web_manager, "main", 1001, execution_mode="cli")["items"]] == [
        main_cli["conversation"]["id"]
    ]
    assert list_conversations(web_manager, "main", 1001, execution_mode="native_agent")["items"] == []
    assert [item["id"] for item in list_conversations(web_manager, "main", 1001, agent_id="reviewer", execution_mode="cli")["items"]] == [
        reviewer_cli["conversation"]["id"]
    ]

    reviewer_result = delete_all_conversations(
        web_manager,
        "main",
        1001,
        agent_id="reviewer",
        execution_mode="cli",
    )

    assert reviewer_result["deleted_count"] == 1
    assert [item["id"] for item in list_conversations(web_manager, "main", 1001, execution_mode="cli")["items"]] == [
        main_cli["conversation"]["id"]
    ]
    assert list_conversations(web_manager, "main", 1001, agent_id="reviewer", execution_mode="cli")["items"] == []


def test_delete_active_native_conversation_clears_runtime_native_session(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)

    created = create_conversation(web_manager, "main", 1001, "原生", execution_mode="native_agent")
    conversation_id = created["conversation"]["id"]
    ChatStore(tmp_path).set_conversation_native_session(conversation_id, "native-1", {"cwd": str(tmp_path)})
    select_conversation(web_manager, "main", 1001, conversation_id, execution_mode="native_agent")

    assert session.native_agent_session_id == "native-1"

    result = delete_conversation(web_manager, "main", 1001, conversation_id, execution_mode="native_agent")

    assert result["native_session_cleared"] is True
    assert session.active_conversation_id is None
    assert session.native_agent_session_id is None


@pytest.mark.asyncio
async def test_native_agent_history_rollback_discards_forward_turns(
    web_manager: MultiBotManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key
    from bot.native_agent.pi_workspace_history import WorkspaceHistoryStatus

    web_manager.main_profile.working_dir = str(tmp_path)
    profile = web_manager.main_profile
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    history = ChatHistoryService(ChatStore(tmp_path), native_provider_filter="native_agent")
    first = history.start_turn(profile=profile, session=session, user_text="一", native_provider="native_agent")
    history.complete_turn(first, content="一回", completion_state="completed", native_session_id="pi-native")
    history.store.update_turn_workspace_history(first.turn_id, "head-1", 1)
    second = history.start_turn(profile=profile, session=session, user_text="二", native_provider="native_agent")
    history.complete_turn(second, content="二回", completion_state="completed", native_session_id="pi-native")
    history.store.update_turn_workspace_history(second.turn_id, "head-2", 2)
    key = pi_session_key(cwd=str(tmp_path), bot_id=session.bot_id, user_id=session.user_id, conversation_id=first.conversation_id)
    pi_store = PiSessionStore()
    pi_store.upsert(PiSessionRecord(key=key, cwd=str(tmp_path), conversation_id=first.conversation_id, pi_session_id="pi-native"))
    pi_store.update_after_completed_turn(key, pi_session_id="pi-native", turn_id=first.turn_id, workspace_history_head="head-1")
    pi_store.update_after_completed_turn(key, pi_session_id="pi-native", turn_id=second.turn_id, workspace_history_head="head-2")

    class FakeNativeService:
        async def rollback_workspace_history(self, **kwargs):
            assert kwargs["target_head"] == "head-1"
            return WorkspaceHistoryStatus(head="head-1", clean=True, manual_change_count=0)

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    result = await rollback_native_agent_history(
        web_manager,
        "main",
        1001,
        conversation_id=first.conversation_id,
        target_turn_id=first.turn_id,
    )

    assert result["current_turn_id"] == first.turn_id
    assert result["rollback_supported"] is False
    assert [item["content"] for item in history.list_history(profile, session)] == ["一", "一回"]
    reloaded = pi_store.get(key)
    assert reloaded is not None
    assert reloaded.linear_index == 1
    assert reloaded.workspace_history_head == "head-1"
    assert reloaded.turns[1].status == "discarded"
    assert "changed_paths" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_native_agent_history_rollback_blocks_running_cluster_child_task(
    web_manager: MultiBotManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.cluster.runtime import AskAgentRequest
    from bot.native_agent.pi_session_store import PiSessionRecord, PiSessionStore, pi_session_key

    web_manager.main_profile.working_dir = str(tmp_path)
    profile = web_manager.main_profile
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    history = ChatHistoryService(ChatStore(tmp_path), native_provider_filter="native_agent")
    first = history.start_turn(profile=profile, session=session, user_text="一", native_provider="native_agent")
    history.complete_turn(first, content="一回", completion_state="completed", native_session_id="pi-native")
    history.store.update_turn_workspace_history(first.turn_id, "head-1", 1)
    key = pi_session_key(
        cwd=str(tmp_path),
        bot_id=session.bot_id,
        user_id=session.user_id,
        conversation_id=first.conversation_id,
    )
    PiSessionStore().upsert(
        PiSessionRecord(
            key=key,
            cwd=str(tmp_path),
            conversation_id=first.conversation_id,
            pi_session_id="pi-native",
            workspace_history_head="head-1",
        )
    )

    class FakeNativeService:
        async def rollback_workspace_history(self, **_kwargs):
            raise AssertionError("子 agent 运行中不应执行工作区 rollback")

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())
    run = api_service._CLUSTER_RUNTIME.start_run(
        api_service.ClusterRunRequest(
            bot_alias="main",
            user_id=chat_session_user_id(1001),
            profile=profile,
            execution_mode="native_agent",
        )
    )
    task = api_service._CLUSTER_RUNTIME.create_agent_task(
        run.run_id,
        AskAgentRequest(agent_id="tester", message="测一下", model_tier="medium", timeout_seconds=60, allow_write=False),
    )
    api_service._CLUSTER_RUNTIME.mark_agent_task_running(run.run_id, task.task_id)

    try:
        with pytest.raises(WebApiError) as exc_info:
            await rollback_native_agent_history(
                web_manager,
                "main",
                1001,
                conversation_id=first.conversation_id,
                target_turn_id=first.turn_id,
            )
    finally:
        api_service._CLUSTER_RUNTIME.cancel_run_tasks(run.run_id, "测试清理")
        api_service._CLUSTER_RUNTIME.finish_run(run.run_id, "cancelled")

    assert exc_info.value.code == "cluster_child_task_running"


@pytest.mark.asyncio
async def test_native_agent_history_rollback_requires_local_record_before_reset(
    web_manager: MultiBotManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    web_manager.main_profile.working_dir = str(tmp_path)
    profile = web_manager.main_profile
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    history = ChatHistoryService(ChatStore(tmp_path), native_provider_filter="native_agent")
    first = history.start_turn(profile=profile, session=session, user_text="一", native_provider="native_agent")
    history.complete_turn(first, content="一回", completion_state="completed", native_session_id="pi-native")
    history.store.update_turn_workspace_history(first.turn_id, "head-1", 1)

    class FakeNativeService:
        async def rollback_workspace_history(self, **_kwargs):
            raise AssertionError("缺本地记录时不应执行工作区 rollback")

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    with pytest.raises(WebApiError) as exc_info:
        await rollback_native_agent_history(
            web_manager,
            "main",
            1001,
            conversation_id=first.conversation_id,
            target_turn_id=first.turn_id,
        )

    assert exc_info.value.code == "workspace_history_record_missing"


def test_native_agent_history_changes_and_diff_api(web_manager: MultiBotManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot.native_agent.shadow_git_history import ShadowGitHistory

    monkeypatch.setenv("TCB_DATA_DIR", str(tmp_path / "data"))
    web_manager.main_profile.working_dir = str(tmp_path)
    profile = web_manager.main_profile
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    history = ChatHistoryService(ChatStore(tmp_path), native_provider_filter="native_agent")
    shadow = ShadowGitHistory()

    first = history.start_turn(profile=profile, session=session, user_text="一", native_provider="native_agent")
    before_first = shadow.snapshot(cwd=tmp_path, conversation_id=first.conversation_id, label="turn-1-before")
    (tmp_path / "smoke").mkdir()
    (tmp_path / "smoke" / "history.txt").write_text("A\n", encoding="utf-8")
    history.complete_turn(first, content="一回", completion_state="completed", native_session_id="pi-native")
    after_first = shadow.record_completed_turn(
        cwd=tmp_path,
        conversation_id=first.conversation_id,
        turn_id=first.turn_id,
        before_head=before_first.head,
        pi_session_id="pi-native",
    )
    history.store.update_turn_workspace_history(first.turn_id, after_first.head, 1)

    second = history.start_turn(profile=profile, session=session, user_text="二", native_provider="native_agent")
    before_second = shadow.snapshot(cwd=tmp_path, conversation_id=second.conversation_id, label="turn-2-before")
    (tmp_path / "smoke" / "history.txt").write_text("A\nB\n", encoding="utf-8")
    (tmp_path / "smoke" / "new.txt").write_text("N\n", encoding="utf-8")
    history.complete_turn(second, content="二回", completion_state="completed", native_session_id="pi-native")
    after_second = shadow.record_completed_turn(
        cwd=tmp_path,
        conversation_id=second.conversation_id,
        turn_id=second.turn_id,
        before_head=before_second.head,
        pi_session_id="pi-native",
    )
    history.store.update_turn_workspace_history(second.turn_id, after_second.head, 2)

    changes = get_native_agent_history_changes(
        web_manager,
        "main",
        1001,
        conversation_id=first.conversation_id,
        turn_id=second.turn_id,
    )
    files = {item["path"]: item for item in changes["files"]}
    diff = get_native_agent_history_diff(
        web_manager,
        "main",
        1001,
        conversation_id=first.conversation_id,
        turn_id=second.turn_id,
        path="smoke/history.txt",
    )

    assert changes["turn_id"] == second.turn_id
    assert changes["linear_index"] == 2
    assert files["smoke/history.txt"]["additions"] == 1
    assert files["smoke/new.txt"]["status"] == "added"
    assert diff["status"] == "modified"
    assert diff["old_path"] == ""
    assert diff["binary"] is False
    assert "+B" in diff["diff"]
    assert diff["truncated"] is False
    with pytest.raises(WebApiError) as exc_info:
        get_native_agent_history_diff(
            web_manager,
            "main",
            1001,
            conversation_id=first.conversation_id,
            turn_id=second.turn_id,
            path="smoke/missing.txt",
        )
    assert exc_info.value.code == "history_diff_path_invalid"

    history.store.mark_turns_after_discarded(first.conversation_id, first.turn_id)
    with pytest.raises(WebApiError) as discarded:
        get_native_agent_history_changes(
            web_manager,
            "main",
            1001,
            conversation_id=first.conversation_id,
            turn_id=second.turn_id,
        )
    assert discarded.value.code == "target_turn_discarded"


def test_reset_user_session_blocks_while_processing(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True
        session.native_agent_session_id = "native-1"

    with pytest.raises(WebApiError) as exc_info:
        reset_user_session(web_manager, "main", 1001)

    assert exc_info.value.status == 409
    assert exc_info.value.code == "conversation_switch_blocked"


def test_reset_user_session_clears_runtime_native_session(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    with session._lock:
        session.native_agent_session_id = "native-1"
        session.native_agent_run_id = "run-1"
    session.persist()

    result = reset_user_session(web_manager, "main", 1001)
    next_session = get_session_for_alias(web_manager, "main", 1001)

    assert result["reset"] is True
    assert next_session.native_agent_session_id is None
    assert next_session.native_agent_run_id is None


@pytest.mark.asyncio
async def test_reset_user_session_during_fake_native_stream_returns_409_and_stream_finishes(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    started = asyncio.Event()
    release = asyncio.Event()

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            session = kwargs["session"]
            with session._lock:
                session.is_processing = True
            started.set()
            yield {"type": "meta", "execution_mode": "native_agent"}
            await release.wait()
            with session._lock:
                session.is_processing = False
            yield {
                "type": "done",
                "output": "完成",
                "message": {"id": "assistant-1", "role": "assistant", "content": "完成", "meta": {}},
                "elapsed_seconds": 0,
                "returncode": 0,
            }

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    async def collect_events():
        return [
            event
            async for event in api_service.stream_chat(
                web_manager,
                "main",
                1001,
                "你好",
                execution_mode="native_agent",
            )
        ]

    task = asyncio.create_task(collect_events())
    await started.wait()

    with pytest.raises(WebApiError) as exc_info:
        reset_user_session(web_manager, "main", 1001)

    assert exc_info.value.status == 409
    assert exc_info.value.code == "conversation_switch_blocked"

    release.set()
    events = await task
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_delete_conversations_route_reads_agent_and_execution_mode(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}

    def fake_delete_all(manager, alias, user_id, *, agent_id="main", execution_mode="", delete_native_session=False):
        captured.update(
            {
                "alias": alias,
                "user_id": user_id,
                "agent_id": agent_id,
                "execution_mode": execution_mode,
                "delete_native_session": delete_native_session,
            }
        )
        return {"deleted_count": 0, "active_conversation_id": "", "native_session_cleared": False, "items": [], "messages": []}

    def fake_auth(_self, _request):
        return AuthContext(
            user_id=1001,
            token_used=True,
            account_id="local-admin",
            username="local-admin",
            role="owner",
            capabilities={"chat_send"},
            is_local_admin=True,
        )

    monkeypatch.setattr("bot.web.server.delete_all_conversations", fake_delete_all)
    monkeypatch.setattr("bot.web.server.WebApiServer._auth_context", fake_auth)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.delete(
                "/api/bots/main/conversations?delete_native_session=true",
                json={"agent_id": "reviewer", "execution_mode": "native_agent"},
            )
            assert resp.status == 200

    assert captured == {
        "alias": "main",
        "user_id": 1,
        "agent_id": "reviewer",
        "execution_mode": "native_agent",
        "delete_native_session": True,
    }


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


def test_codex_command_execution_stream_trace_chunks():
    state = create_stream_trace_state("codex")

    started_events = consume_stream_trace_chunk(
        "codex",
        json.dumps({
            "type": "item.started",
            "item": {
                "id": "cmd-1",
                "type": "command_execution",
                "command": "Get-ChildItem -Force",
                "status": "in_progress",
            },
        }) + "\n",
        state,
    )
    completed_events = consume_stream_trace_chunk(
        "codex",
        json.dumps({
            "type": "item.completed",
            "item": {
                "id": "cmd-1",
                "type": "command_execution",
                "command": "Get-ChildItem -Force",
                "aggregated_output": "README.md\nbot\nfront",
                "exit_code": 0,
                "status": "completed",
            },
        }) + "\n",
        state,
    )
    fallback_events = consume_stream_trace_chunk(
        "codex",
        json.dumps({
            "type": "item.completed",
            "item": {
                "id": "cmd-2",
                "type": "command_execution",
                "command": "Write-Output ok",
                "aggregated_output": "",
                "exit_code": 0,
                "status": "completed",
            },
        }) + "\n",
        state,
    )

    assert started_events == [
        {
            "kind": "tool_call",
            "source": "native",
            "raw_type": "command_execution",
            "title": "command_execution",
            "tool_name": "command_execution",
            "call_id": "cmd-1",
            "summary": "Get-ChildItem -Force",
            "payload": {
                "command": "Get-ChildItem -Force",
                "aggregated_output": "",
                "exit_code": "",
                "status": "in_progress",
            },
        }
    ]
    assert completed_events[0]["kind"] == "tool_result"
    assert completed_events[0]["call_id"] == "cmd-1"
    assert completed_events[0]["summary"] == "README.md\nbot\nfront"
    assert completed_events[0]["payload"] == {
        "command": "Get-ChildItem -Force",
        "aggregated_output": "README.md\nbot\nfront",
        "exit_code": 0,
        "status": "completed",
    }
    assert fallback_events[0]["summary"] == "Exit code: 0"


def test_codex_command_execution_native_transcript_trace(tmp_path: Path):
    transcript_path = tmp_path / "codex.jsonl"
    transcript_path.write_text(
        "\n".join([
            json.dumps({"type": "turn_context", "content": "列出目录"}),
            json.dumps({
                "type": "item.started",
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "Get-ChildItem -Force",
                    "status": "in_progress",
                },
            }),
            json.dumps({
                "type": "item.completed",
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "Get-ChildItem -Force",
                    "aggregated_output": "README.md\nbot\nfront",
                    "exit_code": 0,
                    "status": "completed",
                },
            }),
            json.dumps({"type": "item.completed", "item": {"type": "assistant_message", "text": "目录已读取完成。"}}),
        ]),
        encoding="utf-8",
    )

    messages = load_native_transcript("codex", transcript_path, session_id="thread-1", include_trace=True)

    assert len(messages) == 1
    trace = messages[0]["meta"]["trace"]
    assert trace[0]["kind"] == "tool_call"
    assert trace[0]["summary"] == "Get-ChildItem -Force"
    assert trace[1]["kind"] == "tool_result"
    assert trace[1]["summary"] == "README.md\nbot\nfront"
    assert messages[0]["meta"]["tool_call_count"] == 1


def test_claude_tool_use_description_becomes_commentary_stream_trace():
    state = create_stream_trace_state("claude")

    events = consume_stream_trace_chunk(
        "claude",
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Bash",
                        "input": {
                            "description": "统计 git 跟踪代码文件行数",
                            "command": "git ls-files | xargs wc -l",
                        },
                    }
                ]
            },
        }) + "\n",
        state,
    )

    assert [event["kind"] for event in events] == ["commentary", "tool_call"]
    assert events[0]["raw_type"] == "tool_use.intent"
    assert events[0]["summary"] == "统计 git 跟踪代码文件行数"
    assert events[0]["call_id"] == "toolu_1"
    assert events[1]["summary"] == "git ls-files | xargs wc -l"


def test_claude_tool_use_description_becomes_commentary_native_transcript_trace(tmp_path: Path):
    transcript_path = tmp_path / "claude.jsonl"
    transcript_path.write_text(
        "\n".join([
            json.dumps({
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "统计代码行数",
                        }
                    ]
                },
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Bash",
                            "input": {
                                "description": "统计 git 跟踪代码文件行数",
                                "command": "git ls-files | xargs wc -l",
                            },
                        }
                    ]
                },
            }),
            json.dumps({
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "123 total",
                        }
                    ]
                },
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "统计完成。",
                        }
                    ]
                },
            }),
        ]),
        encoding="utf-8",
    )

    messages = load_native_transcript("claude", transcript_path, session_id="session-1", include_trace=True)

    assert len(messages) == 1
    trace = messages[0]["meta"]["trace"]
    assert [event["kind"] for event in trace] == ["commentary", "tool_call", "tool_result"]
    assert trace[0]["raw_type"] == "tool_use.intent"
    assert trace[0]["summary"] == "统计 git 跟踪代码文件行数"
    assert trace[0]["call_id"] == "toolu_1"
    assert trace[1]["summary"] == "git ls-files | xargs wc -l"
    assert messages[0]["content"] == "统计完成。"
    assert messages[0]["meta"]["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_stream_cli_chat_emits_trace_events_and_done_message(web_manager: MultiBotManager):
    web_manager.main_profile.cli_type = "codex"

    class FakeStdout:
        def __init__(self, owner):
            self._owner = owner
            self._lines = [
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.delta","item":{"type":"assistant_message","delta":"我先检查目录结构。"}}\n',
                '{"type":"item.started","item":{"id":"call_1","type":"command_execution","command":"Get-ChildItem -Force","status":"in_progress"}}\n',
                '{"type":"item.completed","item":{"id":"call_1","type":"command_execution","command":"Get-ChildItem -Force","aggregated_output":"README.md\\nbot\\nfront","exit_code":0,"status":"completed"}}\n',
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
    meta_event = next(event for event in events if event["type"] == "meta")
    done_event = next(event for event in events if event["type"] == "done")

    assert trace_events
    assert meta_event["turn_id"]
    assert meta_event["assistant_message_id"]
    for trace_event in trace_events:
        assert trace_event["turn_id"] == meta_event["turn_id"]
        assert trace_event["assistant_message_id"] == meta_event["assistant_message_id"]
    assert trace_events[0]["event"]["kind"] == "tool_call"
    assert trace_events[0]["event"]["summary"] == "Get-ChildItem -Force"
    assert trace_events[1]["event"]["kind"] == "tool_result"
    assert done_event["turn_id"] == meta_event["turn_id"]
    assert done_event["assistant_message_id"] == meta_event["assistant_message_id"]
    assert done_event["message"]["id"] == done_event["assistant_message_id"]
    assert done_event["message"]["role"] == "assistant"
    assert done_event["message"]["content"] == "目录已读取完成。"


@pytest.mark.asyncio
async def test_stream_cli_chat_status_event_includes_turn_ids(web_manager: MultiBotManager):
    web_manager.main_profile.cli_type = "codex"
    fake_process = _ScheduledFakeProcess([
        (0, '{"type":"item.delta","item":{"type":"assistant_message","delta":"处理中"}}\n'),
        (0.05, '{"type":"item.completed","item":{"type":"assistant_message","text":"完成回复"}}\n'),
    ])

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = await asyncio.wait_for(
            _collect_stream_events(_stream_cli_chat(web_manager, "main", 1001, "执行")),
            timeout=2,
        )

    meta_event = next(event for event in events if event["type"] == "meta")
    status_event = next(event for event in events if event["type"] == "status")
    done_event = next(event for event in events if event["type"] == "done")

    assert status_event["turn_id"] == meta_event["turn_id"]
    assert status_event["assistant_message_id"] == meta_event["assistant_message_id"]
    assert done_event["turn_id"] == meta_event["turn_id"]
    assert done_event["assistant_message_id"] == meta_event["assistant_message_id"]
    assert status_event["preview_text"] == "处理中"


@pytest.mark.asyncio
async def test_stream_chat_routes_native_agent_execution_mode(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {"type": "meta", "execution_mode": "native_agent"}
            yield {
                "type": "done",
                "output": "原生回复",
                "message": {
                    "id": "assistant-native",
                    "role": "assistant",
                    "content": "原生回复",
                    "created_at": "2026-06-04T00:00:00",
                    "meta": {"native_source": {"provider": "native_agent", "session_id": "native-1"}},
                },
                "elapsed_seconds": 1,
                "returncode": 0,
            }

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    events = [
        event async for event in api_service.stream_chat(
            web_manager,
            "main",
            1001,
            "你好",
            execution_mode="native_agent",
        )
    ]

    assert events[-1]["type"] == "done"
    assert captured["profile"] is web_manager.main_profile
    assert captured["session"].agent_id == "main"
    assert captured["user_text"] == "你好"
    assert captured["prompt_text"] == "你好"
    assert captured["solo_mode"] is False


@pytest.mark.asyncio
async def test_stream_chat_routes_native_agent_child_agent(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    web_manager.main_profile.agents = [
        AgentProfile(id="reviewer", name="审查专家", system_prompt="先列风险"),
    ]
    captured: dict[str, Any] = {}

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {"type": "meta", "execution_mode": "native_agent"}
            yield {
                "type": "done",
                "output": "审查回复",
                "message": {
                    "id": "assistant-native-child",
                    "role": "assistant",
                    "content": "审查回复",
                    "created_at": "2026-06-04T00:00:00",
                    "meta": {"native_source": {"provider": "native_agent", "session_id": "native-child-1"}},
                },
                "elapsed_seconds": 1,
                "returncode": 0,
            }

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    events = [
        event async for event in api_service.stream_chat(
            web_manager,
            "main",
            1001,
            "你好",
            agent_id="reviewer",
            execution_mode="native_agent",
        )
    ]

    assert events[-1]["type"] == "done"
    assert captured["profile"] is web_manager.main_profile
    assert captured["session"].agent_id == "reviewer"
    assert captured["user_text"] == "你好"
    assert captured["prompt_text"].endswith("你好")


@pytest.mark.asyncio
async def test_native_cluster_child_task_uses_native_history(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    web_manager.main_profile.supported_execution_modes = ["native_agent"]
    web_manager.main_profile.default_execution_mode = "native_agent"
    web_manager.main_profile.cluster = api_service.normalize_bot_cluster_config({"enabled": True})
    web_manager.main_profile.agents = [
        AgentProfile(id="reviewer", name="审查专家", system_prompt="先列风险"),
    ]
    calls: list[dict[str, Any]] = []

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            calls.append(dict(kwargs))
            history = kwargs["history_service"]
            session = kwargs["session"]
            handle = history.start_turn(
                profile=kwargs["profile"],
                session=session,
                user_text=kwargs["user_text"],
                native_provider="native_agent",
            )
            message = history.complete_turn(
                handle,
                content="子 agent 回复",
                completion_state="completed",
                native_session_id="native-child-1",
            )
            yield {"type": "status", "preview_text": "处理中"}
            yield {"type": "done", "output": "子 agent 回复", "message": message, "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    run = api_service._CLUSTER_RUNTIME.start_run(
        api_service.ClusterRunRequest(
            bot_alias="main",
            user_id=chat_session_user_id(1001),
            profile=web_manager.main_profile,
            execution_mode="native_agent",
        )
    )
    request = api_service._CLUSTER_RUNTIME.validate_ask_agent(
        run.run_id,
        {"agent_id": "reviewer", "message": "复核一下"},
    )
    task = api_service._CLUSTER_RUNTIME.create_agent_task(run.run_id, request)

    await api_service._run_cluster_agent_task(web_manager, run.run_id, task.task_id)

    status = api_service._CLUSTER_RUNTIME.build_task_status(run.run_id, [task.task_id], include_output=True)
    assert status["completed_count"] == 1
    assert status["tasks"][0]["output"] == "子 agent 回复"
    assert calls[0]["session"].agent_id == "reviewer"
    assert calls[0]["solo_mode"] is True
    assert [item["content"] for item in get_history(web_manager, "main", 1001, agent_id="reviewer", execution_mode="native_agent")["items"]] == [
        "复核一下",
        "子 agent 回复",
    ]
    conversations = list_conversations(web_manager, "main", 1001, agent_id="reviewer", execution_mode="native_agent")["items"]
    assert conversations[0]["native_provider"] == "native_agent"


@pytest.mark.asyncio
async def test_stream_chat_routes_native_agent_solo_mode(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {"type": "done", "output": "原生回复", "message": {"id": "assistant-native", "role": "assistant", "content": "原生回复", "meta": {}}, "elapsed_seconds": 1, "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    events = [
        event async for event in api_service.stream_chat(
            web_manager,
            "main",
            1001,
            "你好",
            execution_mode="native_agent",
            solo_mode=True,
        )
    ]

    assert events[-1]["type"] == "done"
    assert captured["solo_mode"] is True


@pytest.mark.asyncio
async def test_stream_chat_routes_native_agent_protocol_to_service(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeNativeService:
        async def stream_chat(self, **kwargs):
            captured.update(kwargs)
            yield {"type": "done", "output": "原生回复", "message": {"id": "assistant-native", "role": "assistant", "content": "原生回复", "meta": {}}, "elapsed_seconds": 1, "returncode": 0}

    monkeypatch.setattr(api_service, "get_native_agent_service", lambda: FakeNativeService())

    events = [
        event async for event in api_service.stream_chat(
            web_manager,
            "main",
            1001,
            "你好",
            execution_mode="native_agent",
            protocol="ag-ui",
        )
    ]

    assert events[-1]["type"] == "done"
    assert captured["protocol"] == "ag-ui"


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


class BlockingAfterLinesStdout:
    def __init__(self, lines: list[str]):
        self.closed = threading.Event()
        self._lines = list(lines)

    def readline(self):
        if self._lines:
            return self._lines.pop(0)
        self.closed.wait(30)
        return ""

    def read(self):
        return ""

    def close(self):
        self.closed.set()


class BlockingAfterLinesProcess:
    def __init__(self, lines: list[str]):
        self.stdout = BlockingAfterLinesStdout(lines)
        self.stdin = None
        self.stderr = None
        self.returncode = None
        self.pid = 4321
        self.kill = MagicMock(side_effect=self._kill)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("cli", timeout or 0)
        return self.returncode

    def _kill(self):
        self.returncode = -9

    def terminate(self):
        self.returncode = -15


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


async def _collect_stream_events(stream):
    events = []
    async for event in stream:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_communicate_process_drains_briefly_after_exit_and_closes_blocking_stdout():
    class BlockingStdout:
        def __init__(self):
            self.closed = threading.Event()
            self._lines = ["完成\n"]

        def readline(self):
            if self._lines:
                return self._lines.pop(0)
            self.closed.wait(30)
            return ""

        def read(self):
            return ""

        def close(self):
            self.closed.set()

    class ExitedProcess:
        def __init__(self):
            self.stdout = BlockingStdout()
            self.stdin = None
            self.stderr = None
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    process = ExitedProcess()

    output, returncode = await asyncio.wait_for(_communicate_process(process), timeout=2)

    assert output == "完成\n"
    assert returncode == 0
    assert process.stdout.closed.is_set()


@pytest.mark.asyncio
async def test_stream_cli_chat_finishes_after_final_message_when_stdout_blocks(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    web_manager.main_profile.cli_type = "codex"
    fake_process = FakeCodexProcessWithBlockingStdout()
    monkeypatch.setattr(api_service, "CODEX_DONE_QUIET_SECONDS", 0.01)
    monkeypatch.setattr(api_service, "CODEX_TERMINATE_GRACE_SECONDS", 0.01)

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = await asyncio.wait_for(
            _collect_stream_events(_stream_cli_chat(web_manager, "main", 1001, "执行")),
            timeout=2,
        )

    done_event = next(event for event in events if event["type"] == "done")
    session = get_session_for_alias(web_manager, "main", 1001)
    assert done_event["output"] == "完成回复"
    assert fake_process.stdout.closed.is_set()
    assert session.process is None
    assert session.is_processing is False


@pytest.mark.asyncio
async def test_communicate_claude_does_not_wait_forever_on_blocking_stdout(
    monkeypatch: pytest.MonkeyPatch,
):
    from bot.claude_done import build_claude_done_session

    claude_done = build_claude_done_session(
        "prompt",
        cli_type="claude",
        enabled=True,
        quiet_seconds=0.01,
        nonce="test",
    )
    claude_process = BlockingAfterLinesProcess(
        [
            '{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"完成"}}}\n',
            '{"type":"result","subtype":"success","session_id":"sess-1","result":"完成\\n__TCB_DONE_test__"}\n',
        ]
    )

    with patch("bot.web.api_service._terminate_process_sync", side_effect=lambda proc: proc.kill()):
        claude_text, claude_session_id, claude_returncode = await asyncio.wait_for(
            _communicate_claude_process(claude_process, done_session=claude_done),
            timeout=2,
        )

    assert claude_text == "完成"
    assert claude_session_id == "sess-1"
    assert claude_returncode == 0
    assert claude_process.kill.called
    assert claude_process.stdout.closed.is_set()


@pytest.mark.asyncio
async def test_cli_chat_popen_uses_chat_cli_process_kwargs(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    process = RecordingProcess(['{"type":"item.completed","item":{"type":"assistant_message","text":"完成"}}\n'])
    captured_kwargs: list[dict[str, object]] = []

    def fake_popen(_cmd, **kwargs):
        captured_kwargs.append(kwargs)
        return process

    monkeypatch.setattr(api_service, "build_chat_cli_process_kwargs", lambda: {"creationflags": 0x08000200})

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", fake_popen):
        stream_events = await asyncio.wait_for(
            _collect_stream_events(_stream_cli_chat(web_manager, "main", 1001, "执行")),
            timeout=2,
        )

    process = RecordingProcess(['{"type":"item.completed","item":{"type":"assistant_message","text":"完成"}}\n'])
    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", fake_popen):
        run_result = await asyncio.wait_for(run_cli_chat(web_manager, "main", 1001, "执行"), timeout=2)

    assert next(event for event in stream_events if event["type"] == "done")["output"] == "完成"
    assert run_result["output"] == "完成"
    assert captured_kwargs[0]["creationflags"] == 0x08000200
    assert captured_kwargs[1]["creationflags"] == 0x08000200


@pytest.mark.asyncio
async def test_run_cli_chat_clamps_yolo_without_unsafe_capability(web_manager: MultiBotManager):
    web_manager.main_profile.cli_type = "codex"
    web_manager.main_profile.cli_params.codex["yolo"] = True
    web_manager.main_profile.cli_params.codex["extra_args"] = [
        "--safe-flag",
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    captured_yolo: list[bool] = []
    captured_extra_args: list[list[str]] = []

    def fake_build_cli_command(**kwargs):
        params_config = kwargs["params_config"]
        captured_yolo.append(bool(params_config.codex.get("yolo")))
        captured_extra_args.append(list(params_config.codex.get("extra_args") or []))
        return ["codex"], False

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", side_effect=fake_build_cli_command), \
         patch("bot.web.api_service.subprocess.Popen", return_value=RecordingProcess(['{"type":"item.completed","item":{"type":"assistant_message","text":"完成"}}\n'])):
        result = await asyncio.wait_for(run_cli_chat(web_manager, "main", 1001, "执行"), timeout=2)

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", side_effect=fake_build_cli_command), \
         patch("bot.web.api_service.subprocess.Popen", return_value=RecordingProcess(['{"type":"item.completed","item":{"type":"assistant_message","text":"完成"}}\n'])):
        unsafe_result = await asyncio.wait_for(
            run_cli_chat(web_manager, "main", 1001, "执行", allow_unsafe_cli=True),
            timeout=2,
        )

    assert result["output"] == "完成"
    assert unsafe_result["output"] == "完成"
    assert captured_yolo == [False, True]
    assert captured_extra_args == [
        ["--safe-flag"],
        ["--safe-flag", "--dangerously-bypass-approvals-and-sandbox"],
    ]


@pytest.mark.asyncio
async def test_run_cli_chat_finally_terminates_lingering_process(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    web_manager.main_profile.cli_type = "codex"
    process = RecordingProcess([])
    communicate_mock = AsyncMock(return_value=("完成", "thread-1", 0))

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=process), \
         patch("bot.web.api_service._communicate_codex_process", communicate_mock), \
         patch("bot.web.api_service._terminate_process_sync", side_effect=lambda proc: proc.kill()) as terminate_mock:
        result = await asyncio.wait_for(run_cli_chat(web_manager, "main", 1001, "执行"), timeout=2)

    session = get_session_for_alias(web_manager, "main", 1001)
    assert result["output"] == "完成"
    terminate_mock.assert_called_with(process)
    assert process.kill.called
    assert session.process is None
    assert session.is_processing is False


@pytest.mark.asyncio
async def test_kill_user_process_terminates_live_process_and_clears_stale_process(
    web_manager: MultiBotManager,
):
    live_process = RecordingProcess([])
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True
        session.process = live_process
        session.stop_requested = True
        session.running_user_text = "执行"
        session.running_preview_text = "处理中"
        session.running_started_at = "2026-06-02T00:00:00"
        session.running_updated_at = "2026-06-02T00:00:01"

    with patch("bot.web.api_service._terminate_process_sync", side_effect=lambda proc: proc.kill()) as terminate_mock, \
         patch.object(ChatHistoryService, "reconcile_idle_streaming_turns", return_value=0) as reconcile_mock:
        result = await kill_user_process(web_manager, "main", 1001)

    assert result["killed"] is True
    terminate_mock.assert_called_with(live_process)
    reconcile_mock.assert_not_called()
    assert live_process.kill.called
    assert live_process.stdout.closed is True
    assert session.process is live_process
    assert session.is_processing is True
    assert session.stop_requested is True
    assert session.running_user_text == "执行"
    assert session.running_preview_text == "处理中"

    stale_process = RecordingProcess([])
    stale_process.returncode = 0
    with session._lock:
        session.is_processing = True
        session.process = stale_process

    with patch.object(ChatHistoryService, "reconcile_idle_streaming_turns", return_value=0) as stale_reconcile_mock:
        stale_result = await kill_user_process(web_manager, "main", 1001)

    assert stale_result["stale_cleared"] is True
    stale_reconcile_mock.assert_called()
    assert stale_process.stdout.closed is True
    assert session.process is None
    assert session.is_processing is False


@pytest.mark.asyncio
async def test_kill_user_process_aborts_native_agent_run(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True
        session.process = None
        session.native_agent_session_id = "native-1"
        session.native_agent_run_id = "run-1"

    with patch("bot.web.api_service.get_native_agent_service") as service_factory, \
         patch.object(ChatHistoryService, "reconcile_idle_streaming_turns", return_value=0) as reconcile_mock:
        service = service_factory.return_value
        service.abort = AsyncMock(return_value=True)
        result = await kill_user_process(web_manager, "main", 1001)

    assert result["killed"] is True
    assert result["native_agent_aborted"] is True
    assert result["stop_requested"] is True
    service.abort.assert_awaited_once_with(session)
    reconcile_mock.assert_not_called()
    assert session.stop_requested is True


@pytest.mark.asyncio
async def test_kill_user_process_aborts_native_agent_runtime_before_session_id(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True
        session.process = None
        session.native_agent_session_id = None
        session.native_agent_server_key = "pir-1"
        session.native_agent_run_id = "run-1"

    with patch("bot.web.api_service.get_native_agent_service") as service_factory:
        service = service_factory.return_value
        service.abort = AsyncMock(return_value=True)
        result = await kill_user_process(web_manager, "main", 1001)

    assert result["killed"] is True
    assert result["native_agent_aborted"] is True
    service.abort.assert_awaited_once_with(session)
    assert session.stop_requested is True
    assert session.native_agent_server_key == "pir-1"


@pytest.mark.asyncio
async def test_reply_native_agent_permission_calls_native_service(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.native_agent_session_id = "native-1"

    with patch("bot.web.api_service.get_native_agent_service") as service_factory:
        service = service_factory.return_value
        service.reply_permission = AsyncMock(return_value={"ok": True})
        result = await reply_native_agent_permission(
            web_manager,
            "main",
            1001,
            "perm-1",
            approved=True,
            message="允许本次读取",
        )

    assert result["permission_id"] == "perm-1"
    assert result["approved"] is True
    service.reply_permission.assert_awaited_once_with(
        session,
        "perm-1",
        approved=True,
        message="允许本次读取",
    )


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
async def test_plan_execute_endpoint_accepts_native_agent_execution_mode(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: True)
    web_manager.main_profile.supported_execution_modes = ["cli", "native_agent"]

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            response = await client.post(
                "/api/bots/main/plans/execute",
                json={"content": "# 方案\n\n- step", "title": "Native Plan", "execution_mode": "native_agent"},
            )
            payload = await response.json()

    assert response.status == 200
    assert payload["data"]["conversation"]["execution_mode"] == "native_agent"


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
