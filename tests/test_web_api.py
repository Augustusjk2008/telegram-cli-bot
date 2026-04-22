"""Web API 相关测试。"""

from __future__ import annotations

import asyncio
import json
import struct
import subprocess
import threading
import time
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer
from aiohttp.client_exceptions import ClientConnectionResetError, WSServerHandshakeError

import bot.runtime_paths as runtime_paths
from bot.assistant_context import AssistantPromptPayload
from bot.assistant_cron import AssistantCronService
from bot.assistant_cron_store import load_job_runtime_state, read_job_run_audit, save_job_runtime_state
from bot.assistant_cron_types import AssistantCronJob, AssistantCronJobState
from bot.assistant_dream import AssistantDreamPreparedPrompt, AssistantDreamApplyResult
from bot.assistant_docs import ManagedPromptSyncResult
from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_runtime import AssistantRunRequest
from bot.assistant_state import save_assistant_runtime_state
from bot.manager import MultiBotManager
from bot.messages import msg
from bot.models import BotProfile, UserSession
from bot.plugins.service import PluginService
from bot.session_store import save_session
from bot.web.server import WebApiServer, _TERMINAL_OUTPUT_EOF
from bot.web.api_service import (
    AuthContext,
    _stream_cli_chat,
    _build_stream_status_event,
    WebApiError,
    build_session_snapshot,
    change_working_directory,
    get_directory_listing,
    get_history,
    get_history_trace,
    get_session_for_alias,
    get_overview,
    resolve_session_bot_id,
    get_working_directory,
    kill_user_process,
    list_bots,
    list_system_scripts,
    create_text_file,
    delete_chat_attachment,
    execute_assistant_run_request,
    read_file_content,
    rename_path,
    run_chat,
    run_cli_chat,
    run_system_script,
    save_chat_attachment,
    save_uploaded_file,
    update_bot_workdir,
    write_file_content,
)
from bot.app_settings import get_git_proxy_settings, update_git_proxy_port
from bot.web import api_service
from bot.web.chat_history_service import ChatHistoryService
from bot.web.chat_store import ChatStore
from bot.web.git_service import (
    commit_git_changes,
    discard_all_git_changes,
    discard_git_paths,
    get_git_diff,
    get_git_overview,
    get_git_tree_status,
    init_git_repository,
    stage_git_paths,
)
from bot.assistant_proposals import create_proposal

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

def test_web_manager_uses_temp_session_store(web_manager: MultiBotManager, temp_dir: Path):
    import bot.session_store as session_store

    assert session_store.STORE_FILE == temp_dir / ".session_store.json"

def test_no_cli_message_points_to_web_settings_not_legacy_command():
    text = msg("chat", "no_cli", cli_path="missing-cli")

    assert "/set_cli_dir" not in text
    assert "设置页" in text
    assert "CLI 路径" in text

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

def test_get_directory_listing_accepts_explicit_path_without_mutating_browser_dir(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    root = tmp_path / "workspace"
    src = root / "src"
    docs = root / "docs"
    root.mkdir()
    src.mkdir()
    docs.mkdir()
    (src / "main.py").write_text("print('ok')\n", encoding="utf-8")

    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(root)
    session.browse_dir = str(docs)

    listing = get_directory_listing(web_manager, "main", 1001, path=str(src))

    assert listing["working_dir"] == str(src)
    assert any(item["name"] == "main.py" for item in listing["entries"])
    assert session.browse_dir == str(docs)
    assert session.working_dir == str(root)

def test_overview_includes_local_store_running_snapshot(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    session.session_epoch = 1
    service = ChatHistoryService(ChatStore(tmp_path))
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text="列出当前目录",
        native_provider="codex",
    )
    service.replace_assistant_preview(handle, "处理中预览")
    with session._lock:
        session.is_processing = True

    overview = get_overview(web_manager, "main", 1001)

    assert overview["session"]["history_count"] == 2
    assert overview["session"]["running_reply"]["user_text"] == "列出当前目录"
    assert overview["session"]["running_reply"]["preview_text"] == "处理中预览"

def test_get_overview_reuses_the_loaded_session_for_summary(web_manager: MultiBotManager):
    real_get_session = api_service.get_session_for_alias
    call_count = 0

    def counted_get_session(manager, alias, user_id):
      nonlocal call_count
      call_count += 1
      return real_get_session(manager, alias, user_id)

    with patch("bot.web.api_service.get_session_for_alias", side_effect=counted_get_session):
        overview = get_overview(web_manager, "main", 1001)

    assert overview["bot"]["alias"] == "main"
    assert call_count == 1

def test_list_bots_includes_processing_state_for_current_user(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True

    items = list_bots(web_manager, 1001)

    assert items[0]["alias"] == "main"
    assert items[0]["is_processing"] is True

def test_user_session_debounces_hot_path_persistence(monkeypatch: pytest.MonkeyPatch):
    persisted_preview_texts: list[str] = []
    session = UserSession(
        bot_id=1,
        bot_alias="main",
        user_id=1001,
        working_dir="C:\\workspace",
    )
    session.persist_hook = lambda current: persisted_preview_texts.append(current.running_preview_text)
    monkeypatch.setattr("bot.models.SESSION_PERSIST_DEBOUNCE_SECONDS", 0.01)

    session.start_running_reply("hello")
    session.update_running_reply("第一段")
    session.update_running_reply("第二段")
    time.sleep(0.04)

    assert persisted_preview_texts == ["第二段"]

    session.clear_running_reply()

    assert persisted_preview_texts[-1] == ""

def test_list_bots_includes_avatar_name(web_manager: MultiBotManager, temp_dir: Path):
    web_manager.main_profile.avatar_name = "avatar_01.png"
    web_manager.managed_profiles["team2"] = BotProfile(
        alias="team2",
        token="",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(temp_dir),
        enabled=True,
        avatar_name="claude-blue.png",
    )

    items = list_bots(web_manager, 1001)

    assert items[0]["alias"] == "main"
    assert items[0]["avatar_name"] == "avatar_01.png"
    assert next(item for item in items if item["alias"] == "team2")["avatar_name"] == "claude-blue.png"

def test_list_system_scripts_reads_active_bot_workdir_scripts(
    monkeypatch: pytest.MonkeyPatch,
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    powershell_script = scripts_dir / "network_traffic.ps1"
    batch_script = scripts_dir / "build_web_frontend.bat"
    shell_script = scripts_dir / "deploy.sh"
    markdown_file = scripts_dir / "README.md"

    powershell_script.write_text("# 网络流量\n# 查看网络状态\n", encoding="utf-8")
    batch_script.write_text(":: 构建前端\nREM 运行前端构建\n", encoding="utf-8")
    shell_script.write_text("# Linux only\n", encoding="utf-8")
    markdown_file.write_text("ignore me\n", encoding="utf-8")

    web_manager.main_profile.working_dir = str(tmp_path)
    monkeypatch.setattr("bot.platform.scripts.get_runtime_platform", lambda: "windows")

    payload = list_system_scripts(web_manager, "main", 1001)

    assert payload == {
        "items": [
            {
                "script_name": "build_web_frontend.bat",
                "display_name": "构建前端",
                "description": "构建前端 | 运行前端构建",
                "path": str(batch_script),
            },
            {
                "script_name": "network_traffic.ps1",
                "display_name": "网络流量",
                "description": "网络流量 | 查看网络状态",
                "path": str(powershell_script),
            },
        ]
    }

def test_change_working_directory_only_updates_browser_dir(web_manager: MultiBotManager, temp_dir: Path):
    session = get_session_for_alias(web_manager, "main", 1001)
    workdir = temp_dir / "cli-workdir"
    workdir.mkdir()
    browse_dir = temp_dir / "workspace"
    browse_dir.mkdir()
    session.working_dir = str(workdir)
    session.browse_dir = str(workdir)
    session.codex_session_id = "thread-old"
    session.claude_session_id = "claude-old"
    session.claude_session_initialized = True

    result = change_working_directory(web_manager, "main", 1001, str(browse_dir))

    assert result["working_dir"] == str(browse_dir)
    assert session.working_dir == str(workdir)
    assert session.browse_dir == str(browse_dir)
    assert web_manager.main_profile.working_dir == str(temp_dir)
    assert session.codex_session_id == "thread-old"
    assert session.claude_session_id == "claude-old"
    assert session.claude_session_initialized is True

@pytest.mark.asyncio
async def test_update_bot_workdir_requires_confirmation_when_local_history_exists(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    home = tmp_path / "home"
    home.mkdir()
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))
    web_manager.main_profile.working_dir = str(old_root)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(old_root)
    service = ChatHistoryService(ChatStore(old_root))
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text="hello",
        native_provider="codex",
    )
    service.complete_turn(handle, content="world", completion_state="completed")

    with pytest.raises(WebApiError) as exc_info:
        await update_bot_workdir(web_manager, "main", str(new_root), 1001)

    assert exc_info.value.status == 409
    assert exc_info.value.code == "workdir_change_requires_reset"
    assert exc_info.value.data == {
        "current_working_dir": str(old_root),
        "requested_working_dir": str(new_root),
        "history_count": 2,
        "message_count": session.message_count,
        "bot_mode": "cli",
    }
    assert runtime_paths.get_chat_history_db_path(old_root).exists()

@pytest.mark.asyncio
async def test_update_bot_workdir_blocks_while_processing(web_manager: MultiBotManager, tmp_path: Path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    web_manager.main_profile.working_dir = str(old_root)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(old_root)
    with session._lock:
        session.is_processing = True

    with pytest.raises(WebApiError) as exc_info:
        await update_bot_workdir(web_manager, "main", str(new_root), 1001)

    assert exc_info.value.code == "workdir_change_blocked_processing"
    assert session.is_processing is True

@pytest.mark.asyncio
async def test_update_bot_workdir_force_reset_clears_history_and_native_session_ids(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    web_manager.main_profile.working_dir = str(old_root)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(old_root)
    session.codex_session_id = "thread-1"
    service = ChatHistoryService(ChatStore(old_root))
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text="hello",
        native_provider="codex",
    )
    service.complete_turn(handle, content="world", completion_state="completed")

    data = await update_bot_workdir(web_manager, "main", str(new_root), 1001, force_reset=True)

    assert data["bot"]["working_dir"] == str(new_root)
    assert session.working_dir == str(new_root)
    assert session.browse_dir == str(new_root)
    assert session.codex_session_id is None
    assert get_history(web_manager, "main", 1001, limit=10)["items"] == []

def test_change_working_directory_from_windows_drive_root_opens_drive_picker(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.browse_dir = "H:\\"

    original_join = api_service.os.path.join
    original_abspath = api_service.os.path.abspath
    original_expanduser = api_service.os.path.expanduser
    original_isdir = api_service.os.path.isdir

    def fake_join(*parts):
        if parts == ("H:\\", ".."):
            return "__joined_parent__"
        return original_join(*parts)

    def fake_abspath(value):
        if value == "__joined_parent__":
            return value
        return original_abspath(value)

    def fake_expanduser(value):
        if value == "__joined_parent__":
            return value
        return original_expanduser(value)

    def fake_isdir(value):
        if value in {"H:\\", "C:\\", "D:\\"}:
            return True
        return original_isdir(value)

    monkeypatch.setattr(api_service.os.path, "join", fake_join)
    monkeypatch.setattr(api_service.os.path, "abspath", fake_abspath)
    monkeypatch.setattr(api_service.os.path, "expanduser", fake_expanduser)
    monkeypatch.setattr(api_service.os.path, "isdir", fake_isdir)

    result = change_working_directory(web_manager, "main", 1001, "..")

    assert result["working_dir"] == "盘符列表"
    assert result["is_virtual_root"] is True
    assert session.browse_dir == "::windows-drives::"

def test_get_directory_listing_returns_windows_drive_picker_entries(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.browse_dir = "::windows-drives::"

    monkeypatch.setattr(
        api_service.os.path,
        "isdir",
        lambda value: value in {"C:\\", "H:\\", "Z:\\"},
    )

    listing = get_directory_listing(web_manager, "main", 1001)

    assert listing["working_dir"] == "盘符列表"
    assert listing["is_virtual_root"] is True
    assert listing["entries"] == [
        {"name": "C:\\", "is_dir": True},
        {"name": "H:\\", "is_dir": True},
        {"name": "Z:\\", "is_dir": True},
    ]

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

@pytest.mark.asyncio
async def test_manual_assistant_cron_run_targets_visible_web_user_session(temp_dir: Path):
    home = bootstrap_assistant_home(temp_dir)
    coordinator = _FakeAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        web_user_id=1001,
    )
    await service.save_job(_build_assistant_cron_job("email_recvbox_check", "检查最新邮件并总结重点"))

    result = await service.run_job_now("email_recvbox_check")
    await service.stop()

    assert result["status"] == "queued"
    assert len(coordinator.requests) == 1
    assert coordinator.requests[0].user_id == 1001
    assert coordinator.requests[0].text == "检查最新邮件并总结重点"
    assert coordinator.requests[0].bot_alias == "assistant1"

@pytest.mark.asyncio
async def test_scheduled_assistant_cron_run_targets_visible_web_user_session(temp_dir: Path):
    now = datetime(2026, 4, 16, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    home = bootstrap_assistant_home(temp_dir)
    coordinator = _FakeAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        web_user_id=1001,
        now_func=lambda: now,
    )
    job = _build_assistant_cron_job("daily_digest", "汇总今天的重要动态")
    await service.save_job(job)
    save_job_runtime_state(
        home,
        job.id,
        AssistantCronJobState(next_run_at=(now - timedelta(seconds=1)).isoformat()),
    )

    results = await service.enqueue_due_jobs()
    await service.stop()

    assert len(results) == 1
    assert len(coordinator.requests) == 1
    assert coordinator.requests[0].user_id == 1001
    assert coordinator.requests[0].text == "汇总今天的重要动态"

@pytest.mark.asyncio
async def test_dream_assistant_cron_run_uses_synthetic_session_and_context_user(temp_dir: Path):
    home = bootstrap_assistant_home(temp_dir)
    coordinator = _FakeAssistantRuntimeCoordinator()
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        web_user_id=1001,
    )
    await service.save_job(_build_dream_assistant_cron_job("daily_dream", "根据近期工作做自我完善"))

    result = await service.run_job_now("daily_dream")
    await service.stop()

    assert result["status"] == "queued"
    assert result["task_mode"] == "dream"
    assert result["deliver_mode"] == "silent"
    assert len(coordinator.requests) == 1
    request = coordinator.requests[0]
    assert request.user_id < 0
    assert request.context_user_id == 1001
    assert request.task_mode == "dream"
    assert request.task_payload["mode"] == "dream"

@pytest.mark.asyncio
async def test_cron_watch_run_error_preserves_started_at_and_elapsed_seconds(temp_dir: Path):
    home = bootstrap_assistant_home(temp_dir)
    coordinator = _FailingAssistantRuntimeCoordinator()
    start = datetime(2026, 4, 21, 1, 0, 0, 122677, tzinfo=ZoneInfo("Asia/Shanghai"))
    finish = datetime(2026, 4, 21, 1, 2, 47, 624192, tzinfo=ZoneInfo("Asia/Shanghai"))
    current = [start]
    service = AssistantCronService(
        assistant_home=home,
        bot_alias="assistant1",
        coordinator=coordinator,
        web_user_id=1001,
        now_func=lambda: current[0],
    )
    await service.save_job(_build_dream_assistant_cron_job("daily_dream", "根据近期工作做自我完善"))

    result = await service.run_job_now("daily_dream")
    assert result["status"] == "queued"

    current[0] = finish
    coordinator.release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    state = load_job_runtime_state(home, "daily_dream")
    records = read_job_run_audit(home, "daily_dream")
    await service.stop()

    assert state.last_status == "error"
    assert state.last_started_at == start.isoformat()
    assert state.last_finished_at == finish.isoformat()
    assert records[-1]["started_at"] == start.isoformat()
    assert records[-1]["elapsed_seconds"] == 167
    assert records[-1]["error"] == "dream 结果处理失败"

def test_build_session_snapshot_omits_removed_legacy_session_id(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.codex_session_id = "thread-1"
    session.claude_session_id = "claude-1"
    session.claude_session_initialized = True

    snapshot = build_session_snapshot(web_manager.main_profile, session)

    assert snapshot["session_ids"] == {
        "codex_session_id": "thread-1",
        "claude_session_id": "claude-1",
        "claude_session_initialized": True,
    }

def test_assistant_change_directory_only_updates_file_browser_path(web_manager: MultiBotManager, temp_dir: Path):
    workdir = temp_dir / "assistant-workdir"
    workdir.mkdir()
    browse_dir = temp_dir / "assistant-browse"
    browse_dir.mkdir()
    (browse_dir / "note.txt").write_text("assistant browser\n", encoding="utf-8")

    web_manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(workdir),
        enabled=True,
        bot_mode="assistant",
    )

    session = get_session_for_alias(web_manager, "assistant1", 1001)

    result = change_working_directory(web_manager, "assistant1", 1001, str(browse_dir))

    assert result["working_dir"] == str(browse_dir)
    assert session.working_dir == str(workdir)
    assert session.browse_dir == str(browse_dir)
    assert web_manager.managed_profiles["assistant1"].working_dir == str(workdir)

    pwd = get_working_directory(web_manager, "assistant1", 1001)
    assert pwd["working_dir"] == str(workdir)

    listing = get_directory_listing(web_manager, "assistant1", 1001)
    assert listing["working_dir"] == str(browse_dir)
    assert any(item["name"] == "note.txt" for item in listing["entries"])

    content = read_file_content(web_manager, "assistant1", 1001, "note.txt", mode="head", lines=1)
    assert content["working_dir"] == str(browse_dir)
    assert content["content"] == "assistant browser"

def test_assistant_change_directory_persists_browser_dir_in_assistant_state(
    web_manager: MultiBotManager, temp_dir: Path
):
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    browse_dir = temp_dir / "assistant-browse"
    browse_dir.mkdir()
    web_manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(workdir),
        enabled=True,
        bot_mode="assistant",
    )

    result = change_working_directory(web_manager, "assistant1", 1001, str(browse_dir))

    assert result["working_dir"] == str(browse_dir)
    state_file = workdir / ".assistant" / "state" / "users" / "1001.json"
    assert json.loads(state_file.read_text(encoding="utf-8"))["browse_dir"] == str(browse_dir)

def test_get_session_for_alias_restores_assistant_private_metadata_without_visible_history_state(
    web_manager: MultiBotManager, temp_dir: Path
):
    workdir = temp_dir / "assistant-root"
    workdir.mkdir()
    browse_dir = temp_dir / "assistant-browse"
    browse_dir.mkdir()
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
    save_assistant_runtime_state(
        home,
        1001,
        {
            "browse_dir": str(browse_dir),
            "history": [{"timestamp": "2026-04-11T09:00:00", "role": "user", "content": "private state"}],
            "codex_session_id": "assistant-thread",
            "web_turn_overlays": [{"provider": "codex", "summary_text": "synthetic"}],
            "message_count": 3,
            "managed_prompt_hash_seen": "hash-private",
        },
    )
    save_session(
        bot_id=resolve_session_bot_id(web_manager, "assistant1"),
        user_id=1001,
        codex_session_id="project-thread",
        browse_dir=str(temp_dir / "project-store"),
        history=[{"timestamp": "2026-04-11T08:00:00", "role": "user", "content": "project store"}],
    )

    session = get_session_for_alias(web_manager, "assistant1", 1001)

    assert session.codex_session_id is None
    assert session.browse_dir == str(browse_dir)
    assert session.history == []
    assert getattr(session, "web_turn_overlays", []) == []
    assert session.message_count == 3
    assert session.managed_prompt_hash_seen == "hash-private"

def test_reset_user_session_clears_assistant_private_state(
    web_manager: MultiBotManager, temp_dir: Path
):
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
    save_assistant_runtime_state(home, 1001, {"history": [{"role": "user", "content": "hello"}]})

    result = api_service.reset_user_session(web_manager, "assistant1", 1001)

    assert result["reset"] is True
    assert not (home.root / "state" / "users" / "1001.json").exists()

def test_reset_user_session_with_live_assistant_session_does_not_recreate_private_state(
    web_manager: MultiBotManager, temp_dir: Path
):
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
    session = get_session_for_alias(web_manager, "assistant1", 1001)
    session.add_to_history("user", "hello")
    state_file = home.root / "state" / "users" / "1001.json"
    assert state_file.exists()

    result = api_service.reset_user_session(web_manager, "assistant1", 1001)

    assert result["reset"] is True
    assert not state_file.exists()
    session.clear_running_reply()
    assert not state_file.exists()

def test_reset_user_session_assistant_noop_does_not_bootstrap_home(
    web_manager: MultiBotManager, temp_dir: Path
):
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

    with patch("bot.web.api_service.reset_session", return_value=False), \
         patch("bot.web.api_service.bootstrap_assistant_home") as bootstrap_mock, \
         patch("bot.web.api_service.clear_assistant_runtime_state") as clear_mock:
        result = api_service.reset_user_session(web_manager, "assistant1", 1001)

    assert result["reset"] is False
    bootstrap_mock.assert_not_called()
    clear_mock.assert_not_called()

def test_reset_user_session_clears_local_history_rows(web_manager: MultiBotManager, tmp_path: Path):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    session.session_epoch = 1
    service = ChatHistoryService(ChatStore(tmp_path))
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text="hello",
        native_provider="codex",
    )
    service.complete_turn(handle, content="world", completion_state="completed")

    result = api_service.reset_user_session(web_manager, "main", 1001)
    history = get_history(web_manager, "main", 1001, limit=10)

    assert result["reset"] is True
    assert history["items"] == []

