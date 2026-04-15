"""Web API 相关测试。"""

from __future__ import annotations

import asyncio
import json
import struct
import subprocess
import time
import zlib
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from aiohttp.client_exceptions import ClientConnectionResetError, WSServerHandshakeError

from bot.assistant_context import AssistantPromptPayload
from bot.assistant_docs import ManagedPromptSyncResult
from bot.assistant_home import bootstrap_assistant_home
from bot.assistant_state import save_assistant_runtime_state
from bot.manager import MultiBotManager
from bot.models import BotProfile, UserSession
from bot.session_store import save_session
from bot.web.server import WebApiServer
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
    read_file_content,
    run_chat,
    run_cli_chat,
    save_uploaded_file,
)
from bot.app_settings import get_git_proxy_settings, update_git_proxy_port
from bot.web import api_service
from bot.web.git_service import (
    commit_git_changes,
    get_git_diff,
    get_git_overview,
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


def test_web_api_service_no_longer_imports_telegram_shell_or_admin_handlers():
    source = Path("bot/web/api_service.py").read_text(encoding="utf-8")

    assert ("from bot." + "handlers.admin import") not in source
    assert ("from bot." + "handlers.shell import") not in source
    assert ("should_reset_" + "ki" + "mi_session") not in source
    assert ("ki" + "mi_session_id") not in source
    assert ('cli_type == "' + "ki" + "mi" + '"') not in source


def test_web_server_module_no_longer_imports_telegram_runtime():
    source = Path("bot/web/server.py").read_text(encoding="utf-8")

    assert ("from " + "telegram") not in source
    assert "Bot(" not in source
    assert "HTTPXRequest" not in source


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


def test_overview_and_directory_listing(web_manager: MultiBotManager, temp_dir: Path):
    subdir = temp_dir / "workspace"
    subdir.mkdir()
    (subdir / "hello.txt").write_text("hello", encoding="utf-8")

    change_working_directory(web_manager, "main", 1001, str(subdir))
    overview = get_overview(web_manager, "main", 1001)
    assert overview["session"]["working_dir"] == str(subdir)

    listing = get_directory_listing(web_manager, "main", 1001)
    assert any(item["name"] == "hello.txt" for item in listing["entries"])


def test_overview_includes_running_reply_snapshot(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True
        session.running_preview_text = "处理中预览"
        session.running_started_at = "2026-04-09T10:40:00"
        session.running_updated_at = "2026-04-09T10:40:05"

    overview = get_overview(web_manager, "main", 1001)

    assert overview["session"]["running_reply"] == {
        "user_text": "",
        "preview_text": "处理中预览",
        "started_at": "2026-04-09T10:40:00",
        "updated_at": "2026-04-09T10:40:05",
    }


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
    web_manager.main_profile.avatar_name = "bot-default.png"
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
    assert items[0]["avatar_name"] == "bot-default.png"
    assert next(item for item in items if item["alias"] == "team2")["avatar_name"] == "claude-blue.png"


def test_change_working_directory_clears_session_ids(web_manager: MultiBotManager, temp_dir: Path):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.codex_session_id = "thread-old"
    session.claude_session_id = "claude-old"
    session.claude_session_initialized = True

    subdir = temp_dir / "workspace"
    subdir.mkdir()

    result = change_working_directory(web_manager, "main", 1001, str(subdir))

    assert result["working_dir"] == str(subdir)
    assert session.working_dir == str(subdir)
    assert session.codex_session_id is None
    assert session.claude_session_id is None
    assert session.claude_session_initialized is False


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


def test_get_session_for_alias_restores_assistant_overlay_but_not_private_history(
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

    assert session.codex_session_id == "assistant-thread"
    assert session.browse_dir == str(browse_dir)
    assert session.history == []
    assert getattr(session, "web_turn_overlays", []) == [{"provider": "codex", "summary_text": "synthetic"}]
    assert session.message_count == 3


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


def test_create_directory_creates_folder_in_current_browser_dir(web_manager: MultiBotManager, temp_dir: Path):
    workspace = temp_dir / "workspace"
    workspace.mkdir()
    change_working_directory(web_manager, "main", 1001, str(workspace))

    result = api_service.create_directory(web_manager, "main", 1001, "docs")

    assert result["name"] == "docs"
    assert result["created_path"] == str(workspace / "docs")
    assert (workspace / "docs").is_dir()


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


def _init_git_repo(repo_dir: Path):
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Web Bot Test"], cwd=repo_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "web-bot@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)


def test_git_overview_returns_repo_state(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    tracked = repo_dir / "tracked.txt"
    tracked.write_text("line 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)

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


def test_init_git_repository_creates_repo_when_missing(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "new-repo"
    repo_dir.mkdir()

    web_manager.main_profile.working_dir = str(repo_dir)
    result = init_git_repository(web_manager, "main", 1001)

    assert result["repo_found"] is True
    assert result["repo_path"] == str(repo_dir)
    assert (repo_dir / ".git").exists()


def test_stage_commit_and_diff_git_changes(web_manager: MultiBotManager, temp_dir: Path):
    repo_dir = temp_dir / "repo"
    repo_dir.mkdir()
    _init_git_repo(repo_dir)

    tracked = repo_dir / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)

    tracked.write_text("before\nafter\n", encoding="utf-8")
    web_manager.main_profile.working_dir = str(repo_dir)

    staged = stage_git_paths(web_manager, "main", 1001, ["tracked.txt"])
    assert any(item["path"] == "tracked.txt" and item["staged"] for item in staged["changed_files"])

    diff = get_git_diff(web_manager, "main", 1001, "tracked.txt", staged=True)
    assert "+after" in diff["diff"]

    committed = commit_git_changes(web_manager, "main", 1001, "feat: update tracked")
    assert committed["recent_commits"][0]["subject"] == "feat: update tracked"


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
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
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
    assert calls[0][:5] == ["git", "-c", "http.proxy=", "-c", "https.proxy="]
    assert calls[1][:5] == ["git", "-c", "http.proxy=", "-c", "https.proxy="]


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
    assert calls[0][:5] == [
        "git",
        "-c",
        "http.proxy=http://127.0.0.1:7897",
        "-c",
        "https.proxy=http://127.0.0.1:7897",
    ]
    assert calls[1][:5] == [
        "git",
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
async def test_admin_run_script_stream_returns_sse_events(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    async def fake_stream_system_script(script_name: str):
        yield {"type": "log", "text": "npm run build"}
        yield {"type": "log", "text": "vite build finished"}
        yield {"type": "done", "script_name": script_name, "success": True, "output": "Web 前端构建完成"}

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.web.server.stream_system_script", fake_stream_system_script):
                resp = await client.post("/api/admin/scripts/run/stream", json={"script_name": "build_web_frontend"})
                assert resp.status == 200
                body = await resp.text()
                assert "event: log" in body
                assert "npm run build" in body
                assert "event: done" in body
                assert "Web 前端构建完成" in body


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
async def test_admin_add_bot_route_no_longer_requires_token_field(
    web_manager: MultiBotManager,
    monkeypatch: pytest.MonkeyPatch,
    temp_dir: Path,
):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [])

    app = WebApiServer(web_manager)._build_app()
    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            with patch("bot.manager.resolve_cli_executable", return_value="codex"), \
                 patch.object(web_manager, "_start_profile", AsyncMock(return_value=None)) as start_profile:
                resp = await client.post(
                    "/api/admin/bots",
                    json={
                        "alias": "web_only",
                        "bot_mode": "cli",
                        "cli_type": "codex",
                        "cli_path": "codex",
                        "working_dir": str(temp_dir),
                    },
                )
                assert resp.status == 200
                payload = await resp.json()

    assert payload["data"]["bot"]["alias"] == "web_only"
    assert web_manager.managed_profiles["web_only"].token == ""
    start_profile.assert_awaited_once()


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
    (avatar_dir / "bot-default.png").write_bytes(_png_bytes(64, 64))
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
        {"name": "bot-default.png", "url": "/assets/avatars/bot-default.png"},
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
        avatar_name="bot-default.png",
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
        avatar_name="bot-default.png",
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
async def test_web_server_start_schedules_auto_update_check_when_enabled(web_manager):
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
async def test_notify_tunnel_public_url_returns_false_when_clipboard_copy_fails(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)
    server._copy_text_to_clipboard = MagicMock(return_value=False)

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
async def test_health_payload_omits_telegram_status(web_manager: MultiBotManager):
    server = WebApiServer(web_manager)

    response = await server.health(MagicMock())
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["service"] == "telegram-cli-bridge-web"
    assert "telegram_running" not in payload


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
             ("Error: Session ID not found", 1, False),
             ("OK", 0, False),
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
             return_value=("完成回复", "thread-1", 0, False),
         ):
        data = await run_cli_chat(web_manager, "main", 1001, "hello")

    assert data["output"] == "完成回复"
    assert isinstance(data["elapsed_seconds"], int)
    assert data["elapsed_seconds"] >= 0
    assert data["message"]["role"] == "assistant"
    assert data["message"]["content"] == "完成回复"


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
         patch("bot.web.api_service.finalize_compaction", return_value=False) as finalize_mock, \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)) as build_mock, \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_codex_process", new_callable=AsyncMock, return_value=("ok", "thread-1", 0, False)):
        await run_cli_chat(web_manager, "assistant1", 1001, "hello")

    compiler.assert_called_once_with(
        ANY,
        1001,
        "hello",
        has_native_session=False,
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
    )
    session = get_session_for_alias(web_manager, "assistant1", 1001)
    assert session.managed_prompt_hash_seen == "hash-updated"
    assert build_mock.call_args.kwargs["user_text"] == "hello from payload"


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
         patch("bot.web.api_service.finalize_compaction", return_value=False), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_codex_process", new_callable=AsyncMock, return_value=("ok", "thread-existing", 0, False)):
        await run_cli_chat(web_manager, "assistant1", 1001, "hello")

    compiler.assert_called_once_with(
        ANY,
        1001,
        "hello",
        has_native_session=True,
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
         patch(
             "bot.web.api_service.sync_managed_prompt_files",
             return_value=ManagedPromptSyncResult(True, True, "hash-new"),
         ) as sync_mock, \
         patch(
             "bot.web.api_service.compile_assistant_prompt",
             return_value=AssistantPromptPayload(
                 prompt_text="AGENTS.md 和 CLAUDE.md 已更新，请重新读取。\n\n继续。",
                 managed_prompt_hash_seen="hash-new",
             ),
         ) as compiler, \
         patch("bot.web.api_service.record_assistant_capture", return_value={"id": "cap_1"}), \
         patch("bot.web.api_service.refresh_compaction_state"), \
         patch("bot.web.api_service.list_pending_capture_ids", return_value=["cap_1"]), \
         patch("bot.web.api_service.snapshot_managed_surface", side_effect=[{"a": "1"}, {"a": "1"}]), \
         patch("bot.web.api_service.finalize_compaction", return_value=False), \
         patch("bot.web.api_service.build_cli_command", return_value=(["codex"], False)) as build_mock, \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "assistant1", 1001, "继续。")]

    compiler.assert_called_once_with(
        ANY,
        1001,
        "继续。",
        has_native_session=True,
        managed_prompt_hash="hash-new",
        seen_managed_prompt_hash="hash-old",
    )
    assert sync_mock.call_count == 2
    assert build_mock.call_args.kwargs["user_text"].startswith("AGENTS.md 和 CLAUDE.md 已更新")
    assert any(event["type"] == "done" for event in events)
    assert session.managed_prompt_hash_seen == "hash-new"


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
         patch("bot.web.api_service.finalize_compaction", return_value=False), \
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
async def test_run_chat_routes_assistant_mode_to_cli_chat(web_manager: MultiBotManager, temp_dir: Path):
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

    with patch(
        "bot.web.api_service.run_cli_chat",
        new_callable=AsyncMock,
        return_value={"output": "cli result", "elapsed_seconds": 1},
    ) as cli_mock:
        data = await run_chat(web_manager, "assistant1", 1001, "hello")

    cli_mock.assert_awaited_once_with(web_manager, "assistant1", 1001, "hello")
    assert data["output"] == "cli result"


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


def test_get_history_uses_overlay_backed_native_shape_instead_of_legacy_history(
    web_manager: MultiBotManager,
):
    web_manager.main_profile.cli_type = "codex"
    session = get_session_for_alias(web_manager, "main", 1001)
    session.history = [{"role": "assistant", "content": "legacy"}]
    session.web_turn_overlays = [
        {
            "provider": "codex",
            "native_session_id": "",
            "user_text": "列出当前目录",
            "started_at": "2026-04-14T10:00:00",
            "updated_at": "2026-04-14T10:00:05",
            "summary_text": "目录已读取完成。",
            "summary_kind": "final",
            "completion_state": "completed",
            "trace": [{"kind": "tool_call", "summary": "Get-ChildItem -Force"}],
            "locator_hint": {"cwd": str(session.working_dir)},
        }
    ]

    data = get_history(web_manager, "main", 1001, limit=10)

    assert [item["role"] for item in data["items"]] == ["user", "assistant"]
    assert data["items"][0]["content"] == "列出当前目录"
    assert data["items"][1]["content"] == "目录已读取完成。"
    assert all(item["content"] != "legacy" for item in data["items"])
    assert data["items"][1]["meta"]["trace_count"] == 1
    assert "trace" not in data["items"][1]["meta"]


def test_get_history_trace_returns_full_trace_for_assistant_message(
    web_manager: MultiBotManager,
):
    web_manager.main_profile.cli_type = "codex"
    session = get_session_for_alias(web_manager, "main", 1001)
    session.web_turn_overlays = [
        {
            "provider": "codex",
            "native_session_id": "",
            "user_text": "列出当前目录",
            "started_at": "2026-04-14T10:00:00",
            "updated_at": "2026-04-14T10:00:05",
            "summary_text": "目录已读取完成。",
            "summary_kind": "final",
            "completion_state": "completed",
            "trace": [
                {"kind": "commentary", "summary": "我先检查目录结构。"},
                {"kind": "tool_call", "summary": "Get-ChildItem -Force"},
                {"kind": "tool_result", "summary": "bot\nfront"},
            ],
            "locator_hint": {"cwd": str(session.working_dir)},
        }
    ]

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
