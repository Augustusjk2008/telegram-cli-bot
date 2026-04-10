"""Web API 相关测试。"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp.client_exceptions import ClientConnectionResetError, WSServerHandshakeError

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_service import (
    AuthContext,
    _stream_cli_chat,
    _build_stream_status_event,
    WebApiError,
    change_working_directory,
    get_directory_listing,
    get_session_for_alias,
    get_overview,
    list_bots,
    read_file_content,
    run_assistant_chat,
    run_cli_chat,
    save_uploaded_file,
)
from bot.web.git_service import (
    commit_git_changes,
    get_git_diff,
    get_git_overview,
    init_git_repository,
    stage_git_paths,
)
from bot.web.server import WebApiServer


@pytest.fixture
def web_manager(temp_dir: Path) -> MultiBotManager:
    storage_file = temp_dir / "managed_bots.json"
    storage_file.write_text(json.dumps({"bots": []}), encoding="utf-8")
    profile = BotProfile(
        alias="main",
        token="dummy-token",
        cli_type="kimi",
        cli_path="kimi",
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


def test_list_bots_includes_processing_state_for_current_user(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    with session._lock:
        session.is_processing = True

    items = list_bots(web_manager, 1001)

    assert items[0]["alias"] == "main"
    assert items[0]["is_processing"] is True


def test_change_working_directory_clears_session_ids(web_manager: MultiBotManager, temp_dir: Path):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.codex_session_id = "thread-old"
    session.kimi_session_id = "kimi-old"
    session.claude_session_id = "claude-old"
    session.claude_session_initialized = True

    subdir = temp_dir / "workspace"
    subdir.mkdir()

    result = change_working_directory(web_manager, "main", 1001, str(subdir))

    assert result["working_dir"] == str(subdir)
    assert session.working_dir == str(subdir)
    assert session.codex_session_id is None
    assert session.kimi_session_id is None
    assert session.claude_session_id is None
    assert session.claude_session_initialized is False


def test_save_and_read_file(web_manager: MultiBotManager, temp_dir: Path):
    result = save_uploaded_file(web_manager, "main", 1001, "notes.txt", b"line1\nline2\n")
    assert result["filename"] == "notes.txt"

    content = read_file_content(web_manager, "main", 1001, "notes.txt", mode="head", lines=1)
    assert content["content"] == "line1"


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
                ws = await client.ws_connect("/terminal/ws?token=secret")
                await ws.send_json({"shell": "powershell", "cwd": str(temp_dir)})
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
                assert started["shell_type"] == "powershell"
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
async def test_admin_tunnel_restart_notifies_main_bot_public_url(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_DEFAULT_USER_ID", 1001)
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [1001])

    fake_main_bot = MagicMock()
    fake_main_bot.send_message = AsyncMock()
    web_manager.applications["main"] = MagicMock(bot=fake_main_bot)

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

    fake_main_bot.send_message.assert_awaited_once()
    sent_text = fake_main_bot.send_message.await_args.kwargs["text"]
    assert "fresh.trycloudflare.com" in sent_text
    server._copy_text_to_clipboard.assert_called_once_with("https://fresh.trycloudflare.com")


@pytest.mark.asyncio
async def test_notify_tunnel_public_url_still_copies_when_telegram_send_fails(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [1001])

    fake_main_bot = MagicMock()
    fake_main_bot.send_message = AsyncMock(side_effect=RuntimeError("network down"))
    web_manager.applications["main"] = MagicMock(bot=fake_main_bot)

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

    assert result is False
    fake_main_bot.send_message.assert_awaited_once()
    server._copy_text_to_clipboard.assert_called_once_with("https://failed.trycloudflare.com")


@pytest.mark.asyncio
async def test_web_server_start_notifies_main_bot_public_url_on_autostart(web_manager: MultiBotManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bot.web.server.ALLOWED_USER_IDS", [1001])

    fake_main_bot = MagicMock()
    fake_main_bot.send_message = AsyncMock()
    web_manager.applications["main"] = MagicMock(bot=fake_main_bot)

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

    fake_main_bot.send_message.assert_awaited_once()
    sent_text = fake_main_bot.send_message.await_args.kwargs["text"]
    assert "startup.trycloudflare.com" in sent_text
    server._copy_text_to_clipboard.assert_called_once_with("https://startup.trycloudflare.com")


def test_read_missing_file_raises(web_manager: MultiBotManager):
    with pytest.raises(WebApiError) as exc_info:
        read_file_content(web_manager, "main", 1001, "missing.txt")
    assert exc_info.value.code == "file_not_found"


@pytest.mark.asyncio
async def test_run_cli_chat_resets_and_persists_kimi_session(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    session.kimi_session_id = "kimi-stale"
    session.persist = MagicMock()

    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="kimi"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["kimi"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_process", new_callable=AsyncMock, return_value=("session expired", 1, False)):
        data = await run_cli_chat(web_manager, "main", 1001, "hello")

    assert data["returncode"] == 1
    assert session.kimi_session_id is None
    session.persist.assert_called()


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
async def test_run_cli_chat_persists_assistant_elapsed_seconds(web_manager: MultiBotManager):
    session = get_session_for_alias(web_manager, "main", 1001)
    fake_process = MagicMock()

    with patch("bot.web.api_service.resolve_cli_executable", return_value="kimi"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["kimi"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process), \
         patch("bot.web.api_service._communicate_process", new_callable=AsyncMock, return_value=("完成回复", 0, False)):
        data = await run_cli_chat(web_manager, "main", 1001, "hello")

    assert data["output"] == "完成回复"
    assert isinstance(data["elapsed_seconds"], int)
    assert data["elapsed_seconds"] >= 0
    assert session.history[-1]["role"] == "assistant"
    assert session.history[-1]["content"] == "完成回复"
    assert session.history[-1]["elapsed_seconds"] == data["elapsed_seconds"]


@pytest.mark.asyncio
async def test_stream_cli_chat_done_event_includes_elapsed_seconds(web_manager: MultiBotManager):
    fake_stdout = MagicMock()
    fake_stdout.readline.return_value = ""
    fake_stdout.read.return_value = ""

    fake_process = MagicMock()
    fake_process.stdout = fake_stdout
    fake_process.poll.return_value = 0
    fake_process.wait.return_value = 0

    with patch("bot.web.api_service.resolve_cli_executable", return_value="kimi"), \
         patch("bot.web.api_service.build_cli_command", return_value=(["kimi"], False)), \
         patch("bot.web.api_service.subprocess.Popen", return_value=fake_process):
        events = [event async for event in _stream_cli_chat(web_manager, "main", 1001, "hello")]

    done_event = next(event for event in events if event["type"] == "done")
    assert done_event["output"] == "（无输出）" or isinstance(done_event["output"], str)
    assert isinstance(done_event["elapsed_seconds"], int)
    assert done_event["elapsed_seconds"] >= 0


@pytest.mark.asyncio
async def test_run_assistant_chat_persists_assistant_elapsed_seconds(web_manager: MultiBotManager):
    web_manager.main_profile.bot_mode = "assistant"
    session = get_session_for_alias(web_manager, "main", 1001)

    async def fake_stream(*args, **kwargs):
        yield {"type": "text", "text": "你好"}

    with patch("bot.web.api_service.ANTHROPIC_AVAILABLE", True), \
         patch("bot.web.api_service._build_system_prompt_with_memory", return_value="system"), \
         patch("bot.web.api_service.call_claude_with_memory_tools_stream", fake_stream):
        data = await run_assistant_chat(web_manager, "main", 1001, "hello")

    assert data["output"] == "你好"
    assert isinstance(data["elapsed_seconds"], int)
    assert data["elapsed_seconds"] >= 0
    assert session.history[-1]["role"] == "assistant"
    assert session.history[-1]["content"] == "你好"
    assert session.history[-1]["elapsed_seconds"] == data["elapsed_seconds"]


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