def test_save_chat_attachment_stores_file_under_home_scoped_dir(
    web_manager: MultiBotManager,
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_home = temp_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: fake_home))

    result = save_chat_attachment(web_manager, "main", 1001, "notes.txt", b"line1\nline2\n")
    saved_path = Path(result["saved_path"])

    assert result["filename"] == "notes.txt"
    assert saved_path == fake_home / ".tcb" / "chat-attachments" / "main" / "1001" / "notes.txt"
    assert saved_path.read_bytes() == b"line1\nline2\n"

def test_save_chat_attachment_deduplicates_existing_names(
    web_manager: MultiBotManager,
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_home = temp_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: fake_home))

    first = save_chat_attachment(web_manager, "main", 1001, "notes.txt", b"first\n")
    second = save_chat_attachment(web_manager, "main", 1001, "notes.txt", b"second\n")

    assert first["filename"] == "notes.txt"
    assert second["filename"] == "notes-1.txt"
    assert first["saved_path"] != second["saved_path"]
    assert Path(second["saved_path"]).read_bytes() == b"second\n"

def test_delete_chat_attachment_removes_file_from_home_scoped_dir(
    web_manager: MultiBotManager,
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_home = temp_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: fake_home))

    uploaded = save_chat_attachment(web_manager, "main", 1001, "notes.txt", b"hello\n")
    saved_path = Path(uploaded["saved_path"])

    result = delete_chat_attachment(web_manager, "main", 1001, uploaded["saved_path"])

    assert result == {
        "filename": "notes.txt",
        "saved_path": str(saved_path),
        "existed": True,
        "deleted": True,
    }
    assert not saved_path.exists()

def test_delete_chat_attachment_rejects_paths_outside_user_scope(
    web_manager: MultiBotManager,
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_home = temp_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: fake_home))
    outside_path = temp_dir / "outside.txt"
    outside_path.write_text("nope", encoding="utf-8")

    with pytest.raises(WebApiError) as exc_info:
        delete_chat_attachment(web_manager, "main", 1001, str(outside_path))

    assert exc_info.value.status == 403
    assert exc_info.value.code == "attachment_delete_forbidden"

def test_delete_chat_attachment_is_idempotent_when_file_is_already_missing(
    web_manager: MultiBotManager,
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_home = temp_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: fake_home))
    missing_path = fake_home / ".tcb" / "chat-attachments" / "main" / "1001" / "missing.txt"

    result = delete_chat_attachment(web_manager, "main", 1001, str(missing_path))

    assert result == {
        "filename": "missing.txt",
        "saved_path": str(missing_path),
        "existed": False,
        "deleted": False,
    }

def test_get_history_does_not_materialize_empty_home_store(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(runtime_paths.Path, "home", staticmethod(lambda: home))

    web_manager.main_profile.working_dir = str(workspace)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(workspace)
    session.session_epoch = 1

    data = get_history(web_manager, "main", 1001, limit=10)

    assert data["items"] == []
    assert not runtime_paths.get_chat_history_db_path(workspace).exists()

def test_save_and_read_file(web_manager: MultiBotManager, temp_dir: Path):
    result = save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"line1\nline2\n")
    assert result["filename"] == "notes.txt"

    content = read_file_content(web_manager, "main", 1001, "notes.txt", mode="head", lines=1)
    assert content["content"] == "line1"

def test_read_file_preview_marks_small_file_as_full_content(web_manager: MultiBotManager, temp_dir: Path):
    save_uploaded_file(web_manager, "main", 1001, "tiny.txt", b"line1\n")

    content = read_file_content(web_manager, "main", 1001, "tiny.txt", mode="head", lines=80)

    assert content["content"] == "line1"
    assert content["file_size_bytes"] == len(b"line1\n")
    assert content["is_full_content"] is True

def test_read_file_preview_marks_truncated_files_as_partial_content(web_manager: MultiBotManager, temp_dir: Path):
    save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"line1\nline2\n")

    content = read_file_content(web_manager, "main", 1001, "notes.txt", mode="head", lines=1)

    assert content["content"] == "line1"
    assert content["file_size_bytes"] == len(b"line1\nline2\n")
    assert content["is_full_content"] is False

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

def test_write_file_content_rejects_absolute_path_outside_browser_dir(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    outside_dir = temp_dir / "outside"
    outside_dir.mkdir()
    target = outside_dir / "notes.txt"
    target.write_text("outside\n", encoding="utf-8")

    change_working_directory(web_manager, "main", 1001, str(workspace))

    with pytest.raises(WebApiError) as exc_info:
        write_file_content(web_manager, "main", 1001, str(target), "changed\n")

    assert exc_info.value.code == "unsafe_write_path"
    assert target.read_text(encoding="utf-8") == "outside\n"

def test_write_file_content_rejects_relative_escape_outside_browser_dir(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    outside_file = temp_dir / "notes.txt"
    outside_file.write_text("outside\n", encoding="utf-8")

    change_working_directory(web_manager, "main", 1001, str(workspace))

    with pytest.raises(WebApiError) as exc_info:
        write_file_content(web_manager, "main", 1001, "../notes.txt", "changed\n")

    assert exc_info.value.code == "unsafe_write_path"
    assert outside_file.read_text(encoding="utf-8") == "outside\n"

def test_write_file_content_rejects_stale_version(web_manager: MultiBotManager, temp_dir: Path):
    save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"line1\n")
    previous = read_file_content(web_manager, "main", 1001, "notes.txt", mode="cat", lines=0)
    write_file_content(web_manager, "main", 1001, "notes.txt", "line2\n", expected_mtime_ns=previous["last_modified_ns"])

    with pytest.raises(WebApiError) as exc_info:
        write_file_content(web_manager, "main", 1001, "notes.txt", "line3\n", expected_mtime_ns=previous["last_modified_ns"])

    assert exc_info.value.code == "file_version_conflict"
    assert read_file_content(web_manager, "main", 1001, "notes.txt", mode="cat", lines=0)["content"] == "line2\n"

def test_write_file_content_rejects_content_larger_than_editor_limit(web_manager: MultiBotManager, temp_dir: Path):
    save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"line1\n")

    with pytest.raises(WebApiError) as exc_info:
        write_file_content(web_manager, "main", 1001, "notes.txt", "a" * (512 * 1024 + 1))

    assert exc_info.value.code == "file_too_large_for_editor"
    assert read_file_content(web_manager, "main", 1001, "notes.txt", mode="cat", lines=0)["content"] == "line1\n"

def test_write_file_content_rejects_non_text_target(web_manager: MultiBotManager, temp_dir: Path):
    binary_bytes = b"\xff\xfe\xfd\x00"
    save_uploaded_file(web_manager, "main", 1001, "notes.bin", binary_bytes)

    with pytest.raises(WebApiError) as exc_info:
        write_file_content(web_manager, "main", 1001, "notes.bin", "changed\n")

    assert exc_info.value.code == "not_text_file"
    assert (temp_dir / "notes.bin").read_bytes() == binary_bytes

def test_write_file_content_rejects_existing_file_larger_than_editor_limit(web_manager: MultiBotManager, temp_dir: Path):
    save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"a" * (512 * 1024 + 1))

    with pytest.raises(WebApiError) as exc_info:
        write_file_content(web_manager, "main", 1001, "notes.txt", "changed\n")

    assert exc_info.value.code == "file_too_large_for_editor"
    assert (temp_dir / "notes.txt").stat().st_size == 512 * 1024 + 1

def test_create_directory_creates_folder_in_current_browser_dir(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    change_working_directory(web_manager, "main", 1001, str(workspace))

    result = api_service.create_directory(web_manager, "main", 1001, "docs")

    assert result["name"] == "docs"
    assert result["created_path"] == str(workspace / "docs")
    assert (workspace / "docs").is_dir()

def test_create_text_file_creates_file_in_current_browser_dir(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    change_working_directory(web_manager, "main", 1001, str(workspace))

    result = create_text_file(web_manager, "main", 1001, "notes.md", "# hello\n")

    target = workspace / "notes.md"

    assert target.read_text(encoding="utf-8") == "# hello\n"
    assert result["path"] == "notes.md"
    assert result["file_size_bytes"] == len("# hello\n".encode("utf-8"))
    assert isinstance(result["last_modified_ns"], int)

def test_create_text_file_accepts_parent_path_for_tree_actions(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    root = tmp_path / "workspace"
    docs = root / "docs"
    root.mkdir()
    docs.mkdir()

    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(root)
    session.browse_dir = str(root)

    result = create_text_file(web_manager, "main", 1001, "notes.md", "# title\n", parent_path="docs")

    assert result["path"] == "docs/notes.md"
    assert (docs / "notes.md").read_text(encoding="utf-8") == "# title\n"

def test_create_text_file_rejects_existing_target(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    (workspace / "notes.md").write_text("old\n", encoding="utf-8")
    change_working_directory(web_manager, "main", 1001, str(workspace))

    with pytest.raises(WebApiError) as exc_info:
        create_text_file(web_manager, "main", 1001, "notes.md", "# hello\n")

    assert exc_info.value.code == "file_already_exists"
    assert (workspace / "notes.md").read_text(encoding="utf-8") == "old\n"

def test_create_text_file_rejects_content_larger_than_editor_limit(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    change_working_directory(web_manager, "main", 1001, str(workspace))

    with pytest.raises(WebApiError) as exc_info:
        create_text_file(web_manager, "main", 1001, "notes.md", "a" * (512 * 1024 + 1))

    assert exc_info.value.code == "file_too_large_for_editor"
    assert not (workspace / "notes.md").exists()

def test_create_text_file_rejects_path_like_filename(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    change_working_directory(web_manager, "main", 1001, str(workspace))

    with pytest.raises(WebApiError) as exc_info:
        create_text_file(web_manager, "main", 1001, "docs/notes.md", "")

    assert exc_info.value.code == "invalid_filename"

def test_rename_path_renames_file_in_place(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    source = workspace / "notes.md"
    source.write_text("# hello\n", encoding="utf-8")
    change_working_directory(web_manager, "main", 1001, str(workspace))

    result = rename_path(web_manager, "main", 1001, "notes.md", "draft.md")

    assert result["old_path"] == "notes.md"
    assert result["path"] == "draft.md"
    assert not source.exists()
    assert (workspace / "draft.md").read_text(encoding="utf-8") == "# hello\n"

def test_rename_path_accepts_nested_relative_path(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    target = workspace / "docs"
    target.mkdir(parents=True)
    (target / "notes.md").write_text("# hello\n", encoding="utf-8")
    change_working_directory(web_manager, "main", 1001, str(workspace))

    result = rename_path(web_manager, "main", 1001, "docs/notes.md", "draft.md")

    assert result["old_path"] == "docs/notes.md"
    assert result["path"] == "docs/draft.md"
    assert not (target / "notes.md").exists()
    assert (target / "draft.md").exists()

def test_delete_path_recursively_removes_non_empty_directory(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    nested = workspace / "docs" / "guides"
    nested.mkdir(parents=True)
    (nested / "intro.txt").write_text("hello\n", encoding="utf-8")
    change_working_directory(web_manager, "main", 1001, str(workspace))

    result = api_service.delete_path(web_manager, "main", 1001, "docs")

    assert result["path"] == "docs"
    assert result["deleted_type"] == "directory"
    assert not (workspace / "docs").exists()

def test_read_file_outside_workdir_by_absolute_path(web_manager: MultiBotManager, temp_dir: Path):
    workspace_dir = temp_dir / "workspace"
    workspace_dir.mkdir()
    outside_dir = temp_dir / "outside"
    outside_dir.mkdir()
    target = outside_dir / "notes.txt"
    target.write_text("outside\nline2\n", encoding="utf-8")

    change_working_directory(web_manager, "main", 1001, str(workspace_dir))
    content = read_file_content(web_manager, "main", 1001, str(target), mode="head", lines=1)

    assert content["content"] == "outside"

def test_run_git_command_uses_safe_text_decode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    _run_git_command(tmp_path, "status")

    command = captured["command"]
    kwargs = captured["kwargs"]
    assert command[:4] == ["git", "-c", "core.fsmonitor=false", "status"]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"

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

def test_git_overview_returns_repo_state(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    tracked = repo_dir / "tracked.txt"
    tracked.write_text("line 1\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "tracked.txt")
    _run_git_command(repo_dir, "commit", "-m", "init")

    tracked.write_text("line 1\nline 2\n", encoding="utf-8")
    (repo_dir / "new.txt").write_text("draft\n", encoding="utf-8")

    web_manager.main_profile.working_dir = str(repo_dir)
    overview = get_git_overview(web_manager, "main", 1001)

    assert overview["repo_found"] is True
    assert overview["repo_path"] == str(repo_dir)
    assert overview["repo_name"] == "repo"
    assert overview["current_branch"]
    assert any(item["path"] == "tracked.txt" for item in overview["changed_files"])
    assert any(item["path"] == "new.txt" for item in overview["changed_files"])
    assert overview["recent_commits"][0]["subject"] == "init"

def test_stage_commit_and_diff_git_changes(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    tracked = repo_dir / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "tracked.txt")
    _run_git_command(repo_dir, "commit", "-m", "init")

    tracked.write_text("before\nafter\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(repo_dir)

    staged = stage_git_paths(web_manager, "main", 1001, ["tracked.txt"])
    assert any(item["path"] == "tracked.txt" and item["staged"] for item in staged["changed_files"])

    diff = get_git_diff(web_manager, "main", 1001, "tracked.txt", staged=True)
    assert "+after" in diff["diff"]

    committed = commit_git_changes(web_manager, "main", 1001, "feat: update tracked")
    assert committed["recent_commits"][0]["subject"] == "feat: update tracked"


def test_discard_git_paths_restores_tracked_and_added_files(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    tracked = repo_dir / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "tracked.txt")
    _run_git_command(repo_dir, "commit", "-m", "init")

    tracked.write_text("before\nafter\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "tracked.txt")
    added = repo_dir / "added.txt"
    added.write_text("draft\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "added.txt")
    web_manager.main_profile.working_dir = str(repo_dir)

    overview = discard_git_paths(web_manager, "main", 1001, ["tracked.txt", "added.txt"])

    assert tracked.read_text(encoding="utf-8") == "before\n"
    assert not added.exists()
    assert not any(item["path"] == "tracked.txt" for item in overview["changed_files"])
    assert not any(item["path"] == "added.txt" for item in overview["changed_files"])


def test_discard_all_git_changes_restores_repo_state(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    tracked = repo_dir / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "tracked.txt")
    _run_git_command(repo_dir, "commit", "-m", "init")

    tracked.write_text("before\nafter\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "tracked.txt")
    added = repo_dir / "added.txt"
    added.write_text("draft\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "added.txt")
    untracked = repo_dir / "scratch.txt"
    untracked.write_text("temp\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(repo_dir)

    overview = discard_all_git_changes(web_manager, "main", 1001)

    assert overview["is_clean"] is True
    assert overview["changed_files"] == []
    assert tracked.read_text(encoding="utf-8") == "before\n"
    assert not added.exists()
    assert not untracked.exists()


def test_get_git_tree_status_filters_to_working_dir_and_marks_added_modified_and_ignored(
    web_manager: MultiBotManager,
    temp_dir: Path,
):
    repo_dir = temp_dir / "repo"
    workspace = repo_dir / "app"
    workspace.mkdir(parents=True)
    _init_git_repo(repo_dir)

    (repo_dir / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
    tracked = workspace / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    (workspace / "keep.txt").write_text("clean\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", ".")
    _run_git_command(repo_dir, "commit", "-m", "init")

    tracked.write_text("after\n", encoding="utf-8")
    (workspace / "new.txt").write_text("new\n", encoding="utf-8")
    (workspace / "ignored.log").write_text("ignored\n", encoding="utf-8")
    (repo_dir / "outside.txt").write_text("outside subtree\n", encoding="utf-8")

    web_manager.main_profile.working_dir = str(workspace)
    change_working_directory(web_manager, "main", 1001, str(workspace))

    status = get_git_tree_status(web_manager, "main", 1001)

    assert status == {
        "repo_found": True,
        "working_dir": str(workspace),
        "repo_path": str(repo_dir),
        "items": {
            "tracked.txt": "modified",
            "new.txt": "added",
            "ignored.log": "ignored",
        },
    }

def test_get_git_tree_status_returns_empty_payload_outside_repo(
    web_manager: MultiBotManager,
    temp_dir: Path,
):
    workspace = temp_dir / "plain-workspace"
    workspace.mkdir()
    web_manager.main_profile.working_dir = str(workspace)
    change_working_directory(web_manager, "main", 1001, str(workspace))

    status = get_git_tree_status(web_manager, "main", 1001)

    assert status == {
        "repo_found": False,
        "working_dir": str(workspace),
        "repo_path": "",
        "items": {},
    }

def test_git_overview_uses_bot_profile_workdir(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)
    (repo_dir / "tracked.txt").write_text("line 1\n", encoding="utf-8")

    other_dir = temp_dir / "other"
    other_dir.mkdir()

    web_manager.main_profile.working_dir = str(repo_dir)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(other_dir)

    overview = get_git_overview(web_manager, "main", 1001)

    assert overview["working_dir"] == str(repo_dir)
    assert overview["repo_found"] is True
    assert overview["repo_path"] == str(repo_dir)

def test_git_diff_uses_bot_profile_workdir(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    tracked = repo_dir / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    _run_git_command(repo_dir, "add", "tracked.txt")
    _run_git_command(repo_dir, "commit", "-m", "init")
    tracked.write_text("before\nafter\n", encoding="utf-8")

    other_dir = temp_dir / "other"
    other_dir.mkdir()

    web_manager.main_profile.working_dir = str(repo_dir)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(other_dir)

    diff = get_git_diff(web_manager, "main", 1001, "tracked.txt", staged=False)

    assert diff["path"] == "tracked.txt"
    assert "+after" in diff["diff"]

def test_git_proxy_settings_persist_to_app_settings_file(temp_dir: Path, monkeypatch: pytest.MonkeyPatch):
    settings_file = temp_dir / ".web_admin_settings.json"
    monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", settings_file)

    assert get_git_proxy_settings() == {"port": ""}

    saved = update_git_proxy_port("7897")

    assert saved == {"port": "7897"}
    assert get_git_proxy_settings() == {"port": "7897"}
    assert json.loads(settings_file.read_text(encoding="utf-8")) == {
        "git_proxy_port": "7897",
    }

def test_git_commands_explicitly_disable_proxy_when_port_is_empty(
    web_manager: MultiBotManager,
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings_file = temp_dir / ".web_admin_settings.json"
    monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", settings_file)
    update_git_proxy_port("")

    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    web_manager.main_profile.working_dir = str(repo_dir)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs):
        calls.append(cmd)
        if cmd[-2:] == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(cmd, 0, f"{repo_dir}\n", "")
        if "status" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "## main\n", "")
        if "log" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("bot.web.git_service.subprocess.run", fake_run)

    overview = get_git_overview(web_manager, "main", 1001)

    assert overview["repo_found"] is True
    assert calls[0][:7] == ["git", "-c", "core.fsmonitor=false", "-c", "http.proxy=", "-c", "https.proxy="]
    assert calls[1][:7] == ["git", "-c", "core.fsmonitor=false", "-c", "http.proxy=", "-c", "https.proxy="]

def test_git_commands_use_local_proxy_port_when_configured(
    web_manager: MultiBotManager,
    temp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings_file = temp_dir / ".web_admin_settings.json"
    monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", settings_file)
    update_git_proxy_port("7897")

    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    web_manager.main_profile.working_dir = str(repo_dir)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs):
        calls.append(cmd)
        if cmd[-2:] == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(cmd, 0, f"{repo_dir}\n", "")
        if "status" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "## main\n", "")
        if "log" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("bot.web.git_service.subprocess.run", fake_run)

    overview = get_git_overview(web_manager, "main", 1001)

    assert overview["repo_found"] is True
    assert calls[0][:7] == [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "http.proxy=http://127.0.0.1:7897",
        "-c",
        "https.proxy=http://127.0.0.1:7897",
    ]
    assert calls[1][:7] == [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "http.proxy=http://127.0.0.1:7897",
        "-c",
        "https.proxy=http://127.0.0.1:7897",
    ]

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
async def test_auth_route_auto_authenticates_loopback_as_admin(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: True)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/auth/me")
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["username"] == "127.0.0.1"
    assert payload["data"]["account_id"] == "local-admin"
    assert payload["data"]["user_id"] == 1001
    assert payload["data"]["token_protected"] is True
    assert "admin_ops" in payload["data"]["capabilities"]
    assert "manage_register_codes" in payload["data"]["capabilities"]

@pytest.mark.asyncio
async def test_loopback_login_ignores_credentials_and_returns_local_admin(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: True)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/auth/login", json={"username": "x", "password": "bad"})
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["username"] == "127.0.0.1"
    assert "manage_register_codes" in payload["data"]["capabilities"]

@pytest.mark.asyncio
async def test_local_admin_can_manage_register_codes(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: True)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            create_resp = await client.post("/api/admin/register-codes", json={"max_uses": 2})
            assert create_resp.status == 200
            created = (await create_resp.json())["data"]

            list_resp = await client.get("/api/admin/register-codes")
            assert list_resp.status == 200
            listed = (await list_resp.json())["data"]["items"]

            patch_resp = await client.patch(f"/api/admin/register-codes/{created['code_id']}", json={"max_uses_delta": 1, "disabled": True})
            assert patch_resp.status == 200
            patched = (await patch_resp.json())["data"]

            delete_resp = await client.delete(f"/api/admin/register-codes/{created['code_id']}")
            assert delete_resp.status == 200

    assert created["code"].startswith("INV-")
    assert listed[0]["code_preview"] == created["code_preview"]
    assert patched["max_uses"] == 3
    assert patched["disabled"] is True

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
    wave_dir = temp_dir / "waves"
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
                json={"input": {"path": str(wave_file)}},
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

@pytest.mark.asyncio
async def test_create_directory_route(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    workspace.mkdir()
    web_manager.main_profile.working_dir = str(workspace)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/bots/main/files/mkdir", json={"name": "docs"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["name"] == "docs"
            assert (workspace / "docs").is_dir()

@pytest.mark.asyncio
async def test_file_routes_serialize_last_modified_ns_as_string(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("# hello\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(workspace)
    change_working_directory(web_manager, "main", 1001, str(workspace))

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            read_resp = await client.get("/api/bots/main/files/read?filename=notes.md&mode=cat&lines=0")
            assert read_resp.status == 200
            read_payload = await read_resp.json()
            assert read_payload["data"]["last_modified_ns"] == str(target.stat().st_mtime_ns)

            write_resp = await client.post(
                "/api/bots/main/files/write",
                json={
                    "path": "notes.md",
                    "content": "# updated\n",
                    "expected_mtime_ns": read_payload["data"]["last_modified_ns"],
                },
            )
            assert write_resp.status == 200
            write_payload = await write_resp.json()

    assert write_payload["data"]["last_modified_ns"] == str(target.stat().st_mtime_ns)
    assert target.read_text(encoding="utf-8") == "# updated\n"

@pytest.mark.asyncio
async def test_workspace_search_routes_use_current_working_directory(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "main.py").write_text("class App:\n    def run(self):\n        needle = True\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(workspace)
    change_working_directory(web_manager, "main", 1001, str(workspace))

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            quick_resp = await client.get("/api/bots/main/workspace/quick-open?q=main&limit=5")
            search_resp = await client.get("/api/bots/main/workspace/search?q=needle&limit=5")
            outline_resp = await client.get("/api/bots/main/workspace/outline?path=src/main.py")

            assert quick_resp.status == 200
            quick_payload = await quick_resp.json()
            assert quick_payload["data"]["items"][0]["path"] == "src/main.py"

            assert search_resp.status == 200
            search_payload = await search_resp.json()
            assert search_payload["data"]["items"][0]["path"] == "src/main.py"
            assert search_payload["data"]["items"][0]["line"] == 3

            assert outline_resp.status == 200
            outline_payload = await outline_resp.json()
            assert outline_payload["data"]["items"] == [
                {"name": "App", "kind": "class", "line": 1},
                {"name": "run", "kind": "function", "line": 2},
            ]

@pytest.mark.asyncio
async def test_write_file_route_updates_file(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("# hello\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(workspace)
    change_working_directory(web_manager, "main", 1001, str(workspace))

    previous = read_file_content(web_manager, "main", 1001, "notes.md", mode="cat", lines=0)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post(
                "/api/bots/main/files/write",
                json={
                    "path": "notes.md",
                    "content": "# updated\n",
                    "expected_mtime_ns": previous["last_modified_ns"],
                },
            )
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["path"] == "notes.md"
    assert target.read_text(encoding="utf-8") == "# updated\n"

@pytest.mark.asyncio
async def test_create_text_file_route_creates_file(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    workspace.mkdir()
    web_manager.main_profile.working_dir = str(workspace)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/bots/main/files/create", json={"filename": "notes.md", "content": "# hello\n"})
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["path"] == "notes.md"
    assert (workspace / "notes.md").read_text(encoding="utf-8") == "# hello\n"

@pytest.mark.asyncio
async def test_rename_path_route_renames_file(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    workspace.mkdir()
    (workspace / "notes.md").write_text("# hello\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(workspace)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/bots/main/files/rename", json={"path": "notes.md", "new_name": "draft.md"})
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["old_path"] == "notes.md"
    assert payload["data"]["path"] == "draft.md"
    assert not (workspace / "notes.md").exists()
    assert (workspace / "draft.md").read_text(encoding="utf-8") == "# hello\n"

@pytest.mark.asyncio
async def test_delete_path_route_recursively_removes_directory(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workspace = temp_dir / "workspace"
    target = workspace / "docs" / "guides"
    target.mkdir(parents=True)
    (target / "intro.txt").write_text("hello\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(workspace)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/bots/main/files/delete", json={"path": "docs"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["deleted_type"] == "directory"
            assert not (workspace / "docs").exists()

@pytest.mark.asyncio
async def test_api_routes_disable_cache(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots")
            assert resp.status == 200
            assert resp.headers["Cache-Control"] == "no-store"
            assert resp.headers["Pragma"] == "no-cache"

@pytest.mark.asyncio
async def test_index_route_disables_cache(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/")
            assert resp.status == 200
            assert resp.headers["Cache-Control"] == "no-store, no-cache, must-revalidate"
            assert resp.headers["Pragma"] == "no-cache"
            assert resp.headers["Expires"] == "0"

@pytest.mark.asyncio
async def test_chat_stream_route_returns_sse_events(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_stream_chat(manager, alias, user_id, message):
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
async def test_terminal_websocket_requires_token(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server._is_loopback_request", lambda _request: False)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with pytest.raises(WSServerHandshakeError):
                await client.ws_connect("/terminal/ws")

@pytest.mark.asyncio
async def test_terminal_websocket_forwards_process_output_and_input(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    started: dict[str, object] = {"writes": []}

    class FakeProcess:
        is_pty = False
        pid = 4321
        reads = [b"PS C:\\demo> ", b"output\r\n"]

        def read(self, timeout: int = 1000) -> bytes:
            if self.reads:
                return self.reads.pop(0)
            return b""

        def write(self, data: bytes) -> None:
            started["writes"].append(data)

        def isalive(self) -> bool:
            return bool(self.reads)

        def terminate(self) -> None:
            started["terminated"] = True

        def close(self) -> None:
            started["closed"] = True

    def fake_create_shell_process(shell_type: str, cwd: str, use_pty: bool = True):
        started["shell_type"] = shell_type
        started["cwd"] = cwd
        started["use_pty"] = use_pty
        return FakeProcess()

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.create_shell_process", side_effect=fake_create_shell_process):
                with patch("bot.web.server.get_default_shell", return_value="bash"):
                    ws = await client.ws_connect("/terminal/ws?token=secret")
                    await ws.send_json({"cwd": str(temp_dir)})
                    first_message = await ws.receive_json()
                    assert first_message == {"pty_mode": False}
                    output_message = await ws.receive()
                    assert output_message.data == b"PS C:\\demo> "
                    await ws.send_str("pwd\r")
                    for _ in range(20):
                        if started["writes"]:
                            break
                        await asyncio.sleep(0.01)
                    assert started["cwd"] == str(temp_dir)
                    assert started["shell_type"] == "bash"
                    assert started["use_pty"] is True
                    assert started["writes"] == [b"pwd\r"]
                    await ws.close()

@pytest.mark.asyncio
async def test_terminal_websocket_ignores_disconnect_while_forwarding_output(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)
    request = MagicMock()
    request.query = {}
    request.transport = None

    state: dict[str, object] = {}

    class FakeProcess:
        is_pty = False
        pid = 9876

        def terminate(self) -> None:
            state["terminated"] = True

        def close(self) -> None:
            state["closed"] = True

    class FakeOutputPump:
        def __init__(self, process):
            self._reads = [b"hello", _TERMINAL_OUTPUT_EOF]

        def start(self, loop) -> None:
            state["pump_started"] = True

        def stop(self) -> None:
            state["pump_stopped"] = True

        async def read(self):
            return self._reads.pop(0)

    class FakeWebSocket:
        closed = True

        def __init__(self):
            self.binary_writes = 0

        async def prepare(self, req):
            return self

        async def receive(self):
            return MagicMock(type=WSMsgType.TEXT, data="{}")

        async def send_json(self, payload):
            state["pty_payload"] = payload

        async def send_bytes(self, data):
            self.binary_writes += 1
            raise ClientConnectionResetError("Cannot write to closing transport")

    fake_ws = FakeWebSocket()
    fake_process = FakeProcess()

    with patch.object(server, "_with_auth", AsyncMock(return_value=AuthContext(user_id=1001, token_used=False))), \
         patch("bot.web.server.get_default_shell", return_value="powershell"), \
         patch("bot.web.server.create_shell_process", return_value=fake_process), \
         patch("bot.web.server._TerminalOutputPump", FakeOutputPump), \
         patch("bot.web.server.web.WebSocketResponse", return_value=fake_ws), \
         patch("bot.web.server.logger.exception") as exception_log:
        response = await server.terminal_ws(request)

    assert response is fake_ws
    assert state["pty_payload"] == {"pty_mode": False}
    assert state["pump_started"] is True
    assert state["pump_stopped"] is True
    assert state["terminated"] is True
    assert state["closed"] is True
    assert fake_ws.binary_writes == 1
    exception_log.assert_not_called()

@pytest.mark.asyncio
async def test_run_system_script_executes_full_filename_from_bot_scripts_dir(
    monkeypatch: pytest.MonkeyPatch,
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "network_traffic.ps1"
    script_path.write_text("# 网络流量\n", encoding="utf-8")

    web_manager.main_profile.working_dir = str(tmp_path)
    monkeypatch.setattr("bot.platform.scripts.get_runtime_platform", lambda: "windows")

    execute_calls: list[Path] = []

    def fake_execute_script(path: Path) -> tuple[bool, str]:
        execute_calls.append(path)
        return True, "ok"

    monkeypatch.setattr("bot.web.api_service.execute_script", fake_execute_script)

    payload = await run_system_script(web_manager, "main", 1001, "network_traffic.ps1")

    assert execute_calls == [script_path.resolve()]
    assert payload == {
        "script_name": "network_traffic.ps1",
        "success": True,
        "output": "ok",
    }

@pytest.mark.asyncio
async def test_bot_run_script_stream_returns_sse_events(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_stream_system_script(
        manager: MultiBotManager,
        alias: str,
        user_id: int,
        script_name: str,
    ):
        assert alias == "main"
        assert user_id == 1001
        assert script_name == "build_web_frontend.sh"
        yield {"type": "log", "text": "npm run build"}
        yield {"type": "done", "script_name": script_name, "success": True, "output": "Web 前端构建完成"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.stream_system_script", fake_stream_system_script):
                resp = await client.post("/api/bots/main/scripts/run/stream", json={"script_name": "build_web_frontend.sh"})
                assert resp.status == 200
                body = await resp.text()
                assert "event: log" in body
                assert "npm run build" in body
                assert "event: done" in body
                assert "Web 前端构建完成" in body

@pytest.mark.asyncio
async def test_stream_system_script_normalizes_done_event_script_name_to_full_filename(
    monkeypatch: pytest.MonkeyPatch,
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_path = scripts_dir / "network_traffic.ps1"
    script_path.write_text("# 网络流量\n", encoding="utf-8")

    web_manager.main_profile.working_dir = str(tmp_path)
    monkeypatch.setattr("bot.platform.scripts.get_runtime_platform", lambda: "windows")

    def fake_stream_execute_script(path: Path):
        assert path == script_path.resolve()
        yield {"type": "log", "text": "checking"}
        yield {"type": "done", "script_name": "network_traffic", "success": True, "output": "ok"}

    monkeypatch.setattr("bot.web.api_service.stream_execute_script", fake_stream_execute_script)

    events = [
        event
        async for event in api_service.stream_system_script(web_manager, "main", 1001, "network_traffic.ps1")
    ]

    assert events == [
        {"type": "log", "text": "checking"},
        {"type": "done", "script_name": "network_traffic.ps1", "success": True, "output": "ok"},
    ]

@pytest.mark.asyncio
async def test_admin_restart_returns_response_before_triggering_restart(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.RESTART_RESPONSE_DELAY_SECONDS", 0.001, raising=False)

    restart_calls: list[str] = []

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.request_restart", side_effect=lambda: restart_calls.append("called")):
                resp = await client.post("/api/admin/restart")
                assert resp.status == 200
                payload = await resp.json()
                assert payload["data"]["restart_requested"] is True
                assert restart_calls == []
                await asyncio.sleep(0.02)
                assert restart_calls == ["called"]

@pytest.mark.asyncio
async def test_admin_avatar_assets_route_lists_available_files(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    avatar_dir = temp_dir / "assets" / "avatars"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "avatar_01.png").write_bytes(_png_bytes(64, 64))
    (avatar_dir / "claude-blue.png").write_bytes(_png_bytes(64, 64))
    (avatar_dir / "too-small.png").write_bytes(_png_bytes(32, 32))
    monkeypatch.setattr(api_service, "_avatar_asset_dirs", lambda: [avatar_dir], raising=False)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/assets/avatars")
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["items"] == [
        {"name": "avatar_01.png", "url": "/assets/avatars/avatar_01.png"},
        {"name": "claude-blue.png", "url": "/assets/avatars/claude-blue.png"},
    ]

@pytest.mark.asyncio
async def test_admin_add_bot_route_accepts_avatar_name(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    avatar_dir = temp_dir / "assets" / "avatars"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "claude-blue.png").write_bytes(_png_bytes(64, 64))
    monkeypatch.setattr(api_service, "_avatar_asset_dirs", lambda: [avatar_dir], raising=False)

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.manager.resolve_cli_executable", return_value="codex"), \
                 patch.object(web_manager, "_start_profile", AsyncMock(return_value=None)):
                resp = await client.post(
                    "/api/admin/bots",
                    json={
                        "alias": "team2",
                        "token": "",
                        "bot_mode": "cli",
                        "cli_type": "codex",
                        "cli_path": "codex",
                        "working_dir": str(temp_dir),
                        "avatar_name": "claude-blue.png",
                    },
                )
                assert resp.status == 200
                payload = await resp.json()

    assert payload["data"]["bot"]["avatar_name"] == "claude-blue.png"
    assert web_manager.managed_profiles["team2"].avatar_name == "claude-blue.png"

@pytest.mark.asyncio
async def test_admin_update_avatar_route_persists_avatar_selection(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    avatar_dir = temp_dir / "assets" / "avatars"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "mint-teal.png").write_bytes(_png_bytes(64, 64))
    monkeypatch.setattr(api_service, "_avatar_asset_dirs", lambda: [avatar_dir], raising=False)

    web_manager.managed_profiles["team2"] = BotProfile(
        alias="team2",
        token="",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(temp_dir),
        enabled=True,
        avatar_name="avatar_01.png",
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch(
                "/api/admin/bots/team2/avatar",
                json={"avatar_name": "mint-teal.png"},
            )
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"]["bot"]["avatar_name"] == "mint-teal.png"
    assert web_manager.managed_profiles["team2"].avatar_name == "mint-teal.png"

@pytest.mark.asyncio
async def test_admin_update_avatar_route_rejects_invalid_filename(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    web_manager.managed_profiles["team2"] = BotProfile(
        alias="team2",
        token="",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(temp_dir),
        enabled=True,
        avatar_name="avatar_01.png",
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch(
                "/api/admin/bots/team2/avatar",
                json={"avatar_name": "../evil.png"},
            )
            assert resp.status == 400
            payload = await resp.json()

    assert payload["error"]["code"] == "invalid_avatar_name"

@pytest.mark.asyncio
async def test_cli_params_routes_support_get_patch_and_reset(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    web_manager.main_profile.cli_type = "codex"
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots/main/cli-params")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["cli_type"] == "codex"
            assert payload["data"]["params"]["reasoning_effort"] == "xhigh"
            assert payload["data"]["schema"]["reasoning_effort"]["type"] == "string"
            assert payload["data"]["schema"]["reasoning_effort"]["enum"] == ["xhigh", "high", "medium", "low"]

            resp = await client.patch(
                "/api/bots/main/cli-params",
                json={"key": "reasoning_effort", "value": "high"},
            )
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["params"]["reasoning_effort"] == "high"

            resp = await client.post("/api/bots/main/cli-params/reset")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["params"]["reasoning_effort"] == "xhigh"

@pytest.mark.asyncio
async def test_admin_tunnel_route_returns_manual_public_url(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.web.server.WEB_PUBLIC_URL", "https://demo.trycloudflare.com")

    server = WebApiServer(web_manager)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/tunnel")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["public_url"] == "https://demo.trycloudflare.com"
            assert payload["data"]["source"] == "manual_config"

@pytest.mark.asyncio
async def test_admin_git_proxy_routes_support_get_and_patch(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", temp_dir / ".web_admin_settings.json")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/admin/git-proxy")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"] == {"port": ""}

            resp = await client.patch("/api/admin/git-proxy", json={"port": "7897"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"] == {"port": "7897"}

            resp = await client.get("/api/admin/git-proxy")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"] == {"port": "7897"}

@pytest.mark.asyncio
async def test_admin_git_proxy_route_rejects_invalid_port(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])
    monkeypatch.setattr("bot.app_settings.APP_SETTINGS_FILE", temp_dir / ".web_admin_settings.json")

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch("/api/admin/git-proxy", json={"port": "70000"})
            assert resp.status == 400
            payload = await resp.json()
            assert payload["error"]["code"] == "invalid_git_proxy_port"

@pytest.mark.asyncio
async def test_admin_update_routes_proxy_update_service(web_manager, monkeypatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    base_status = {
        "current_version": "1.0.0",
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

    toggle_mock.assert_called_once_with(False)
    check_mock.assert_called_once()
    download_mock.assert_called_once()

@pytest.mark.asyncio
async def test_admin_update_download_stream_returns_sse_events(web_manager, monkeypatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    base_status = {
        "current_version": "1.0.0",
        "update_enabled": True,
        "update_channel": "release",
        "last_checked_at": "",
        "last_available_version": "1.0.1",
        "last_available_release_url": "https://github.com/owner/repo/releases/tag/v1.0.1",
        "last_available_notes": "Bugfixes",
        "pending_update_version": "1.0.1",
        "pending_update_path": ".updates/cli-bridge-windows-x64.zip",
        "pending_update_notes": "Bugfixes",
        "pending_update_platform": "windows-x64",
        "update_last_error": "",
    }

    async def fake_stream_update_download():
        yield {
            "type": "progress",
            "phase": "downloading",
            "downloaded_bytes": 512,
            "total_bytes": 1024,
            "percent": 50,
        }
        yield {
            "type": "done",
            "status": base_status,
        }

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.stream_update_download", fake_stream_update_download):
                resp = await client.post("/api/admin/update/download/stream", json={})
                assert resp.status == 200
                body = await resp.text()

    assert "event: progress" in body
    assert '"percent": 50' in body
    assert "event: done" in body
    assert '"pending_update_version": "1.0.1"' in body

@pytest.mark.asyncio
async def test_web_server_start_schedules_auto_update_refresh_when_enabled(web_manager):
    server = WebApiServer(web_manager)
    created_coroutines: list[Any] = []

    def fake_create_task(coro):
        created_coroutines.append(coro)
        coro.close()
        return MagicMock()

    with patch("bot.web.server.get_update_status", return_value={"update_enabled": True}), \
         patch("bot.web.server.asyncio.create_task", side_effect=fake_create_task) as create_task, \
         patch.object(server, "_runner", None):
        with patch.object(server, "_build_app", return_value=web.Application()):
            with patch("bot.web.server.web.AppRunner") as runner_cls:
                runner = AsyncMock()
                runner_cls.return_value = runner
                with patch("bot.web.server.web.TCPSite") as site_cls:
                    site = AsyncMock()
                    site_cls.return_value = site
                    await server.start()

    create_task.assert_called()
    assert created_coroutines

@pytest.mark.asyncio
async def test_auto_refresh_update_status_downloads_latest_update_when_enabled(web_manager):
    server = WebApiServer(web_manager)
    repo_root = Path(__file__).resolve().parents[1]

    with patch(
        "bot.web.server.get_update_status",
        return_value={
            "update_enabled": True,
            "current_version": "1.0.5",
            "pending_update_version": "",
        },
    ), patch(
        "bot.web.server.check_for_updates",
        return_value={
            "update_enabled": True,
            "current_version": "1.0.5",
            "last_available_version": "1.0.6",
            "pending_update_version": "",
        },
    ) as check_mock, patch(
        "bot.web.server.download_latest_update",
        return_value={
            "update_enabled": True,
            "current_version": "1.0.5",
            "pending_update_version": "1.0.6",
        },
    ) as download_mock:
        await server._auto_refresh_update_status()

    check_mock.assert_called_once_with()
    download_mock.assert_called_once_with(repo_root)

@pytest.mark.asyncio
async def test_admin_rename_bot_route_updates_alias(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    workdir = temp_dir / "repo"
    workdir.mkdir()
    web_manager.managed_profiles["sub1"] = BotProfile(
        alias="sub1",
        token="sub-token",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(workdir),
    )

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.patch("/api/admin/bots/sub1/alias", json={"new_alias": "team1"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["data"]["bot"]["alias"] == "team1"
            assert "team1" in web_manager.managed_profiles
            assert "sub1" not in web_manager.managed_profiles

@pytest.mark.asyncio
async def test_admin_tunnel_restart_uses_tunnel_service(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    class FakeTunnelService:
        def __init__(self):
            self.restart_called = False

        def snapshot(self):
            return {
                "mode": "cloudflare_quick",
                "status": "stopped",
                "source": "quick_tunnel",
                "public_url": "",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": None,
            }

        async def restart(self):
            self.restart_called = True
            return {
                "mode": "cloudflare_quick",
                "status": "running",
                "source": "quick_tunnel",
                "public_url": "https://fresh.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": 1234,
            }

    server = WebApiServer(web_manager)
    fake_tunnel = FakeTunnelService()
    server._tunnel_service = fake_tunnel
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/admin/tunnel/restart")
            assert resp.status == 200
            payload = await resp.json()
            assert fake_tunnel.restart_called is True
            assert payload["data"]["status"] == "running"
            assert payload["data"]["public_url"] == "https://fresh.trycloudflare.com"

@pytest.mark.asyncio
async def test_admin_tunnel_restart_copies_public_url(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    class FakeTunnelService:
        def snapshot(self):
            return {
                "mode": "cloudflare_quick",
                "status": "stopped",
                "source": "quick_tunnel",
                "public_url": "",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": None,
            }

        async def restart(self):
            return {
                "mode": "cloudflare_quick",
                "status": "running",
                "source": "quick_tunnel",
                "public_url": "https://fresh.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": 1234,
            }

    server = WebApiServer(web_manager)
    server._tunnel_service = FakeTunnelService()
    server._copy_text_to_clipboard = MagicMock(return_value=True)
    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.post("/api/admin/tunnel/restart")
            assert resp.status == 200

    server._copy_text_to_clipboard.assert_called_once_with("https://fresh.trycloudflare.com")

@pytest.mark.asyncio
async def test_notify_tunnel_public_url_returns_clipboard_result_for_quick_tunnel(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)
    server._copy_text_to_clipboard = MagicMock(return_value=True)

    result = await server._notify_tunnel_public_url(
        {
            "mode": "cloudflare_quick",
            "status": "running",
            "source": "quick_tunnel",
            "public_url": "https://failed.trycloudflare.com",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": 1234,
        },
        reason="web_server_start",
    )

    assert result is True
    server._copy_text_to_clipboard.assert_called_once_with("https://failed.trycloudflare.com")

@pytest.mark.asyncio
async def test_notify_tunnel_public_url_returns_false_when_clipboard_and_qr_both_fail(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)
    server._copy_text_to_clipboard = MagicMock(return_value=False)
    server._print_public_url_qr = MagicMock(return_value=False)

    result = await server._notify_tunnel_public_url(
        {
            "mode": "cloudflare_quick",
            "status": "running",
            "source": "quick_tunnel",
            "public_url": "https://web-only.trycloudflare.com",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": 1234,
        },
        reason="web_server_start",
    )

    assert result is False
    server._copy_text_to_clipboard.assert_called_once_with("https://web-only.trycloudflare.com")
    server._print_public_url_qr.assert_called_once_with("https://web-only.trycloudflare.com")

@pytest.mark.asyncio
async def test_web_server_start_copies_public_url_on_autostart(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    class FakeTunnelService:
        def should_autostart(self):
            return True

        async def start(self):
            return {
                "mode": "cloudflare_quick",
                "status": "running",
                "source": "quick_tunnel",
                "public_url": "https://startup.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": 1234,
            }

        async def stop(self):
            return {
                "mode": "cloudflare_quick",
                "status": "stopped",
                "source": "quick_tunnel",
                "public_url": "",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": None,
            }

    class FakeRunner:
        async def setup(self):
            return None

        async def cleanup(self):
            return None

    class FakeSite:
        def __init__(self, runner, host, port):
            self.runner = runner
            self.host = host
            self.port = port

        async def start(self):
            return None

    monkeypatch.setattr("bot.web.server.web.AppRunner", lambda app: FakeRunner())
    monkeypatch.setattr("bot.web.server.web.TCPSite", FakeSite)

    server = WebApiServer(web_manager, tunnel_service=FakeTunnelService())
    server._copy_text_to_clipboard = MagicMock(return_value=True)
    await server.start()
    await server.stop()

    server._copy_text_to_clipboard.assert_called_once_with("https://startup.trycloudflare.com")

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_web_server_start_logs_bracketed_ipv6_url(
    web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("bot.web.server.WEB_HOST", "::1")
    monkeypatch.setattr("bot.web.server.WEB_PORT", 8765)
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_ALLOWED_ORIGINS", [])

    class FakeTunnelService:
        def should_autostart(self):
            return False

        async def stop(self):
            return None

    class FakeRunner:
        async def setup(self):
            return None

        async def cleanup(self):
            return None

    class FakeSite:
        def __init__(self, runner, host, port):
            self.runner = runner
            self.host = host
            self.port = port

        async def start(self):
            return None

    log_lines: list[str] = []

    def fake_info(message, *args):
        log_lines.append(message % args if args else message)

    monkeypatch.setattr("bot.web.server.web.AppRunner", lambda app: FakeRunner())
    monkeypatch.setattr("bot.web.server.web.TCPSite", FakeSite)
    monkeypatch.setattr("bot.web.server.logger.info", fake_info)

    server = WebApiServer(web_manager, tunnel_service=FakeTunnelService())
    await server.start()
    await server.stop()

    assert any("http://[::1]:8765" in line for line in log_lines)

@pytest.mark.asyncio
async def test_web_server_start_in_web_only_mode_copies_tunnel_url(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    class FakeTunnelService:
        def should_autostart(self):
            return True

        async def start(self):
            return {
                "mode": "cloudflare_quick",
                "status": "running",
                "source": "quick_tunnel",
                "public_url": "https://web-only-start.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": 4321,
            }

        async def stop(self):
            return {
                "mode": "cloudflare_quick",
                "status": "stopped",
                "source": "quick_tunnel",
                "public_url": "",
                "local_url": "http://127.0.0.1:8765",
                "last_error": "",
                "pid": None,
            }

    class FakeRunner:
        async def setup(self):
            return None

        async def cleanup(self):
            return None

    class FakeSite:
        def __init__(self, runner, host, port):
            self.runner = runner
            self.host = host
            self.port = port

        async def start(self):
            return None

    monkeypatch.setattr("bot.web.server.web.AppRunner", lambda app: FakeRunner())
    monkeypatch.setattr("bot.web.server.web.TCPSite", FakeSite)

    server = WebApiServer(web_manager, tunnel_service=FakeTunnelService())
    server._copy_text_to_clipboard = MagicMock(return_value=True)
    await server.start()
    await server.stop()

    server._copy_text_to_clipboard.assert_called_once_with("https://web-only-start.trycloudflare.com")

@pytest.mark.asyncio
async def test_notify_tunnel_public_url_skips_non_quick_tunnel(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)
    server._copy_text_to_clipboard = MagicMock(return_value=True)

    result = await server._notify_tunnel_public_url(
        {
            "mode": "cloudflare_quick",
            "status": "running",
            "source": "configured",
            "public_url": "https://no-token.trycloudflare.com",
            "local_url": "http://127.0.0.1:8765",
            "last_error": "",
            "pid": 1234,
        },
        reason="web_server_start",
    )

    assert result is False
    server._copy_text_to_clipboard.assert_not_called()

def test_read_missing_file_raises(web_manager: MultiBotManager):
    with pytest.raises(WebApiError) as exc_info:
        read_file_content(web_manager, "main", 1001, "missing.txt")
    assert exc_info.value.code == "file_not_found"

@pytest.mark.asyncio
async def test_run_cli_chat_retries_invalid_claude_session(web_manager: MultiBotManager):
    web_manager.main_profile.cli_type = "claude"

    session = get_session_for_alias(web_manager, "main", 1001)
    session.claude_session_id = "claude-stale"
    session.claude_session_initialized = True
    session.persist = MagicMock()

    first_process = MagicMock()
    second_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="claude"), \
         patch("bot.web.api_service.build_cli_command", side_effect=[(["claude", "-r", "claude-stale"], False), (["claude"], False)]) as build_mock, \
         patch("bot.web.api_service.subprocess.Popen", side_effect=[first_process, second_process]), \
         patch("bot.web.api_service._communicate_process", new_callable=AsyncMock, side_effect=[
             ("Error: Session ID not found", 1),
             ("OK", 0),
         ]) as communicate_mock:
        data = await run_cli_chat(web_manager, "main", 1001, "hello")

    assert communicate_mock.await_count == 2
    assert build_mock.call_count == 2
    assert build_mock.call_args_list[0].kwargs["resume_session"] is True
    assert build_mock.call_args_list[1].kwargs["resume_session"] is False
    assert data["output"] == "OK"
    assert data["returncode"] == 0
    assert session.claude_session_initialized is True
    session.persist.assert_called()

@pytest.mark.asyncio
async def test_run_cli_chat_claude_done_detector_avoids_communicate_and_strips_output(web_manager: MultiBotManager):
    from bot.claude_done import build_claude_done_session

    web_manager.main_profile.cli_type = "claude"

    class FakeStdout:
        def __init__(self):
            self._lines = [
                '{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"最终回答\\n__TCB_DONE_abc123__"}}}\n',
                '{"type":"result","subtype":"success","session_id":"sess-1","result":"最终回答\\n__TCB_DONE_abc123__"}\n',
            ]

        def readline(self):
            return self._lines.pop(0) if self._lines else ""

        def read(self):
            return ""

    class FakeProcess:
        def __init__(self):
            self.stdout = FakeStdout()
            self.stdin = None
            self.returncode = None
            self.terminate = MagicMock(side_effect=self._terminate)

        def _terminate(self):
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    fake_process = FakeProcess()
    done_session = build_claude_done_session(
        "hello",
        cli_type="claude",
        enabled=True,
        quiet_seconds=0.0,
        sentinel_mode="nonce",
        nonce="abc123",
    )

    with patch("bot.web.api_service.resolve_cli_executable", return_value="claude"), \
         patch("bot.web.api_service.build_claude_done_session", return_value=done_session), \
         patch("bot.web.api_service.build_cli_command", return_value=(["claude"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch(
             "bot.web.api_service._communicate_process",
             new_callable=AsyncMock,
             side_effect=AssertionError("communicate should not be used when done detector is enabled"),
         ):
        data = await run_cli_chat(web_manager, "main", 1001, "hello")

    assert data["output"] == "最终回答"
    assert data["returncode"] == 0
    assert "__TCB_DONE_" not in data["output"]
    fake_process.terminate.assert_called_once()

@pytest.mark.asyncio
async def test_run_cli_chat_persists_assistant_elapsed_seconds(web_manager: MultiBotManager):
    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch(
             "bot.web.api_service._communicate_codex_process",
             new_callable=AsyncMock,
             return_value=("完成回复", "thread-1", 0),
         ):
        data = await run_cli_chat(web_manager, "main", 1001, "hello")

    assert data["output"] == "完成回复"
    assert isinstance(data["elapsed_seconds"], int)
    assert data["elapsed_seconds"] >= 0
    assert data["message"]["role"] == "assistant"
    assert data["message"]["content"] == "完成回复"

@pytest.mark.asyncio
async def test_run_cli_chat_passes_hidden_process_kwargs_to_popen(web_manager: MultiBotManager):
    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.build_hidden_process_kwargs", return_value={"creationflags": 123}) as hidden_mock, \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process) as popen_mock, \
         patch(
             "bot.web.api_service._communicate_codex_process",
             new_callable=AsyncMock,
             return_value=("完成回复", "thread-1", 0),
         ):
        await run_cli_chat(web_manager, "main", 1001, "hello")

    hidden_mock.assert_called_once_with()
    assert popen_mock.call_args.kwargs["creationflags"] == 123

@pytest.mark.asyncio
async def test_communicate_process_waits_without_forced_timeout():
    class FakeProcess:
        def __init__(self):
            self.returncode = 0
            self.timeout_arg = None
            self.terminate = MagicMock()
            self.kill = MagicMock()

        def communicate(self, timeout=None):
            self.timeout_arg = timeout
            if timeout is not None:
                raise subprocess.TimeoutExpired(["codex"], timeout, output="partial")
            return "完成回复", None

        def wait(self, timeout=None):
            return self.returncode

    fake_process = FakeProcess()

    output, returncode = await api_service._communicate_process(fake_process)

    assert output == "完成回复"
    assert returncode == 0
    assert fake_process.timeout_arg is None
    fake_process.terminate.assert_not_called()
    fake_process.kill.assert_not_called()

@pytest.mark.asyncio
async def test_run_cli_chat_compiles_assistant_prompt_before_building_command(
    web_manager: MultiBotManager, temp_dir: Path
):
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
    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.is_compaction_prompt_active", return_value=False) as prompt_active_mock, \
         patch(
             "bot.web.api_service.sync_managed_prompt_files",
             return_value=ManagedPromptSyncResult(False, False, "hash-current"),
         ) as sync_mock, \
         patch(
             "bot.web.api_service.compile_assistant_prompt",
             return_value=AssistantPromptPayload(
                 prompt_text="hello from payload",
                 managed_prompt_hash_seen="hash-updated",
             ),
         ) as compiler, \
         patch("bot.web.api_service.record_assistant_capture", return_value={"id": "cap_1"}) as capture_mock, \
         patch("bot.web.api_service.refresh_compaction_state") as refresh_mock, \
         patch("bot.web.api_service.list_pending_capture_ids", return_value=["cap_0", "cap_1"]) as pending_mock, \
         patch("bot.web.api_service.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]) as surface_mock, \
         patch("bot.web.api_service.finalize_compaction", return_value="none") as finalize_mock, \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)) as build_mock, \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_codex_process", new_callable=AsyncMock, return_value=("ok", "thread-1", 0)):
        await run_cli_chat(web_manager, "assistant1", 1001, "hello")

    prompt_active_mock.assert_called_once_with(ANY)
    compiler.assert_called_once_with(
        "hello",
        managed_prompt_hash="hash-current",
        seen_managed_prompt_hash=None,
    )
    assert sync_mock.call_count == 2
    capture_mock.assert_called_once()
    refresh_mock.assert_called_once_with(ANY, latest_capture={"id": "cap_1"})
    pending_mock.assert_called_once()
    assert surface_mock.call_count == 2
    finalize_mock.assert_called_once_with(
        ANY,
        before={"a": "1"},
        after={"a": "1"},
        consumed_capture_ids=["cap_0", "cap_1"],
        review_prompt_active=False,
    )
    session = get_session_for_alias(web_manager, "assistant1", 1001)
    assert session.managed_prompt_hash_seen == "hash-updated"
    assert build_mock.call_args.kwargs["user_text"] == "hello from payload"

@pytest.mark.asyncio
async def test_execute_assistant_run_request_applies_dream_result_and_skips_captures(
    web_manager: MultiBotManager, temp_dir: Path
):
    workdir = temp_dir / "assistant-root-dream"
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
    fake_process = MagicMock()
    request = AssistantRunRequest(
        run_id="run_dream_1",
        source="cron",
        bot_alias="assistant1",
        user_id=-77,
        text="根据近期工作做自我完善",
        interactive=False,
        visible_text="根据近期工作做自我完善",
        context_user_id=1001,
        task_mode="dream",
        task_payload={
            "prompt": "根据近期工作做自我完善",
            "mode": "dream",
            "lookback_hours": 24,
            "history_limit": 40,
            "capture_limit": 20,
            "deliver_mode": "silent",
        },
        job_id="daily_dream",
        scheduled_at="2026-04-20T09:00:00+08:00",
    )

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch(
             "bot.web.api_service.sync_managed_prompt_files",
             return_value=ManagedPromptSyncResult(False, False, "hash-current"),
         ), \
         patch(
             "bot.web.api_service.prepare_dream_prompt",
             return_value=AssistantDreamPreparedPrompt(
                 prompt_text="dream prompt payload",
                 context_stats={"history_count": 2, "capture_count": 1},
             ),
         ) as prepare_mock, \
         patch(
             "bot.web.api_service.compile_assistant_prompt",
             return_value=AssistantPromptPayload(
                 prompt_text="dream prompt payload",
                 managed_prompt_hash_seen="hash-dream",
             ),
         ), \
         patch("bot.web.api_service.record_assistant_capture", return_value={"id": "cap_1"}) as capture_mock, \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)) as build_mock, \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch(
             "bot.web.api_service._communicate_codex_process",
             new_callable=AsyncMock,
             return_value=(
                 "摘要\n<DREAM_RESULT>{\"summary\":\"dream 完成\",\"working_memory\":{},\"knowledge_entries\":[],\"proposal\":null}</DREAM_RESULT>",
                 "thread-1",
                 0,
             ),
         ), \
         patch(
             "bot.web.api_service.apply_dream_result",
             return_value=AssistantDreamApplyResult(
                 summary="dream 完成",
                 applied_paths=["C:/repo/.assistant/memory/working/recent_summary.md"],
                 proposal_id="pr_123",
                 audit_path="C:/repo/.assistant/audit/dream/run_dream_1.json",
             ),
         ) as apply_mock:
        result = await execute_assistant_run_request(web_manager, request)

    prepare_mock.assert_called_once()
    capture_mock.assert_not_called()
    assert build_mock.call_args.kwargs["user_text"] == "dream prompt payload"
    apply_mock.assert_called_once()
    assert result["output"] == "dream 完成"
    assert result["proposal_id"] == "pr_123"
    assert result["applied_paths"] == ["C:/repo/.assistant/memory/working/recent_summary.md"]

@pytest.mark.asyncio
async def test_run_cli_chat_resyncs_managed_prompts_after_noop_compaction(
    web_manager: MultiBotManager, temp_dir: Path
):
    workdir = temp_dir / "assistant-root-noop"
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
    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.is_compaction_prompt_active", return_value=True), \
         patch(
             "bot.web.api_service.sync_managed_prompt_files",
             return_value=ManagedPromptSyncResult(False, False, "hash-current"),
         ) as sync_mock, \
         patch(
             "bot.web.api_service.compile_assistant_prompt",
             return_value=AssistantPromptPayload(
                 prompt_text="hello from payload",
                 managed_prompt_hash_seen="hash-updated",
             ),
         ), \
         patch("bot.web.api_service.record_assistant_capture", return_value={"id": "cap_1"}), \
         patch("bot.web.api_service.refresh_compaction_state"), \
         patch("bot.web.api_service.list_pending_capture_ids", return_value=["cap_1"]), \
         patch("bot.web.api_service.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]), \
         patch("bot.web.api_service.finalize_compaction", return_value="noop") as finalize_mock, \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_codex_process", new_callable=AsyncMock, return_value=("ok", "thread-1", 0)):
        await run_cli_chat(web_manager, "assistant1", 1001, "hello")

    assert sync_mock.call_count == 3
    finalize_mock.assert_called_once_with(
        ANY,
        before={"a": "1"},
        after={"a": "1"},
        consumed_capture_ids=["cap_1"],
        review_prompt_active=True,
    )

@pytest.mark.asyncio
async def test_run_cli_chat_marks_native_session_when_assistant_codex_thread_exists(
    web_manager: MultiBotManager, temp_dir: Path
):
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
    session = get_session_for_alias(web_manager, "assistant1", 1001)
    session.codex_session_id = "thread-existing"
    session.managed_prompt_hash_seen = "hash-seen"
    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.is_compaction_prompt_active", return_value=False), \
         patch(
             "bot.web.api_service.sync_managed_prompt_files",
             return_value=ManagedPromptSyncResult(True, True, "hash-current"),
         ) as sync_mock, \
         patch(
             "bot.web.api_service.compile_assistant_prompt",
             return_value=AssistantPromptPayload(
                 prompt_text="resume payload",
                 managed_prompt_hash_seen="hash-updated",
             ),
         ) as compiler, \
         patch("bot.web.api_service.record_assistant_capture", return_value={"id": "cap_1"}), \
         patch("bot.web.api_service.refresh_compaction_state"), \
         patch("bot.web.api_service.list_pending_capture_ids", return_value=["cap_1"]), \
         patch("bot.web.api_service.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]), \
         patch("bot.web.api_service.finalize_compaction", return_value="none"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_codex_process", new_callable=AsyncMock, return_value=("ok", "thread-existing", 0)):
        await run_cli_chat(web_manager, "assistant1", 1001, "hello")

    compiler.assert_called_once_with(
        "hello",
        managed_prompt_hash="hash-current",
        seen_managed_prompt_hash="hash-seen",
    )
    assert sync_mock.call_count == 2
    assert session.managed_prompt_hash_seen == "hash-updated"

@pytest.mark.asyncio
async def test_stream_cli_chat_uses_managed_prompt_hash_for_assistant(web_manager: MultiBotManager, temp_dir: Path):
    workdir = temp_dir / "assistant-root-stream"
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
    session = get_session_for_alias(web_manager, "assistant1", 1001)
    session.codex_session_id = "thread-existing"
    session.managed_prompt_hash_seen = "hash-old"

    fake_stdout = MagicMock()
    fake_stdout.readline.return_value = ""
    fake_stdout.read.return_value = ""

    fake_process = MagicMock()
    fake_process.stdout = fake_stdout
    fake_process.poll.return_value = 0
    fake_process.wait.return_value = 0

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.is_compaction_prompt_active", return_value=False), \
         patch(
             "bot.web.api_service.sync_managed_prompt_files",
             return_value=ManagedPromptSyncResult(True, True, "hash-new"),
         ) as sync_mock, \
         patch(
             "bot.web.api_service.compile_assistant_prompt",
             return_value=AssistantPromptPayload(
                 prompt_text="继续。",
                 managed_prompt_hash_seen="hash-new",
             ),
         ) as compiler, \
         patch("bot.web.api_service.record_assistant_capture", return_value={"id": "cap_1"}), \
         patch("bot.web.api_service.refresh_compaction_state"), \
         patch("bot.web.api_service.list_pending_capture_ids", return_value=["cap_1"]), \
         patch("bot.web.api_service.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]), \
         patch("bot.web.api_service.finalize_compaction", return_value="none") as finalize_mock, \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)) as build_mock, \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "assistant1", 1001, "继续。")]
        for _ in range(20):
            if sync_mock.call_count == 2 and finalize_mock.call_count == 1:
                break
            await asyncio.sleep(0.05)

    compiler.assert_called_once_with(
        "继续。",
        managed_prompt_hash="hash-new",
        seen_managed_prompt_hash="hash-old",
    )
    assert sync_mock.call_count == 2
    finalize_mock.assert_called_once_with(
        ANY,
        before={"a": "1"},
        after={"a": "1"},
        consumed_capture_ids=["cap_1"],
        review_prompt_active=False,
    )
    assert build_mock.call_args.kwargs["user_text"] == "继续。"
    assert any(event["type"] == "done" for event in events)
    assert session.managed_prompt_hash_seen == "hash-new"

@pytest.mark.asyncio
async def test_stream_cli_chat_emits_done_before_assistant_finalize_completes(
    web_manager: MultiBotManager, temp_dir: Path
):
    workdir = temp_dir / "assistant-root-stream-finalize"
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
    session = get_session_for_alias(web_manager, "assistant1", 1001)

    fake_stdout = MagicMock()
    fake_stdout.readline.return_value = ""
    fake_stdout.read.return_value = ""

    fake_process = MagicMock()
    fake_process.stdout = fake_stdout
    fake_process.poll.return_value = 0
    fake_process.wait.return_value = 0

    finalize_started = threading.Event()
    finalize_release = threading.Event()

    def delayed_finalize(*args, **kwargs):
        finalize_started.set()
        finalize_release.wait(timeout=2.0)

    async def collect_events():
        return [event async for event in _stream_cli_chat(web_manager, "assistant1", 1001, "继续。")]

    try:
        with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
             patch("bot.web.api_service.is_compaction_prompt_active", return_value=False), \
             patch(
                 "bot.web.api_service.sync_managed_prompt_files",
                 return_value=ManagedPromptSyncResult(False, False, "hash-new"),
             ), \
             patch(
                 "bot.web.api_service.compile_assistant_prompt",
                 return_value=AssistantPromptPayload(
                     prompt_text="继续。",
                     managed_prompt_hash_seen="hash-new",
                 ),
             ), \
             patch("bot.web.api_service._finalize_assistant_chat_turn", side_effect=delayed_finalize) as finalize_mock, \
             patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
             patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
            events = await asyncio.wait_for(collect_events(), timeout=0.5)
            assert await asyncio.to_thread(finalize_started.wait, 0.5)
            assert finalize_mock.call_count == 1

        done_event = next(event for event in events if event["type"] == "done")
        assert done_event["session"]["is_processing"] is False
        assert session.is_processing is False
    finally:
        finalize_release.set()
        await asyncio.sleep(0.05)

@pytest.mark.asyncio
async def test_stream_cli_chat_assistant_claude_emits_trace_without_include_trace_error(
    web_manager: MultiBotManager, temp_dir: Path
):
    workdir = temp_dir / "assistant-root-claude-stream"
    workdir.mkdir()
    web_manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="claude",
        cli_path="claude",
        working_dir=str(workdir),
        enabled=True,
        bot_mode="assistant",
    )

    class FakeStdout:
        def __init__(self, owner):
            self._owner = owner
            self._lines = [
                '{"type":"assistant","session_id":"session-1","message":{"content":[{"type":"text","text":"我先检查最近变更。"},{"type":"tool_use","id":"toolu_1","name":"Bash","input":{"command":"git status --short"}}]}}\n',
                '{"type":"result","subtype":"success","session_id":"session-1","result":"最近有 1 个文件修改。"}\n',
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

    with patch("bot.web.api_service.resolve_cli_executable", return_value="claude"), \
         patch("bot.web.api_service.is_compaction_prompt_active", return_value=False), \
         patch(
             "bot.web.api_service.sync_managed_prompt_files",
             return_value=ManagedPromptSyncResult(False, False, "hash-current"),
         ), \
         patch(
             "bot.web.api_service.compile_assistant_prompt",
             return_value=AssistantPromptPayload(
                 prompt_text="assistant payload",
                 managed_prompt_hash_seen="hash-current",
             ),
         ), \
         patch("bot.web.api_service.record_assistant_capture", return_value={"id": "cap_1"}), \
         patch("bot.web.api_service.refresh_compaction_state"), \
         patch("bot.web.api_service.list_pending_capture_ids", return_value=["cap_1"]), \
         patch("bot.web.api_service.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]), \
         patch("bot.web.api_service.finalize_compaction", return_value="none"), \
         patch("bot.web.api_service.build_claude_done_session", return_value=MagicMock(enabled=False, prompt_text="assistant payload")), \
         patch("bot.web.api_service.build_cli_command", return_value=(["claude"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "assistant1", 1001, "查看最近变更")]

    trace_events = [event for event in events if event["type"] == "trace"]
    done_event = next(event for event in events if event["type"] == "done")
    session = get_session_for_alias(web_manager, "assistant1", 1001)

    assert [event["event"]["kind"] for event in trace_events] == ["commentary", "tool_call"]
    assert trace_events[1]["event"]["summary"] == "git status --short"
    assert done_event["message"]["role"] == "assistant"
    assert done_event["message"]["content"] == "最近有 1 个文件修改。"
    assert session.claude_session_initialized is True
    assert session.managed_prompt_hash_seen == "hash-current"

@pytest.mark.asyncio
async def test_run_chat_requires_assistant_runtime_for_assistant_mode(
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

    with pytest.raises(WebApiError) as exc_info:
        await run_chat(web_manager, "assistant1", 1001, "hello")

    assert exc_info.value.status == 503
    assert exc_info.value.code == "assistant_runtime_unavailable"

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
    assert request.user_id == 1001
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

@pytest.mark.asyncio
async def test_admin_assistant_upgrade_apply_route(
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

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch(
                "bot.web.server.apply_assistant_upgrade",
                new_callable=AsyncMock,
                return_value={"id": "pr_1", "status": "applied"},
            ) as apply_mock:
                resp = await client.post("/api/admin/bots/assistant1/assistant/upgrades/pr_1/apply")

            assert resp.status == 200
            apply_mock.assert_awaited_once()

@pytest.mark.asyncio
async def test_stream_cli_chat_done_event_includes_elapsed_seconds(web_manager: MultiBotManager):
    fake_stdout = MagicMock()
    fake_stdout.readline.return_value = ""
    fake_stdout.read.return_value = ""

    fake_process = MagicMock()
    fake_process.stdout = fake_stdout
    fake_process.poll.return_value = 0
    fake_process.wait.return_value = 0

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "main", 1001, "hello")]

    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["output"] == "（无输出）" or isinstance(done_event["output"], str)
    assert isinstance(done_event["elapsed_seconds"], int)
    assert done_event["elapsed_seconds"] >= 0

@pytest.mark.asyncio
async def test_stream_cli_chat_passes_hidden_process_kwargs_to_popen(web_manager: MultiBotManager):
    fake_stdout = MagicMock()
    fake_stdout.readline.return_value = ""
    fake_stdout.read.return_value = ""

    fake_process = MagicMock()
    fake_process.stdout = fake_stdout
    fake_process.poll.return_value = 0
    fake_process.wait.return_value = 0

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.build_hidden_process_kwargs", return_value={"creationflags": 456}) as hidden_mock, \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process) as popen_mock:
        [event async for event in _stream_cli_chat(web_manager, "main", 1001, "hello")]

    hidden_mock.assert_called_once_with()
    assert popen_mock.call_args.kwargs["creationflags"] == 456

@pytest.mark.asyncio
async def test_stream_cli_chat_does_not_force_terminate_on_elapsed_time(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(api_service, "CLI_EXEC_TIMEOUT", 0, raising=False)
    web_manager.main_profile.cli_type = "codex"

    class FakeStdout:
        def __init__(self, owner):
            self._owner = owner
            self._lines = ['{"type":"item.completed","item":{"type":"assistant_message","text":"完成回复"}}\n']

        def readline(self):
            time.sleep(0.02)
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

    fake_process = FakeProcess()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "main", 1001, "hello")]

    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["output"] == "完成回复"
    fake_process.terminate.assert_not_called()
    fake_process.kill.assert_not_called()

def test_get_history_reads_from_local_store_not_overlay_or_legacy_history(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    web_manager.main_profile.cli_type = "codex"
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    session.session_epoch = 1
    session.history = [{"role": "assistant", "content": "legacy"}]
    session.web_turn_overlays = [{"summary_text": "overlay"}]
    service = ChatHistoryService(ChatStore(tmp_path))
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text="列出当前目录",
        native_provider="codex",
    )
    service.complete_turn(handle, content="目录已读取完成。", completion_state="completed")

    data = get_history(web_manager, "main", 1001, limit=10)

    assert [item["content"] for item in data["items"]] == ["列出当前目录", "目录已读取完成。"]
    assert all(item["content"] != "legacy" for item in data["items"])
    assert all(item["content"] != "overlay" for item in data["items"])

def test_get_history_trace_returns_full_trace_for_assistant_message(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    web_manager.main_profile.cli_type = "codex"
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    session.session_epoch = 1
    store = ChatStore(tmp_path)
    service = ChatHistoryService(store)
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text="列出当前目录",
        native_provider="codex",
    )
    store.append_trace_event(handle.turn_id, kind="commentary", summary="我先检查目录结构。")
    store.append_trace_event(handle.turn_id, kind="tool_call", summary="Get-ChildItem -Force")
    store.append_trace_event(handle.turn_id, kind="tool_result", summary="bot\nfront")
    service.complete_turn(handle, content="目录已读取完成。", completion_state="completed")

    history = get_history(web_manager, "main", 1001, limit=10)
    assistant_message_id = history["items"][1]["id"]

    data = get_history_trace(web_manager, "main", 1001, assistant_message_id)

    assert data["message_id"] == assistant_message_id
    assert data["trace_count"] == 3
    assert data["tool_call_count"] == 1
    assert data["process_count"] == 1
    assert [item["kind"] for item in data["trace"]] == [
        "commentary",
        "tool_call",
        "tool_result",
    ]

def test_kill_user_process_marks_stop_requested_and_preserves_running_reply(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    process = MagicMock()
    process.poll.return_value = None
    process.terminate = MagicMock()

    with session._lock:
        session.process = process
        session.is_processing = True
        session.stop_requested = False
        session.running_user_text = "继续"
        session.running_preview_text = "处理中预览"
        session.running_started_at = "2026-04-14T10:00:00"
        session.running_updated_at = "2026-04-14T10:00:03"

    result = kill_user_process(web_manager, "main", 1001)

    assert result["killed"] is True
    assert session.stop_requested is True
    assert session.is_processing is True
    assert session.running_preview_text == "处理中预览"
    process.terminate.assert_called_once()

def test_codex_status_event_skips_json_meta_preview():
    event = _build_stream_status_event(
        cli_type="codex",
        elapsed_seconds=3,
        raw_output='{"type":"thread.started","thread_id":"abc"}\n{"type":"turn.started"}\n',
    )

    assert event == {
        "type": "status",
        "elapsed_seconds": 3,
    }

def test_codex_status_event_uses_latest_message_preview_without_duplication():
    event = _build_stream_status_event(
        cli_type="codex",
        elapsed_seconds=3,
        raw_output=(
            '{"type":"item.delta","item":{"type":"assistant_message","delta":"我先检查目录结构。"}}\n'
            '{"type":"item.completed","item":{"type":"assistant_message","text":"我先检查目录结构。"}}\n'
            '{"type":"item.completed","item":{"type":"assistant_message","text":"目录已读取完成。"}}\n'
        ),
    )

    assert event == {
        "type": "status",
        "elapsed_seconds": 3,
        "preview_text": "目录已读取完成。",
    }

def test_claude_status_event_extracts_text_delta_preview():
    event = _build_stream_status_event(
        cli_type="claude",
        elapsed_seconds=2,
        raw_output='{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"你好"}}}\n',
    )

    assert event == {
        "type": "status",
        "elapsed_seconds": 2,
        "preview_text": "你好",
    }

@pytest.mark.asyncio
async def test_stream_cli_chat_claude_done_detector_strips_preview_and_done_output(web_manager: MultiBotManager):
    from bot.claude_done import build_claude_done_session

    web_manager.main_profile.cli_type = "claude"

    class FakeStdout:
        def __init__(self):
            self._lines = [
                '{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"你好\\n__TCB_DONE_abc123__"}}}\n',
                '{"type":"result","subtype":"success","session_id":"sess-1","result":"你好\\n__TCB_DONE_abc123__"}\n',
            ]

        def readline(self):
            return self._lines.pop(0) if self._lines else ""

        def read(self):
            return ""

    class FakeProcess:
        def __init__(self):
            self.stdout = FakeStdout()
            self.stdin = None
            self.returncode = None
            self.terminate = MagicMock(side_effect=self._terminate)

        def _terminate(self):
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    fake_process = FakeProcess()
    done_session = build_claude_done_session(
        "hello",
        cli_type="claude",
        enabled=True,
        quiet_seconds=0.0,
        sentinel_mode="nonce",
        nonce="abc123",
    )

    with patch("bot.web.api_service.resolve_cli_executable", return_value="claude"), \
         patch("bot.web.api_service.build_claude_done_session", return_value=done_session), \
         patch("bot.web.api_service.build_cli_command", return_value=(["claude"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "main", 1001, "hello")]

    status_events = [event for event in events if event["type"] == "status" and event.get("preview_text")]
    done_event = next(event for event in events if event["type"] == "done")

    assert status_events
    assert status_events[-1]["preview_text"] == "你好"
    assert done_event["output"] == "你好"
    assert done_event["returncode"] == 0
    fake_process.terminate.assert_called_once()

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

@pytest.mark.asyncio
async def test_stream_cli_chat_persists_one_assistant_row_for_status_trace_and_done(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    web_manager.main_profile.cli_type = "codex"
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    session.session_epoch = 1

    class FakeStdout:
        def __init__(self):
            self._lines = [
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.completed","item":{"type":"assistant_message","text":"我先检查目录结构。"}}\n',
                '{"type":"item.completed","item":{"type":"function_call","name":"shell_command","arguments":"{\\"command\\":\\"Get-ChildItem -Force\\"}","call_id":"call_1"}}\n',
                '{"type":"item.completed","item":{"type":"assistant_message","text":"目录已读取完成。"}}\n',
            ]

        def readline(self):
            return self._lines.pop(0) if self._lines else ""

        def read(self):
            return ""

    fake_process = MagicMock()
    fake_process.stdout = FakeStdout()
    fake_process.poll.side_effect = [None, None, None, 0, 0]
    fake_process.wait.return_value = 0

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "main", 1001, "列出当前目录")]

    done_event = next(event for event in events if event["type"] == "done")
    history = get_history(web_manager, "main", 1001, limit=10)
    assistant_items = [item for item in history["items"] if item["role"] == "assistant"]

    assert len(assistant_items) == 1
    assert assistant_items[0]["id"] == done_event["message"]["id"]
    assert assistant_items[0]["content"] == "目录已读取完成。"
    assert assistant_items[0]["meta"]["tool_call_count"] == 1

@pytest.mark.asyncio
async def test_stream_cli_chat_persists_trace_counts_from_codex_response_items(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    web_manager.main_profile.cli_type = "codex"
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    session.session_epoch = 1

    class FakeStdout:
        def __init__(self):
            self._lines = [
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"response_item","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"我先检查目录结构。"}]}}\n',
                '{"type":"response_item","item":{"type":"function_call","name":"shell_command","call_id":"call_1","arguments":"{\\"command\\":\\"Get-ChildItem -Force\\"}"}}\n',
                '{"type":"response_item","item":{"type":"function_call_output","call_id":"call_1","output":"README.md\\nbot\\nfront"}}\n',
                '{"type":"event_msg","payload":{"type":"agent_message","message":"目录已读取完成。"}}\n',
            ]

        def readline(self):
            return self._lines.pop(0) if self._lines else ""

        def read(self):
            return ""

    fake_process = MagicMock()
    fake_process.stdout = FakeStdout()
    fake_process.poll.side_effect = [None, None, None, None, 0, 0]
    fake_process.wait.return_value = 0

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "main", 1001, "列出当前目录")]

    done_event = next(event for event in events if event["type"] == "done")
    history = get_history(web_manager, "main", 1001, limit=10)
    assistant_items = [item for item in history["items"] if item["role"] == "assistant"]

    assert len(assistant_items) == 1
    assert assistant_items[0]["id"] == done_event["message"]["id"]
    assert assistant_items[0]["content"] == "目录已读取完成。"
    assert assistant_items[0]["meta"]["trace_count"] == 4
    assert assistant_items[0]["meta"]["tool_call_count"] == 1

def test_kill_user_process_preserves_local_streaming_row(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    web_manager.main_profile.working_dir = str(tmp_path)
    session = get_session_for_alias(web_manager, "main", 1001)
    session.working_dir = str(tmp_path)
    session.session_epoch = 1
    service = ChatHistoryService(ChatStore(tmp_path))
    handle = service.start_turn(
        profile=web_manager.main_profile,
        session=session,
        user_text="继续",
        native_provider="codex",
    )
    service.replace_assistant_preview(handle, "处理中预览")

    process = MagicMock()
    process.poll.return_value = None
    process.terminate = MagicMock()
    with session._lock:
        session.process = process
        session.is_processing = True
        session.stop_requested = False

    result = kill_user_process(web_manager, "main", 1001)
    history = get_history(web_manager, "main", 1001, limit=10)

    assert result["killed"] is True
    assert history["items"][-1]["content"] == "处理中预览"
    assert history["items"][-1]["state"] == "streaming"

@pytest.mark.asyncio
async def test_assistant_turn_persists_only_visible_user_text(
    web_manager: MultiBotManager,
    tmp_path: Path,
):
    web_manager.managed_profiles["assistant1"] = BotProfile(
        alias="assistant1",
        token="",
        cli_type="codex",
        cli_path="codex",
        working_dir=str(tmp_path),
        enabled=True,
        bot_mode="assistant",
    )

    fake_process = MagicMock()

    fake_home = MagicMock()
    fake_home.root = tmp_path / ".assistant"

    with patch("bot.web.api_service.resolve_cli_executable", return_value="codex"), \
         patch("bot.web.api_service._prepare_assistant_prompt", return_value=(fake_home, {}, "HIDDEN PREAMBLE\n\n查看最近变更", False)), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_codex_process", new_callable=AsyncMock, return_value=("查看完成", "thread-1", 0)):
        await run_cli_chat(web_manager, "assistant1", 1001, "查看最近变更")

    history = get_history(web_manager, "assistant1", 1001, limit=10)
    assert history["items"][0]["content"] == "查看最近变更"
    assert all("HIDDEN PREAMBLE" not in item["content"] for item in history["items"])

@pytest.mark.asyncio
async def test_post_chat_stream_continues_processing_after_client_disconnect(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)
    request = MagicMock()
    consumed: list[str] = []

    async def fake_stream_chat(manager, alias, user_id, message):
        for event in [
            {"type": "meta", "alias": alias},
            {"type": "status", "elapsed_seconds": 1},
            {"type": "done", "output": "ok"},
        ]:
            consumed.append(event["type"])
            yield event

    class FakeStreamResponse:
        def __init__(self, *args, **kwargs):
            self.write_calls = 0
            self.write_eof_called = False

        async def prepare(self, req):
            return self

        async def write(self, data):
            self.write_calls += 1
            if self.write_calls == 2:
                raise ClientConnectionResetError("Cannot write to closing transport")

        async def write_eof(self):
            self.write_eof_called = True

    response_holder: dict[str, FakeStreamResponse] = {}

    def fake_stream_response(*args, **kwargs):
        response = FakeStreamResponse(*args, **kwargs)
        response_holder["response"] = response
        return response

    with patch.object(server, "_with_auth", AsyncMock(return_value=AuthContext(user_id=1001, token_used=False))), \
         patch.object(server, "_manager_alias", return_value="main"), \
         patch.object(server, "_parse_json", AsyncMock(return_value={"message": "hi"})), \
         patch("bot.web.server.stream_chat", fake_stream_chat), \
         patch("bot.web.server.web.StreamResponse", side_effect=fake_stream_response):
        response = await server.post_chat_stream(request)

    assert response is response_holder["response"]
    assert consumed == ["meta", "status", "done"]
    assert response_holder["response"].write_eof_called is False

@pytest.mark.asyncio
async def test_debug_profile_route_returns_service_payload(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    server = WebApiServer(web_manager)
    fake_profile = {"config_name": "(gdb) Remote Debug", "remote_host": "192.168.1.29"}
    server._debug_service = MagicMock()
    server._debug_service.get_profile = AsyncMock(return_value=fake_profile)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots/main/debug/profile")
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"] == fake_profile
    server._debug_service.get_profile.assert_awaited_once_with("main", 1001)

@pytest.mark.asyncio
async def test_debug_state_route_returns_service_payload(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    server = WebApiServer(web_manager)
    fake_state = {
        "phase": "paused",
        "message": "命中断点",
        "breakpoints": [],
        "frames": [],
        "current_frame_id": "frame-0",
        "scopes": [{"name": "Locals", "variablesReference": "frame-0:locals"}],
        "variables": {},
    }
    server._debug_service = MagicMock()
    server._debug_service.get_state = AsyncMock(return_value=fake_state)

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            resp = await client.get("/api/bots/main/debug/state")
            assert resp.status == 200
            payload = await resp.json()

    assert payload["data"] == fake_state
    server._debug_service.get_state.assert_awaited_once_with("main", 1001)

@pytest.mark.asyncio
async def test_debug_websocket_forwards_service_events_and_client_messages(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "secret")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    server = WebApiServer(web_manager)
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    server._debug_service = MagicMock()
    server._debug_service.subscribe = AsyncMock(return_value=queue)
    server._debug_service.get_state = AsyncMock(
        return_value={
            "phase": "preparing",
            "message": "准备调试环境",
            "breakpoints": [],
            "frames": [],
            "current_frame_id": "",
            "scopes": [],
            "variables": {},
        }
    )

    async def fake_handle(alias: str, user_id: int, payload: dict[str, object]) -> None:
        assert alias == "main"
        assert user_id == 1001
        assert payload == {"type": "launch", "payload": {"remoteHost": "192.168.1.29", "remotePort": 1234}}
        queue.put_nowait({"type": "prepareLog", "payload": {"line": "debug.ps1 ready"}})

    server._debug_service.handle_ws_message = AsyncMock(side_effect=fake_handle)
    server._debug_service.unsubscribe = AsyncMock()

    app = server._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            ws = await client.ws_connect("/debug/ws?token=secret&alias=main")
            first = await ws.receive_json()
            await ws.send_json({"type": "launch", "payload": {"remoteHost": "192.168.1.29", "remotePort": 1234}})
            second = await ws.receive_json()
            await ws.close()
            for _ in range(20):
                if server._debug_service.unsubscribe.await_count:
                    break
                await asyncio.sleep(0.01)

    assert first["type"] == "state"
    assert first["payload"]["phase"] == "preparing"
    assert second == {"type": "prepareLog", "payload": {"line": "debug.ps1 ready"}}
    server._debug_service.subscribe.assert_awaited_once_with("main", 1001)
    server._debug_service.handle_ws_message.assert_awaited_once()

@pytest.mark.asyncio
async def test_web_server_stop_closes_debug_resources(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)
    runner = MagicMock()
    runner.cleanup = AsyncMock()
    server._runner = runner
    server._site = object()
    server._tunnel_service = MagicMock()
    server._tunnel_service.stop = AsyncMock()
    server._debug_service = MagicMock()
    server._debug_service.shutdown = AsyncMock()

    debug_ws = MagicMock()
    debug_ws.close = AsyncMock()
    server._debug_sockets.add(debug_ws)
    debug_task = asyncio.create_task(asyncio.sleep(60))
    server._debug_tasks.add(debug_task)

    await server.stop()

    assert debug_task.cancelled() is True
    debug_ws.close.assert_awaited_once()
    server._debug_service.shutdown.assert_awaited_once()
    runner.cleanup.assert_awaited_once()
    server._tunnel_service.stop.assert_awaited_once()
