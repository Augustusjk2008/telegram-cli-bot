from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_MANAGE_BOTS, CAP_READ_FILE_CONTENT, CAP_TERMINAL_EXEC, CAP_VIEW_FILE_TREE, CAP_WRITE_FILES
from bot.web.routes import remote_routes
from bot.web.server import WebApiServer


CONFIG = {
    "connection_id": "a" * 32,
    "host": "remote.example", "port": 22, "username": "developer", "root": "/srv/project",
    "host_key_fingerprint": "SHA256:" + "a" * 43, "key_filename": "",
}


def _server(tmp_path, monkeypatch):
    local = tmp_path / "local-control"
    local.mkdir()
    (local / "private.txt").write_text("local-only", encoding="utf-8")
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    profile = BotProfile(alias="main", working_dir=str(local), remote_workspace=dict(CONFIG))
    manager = MultiBotManager(profile, str(storage))
    monkeypatch.setattr("bot.web.server.WEB_API_TOKEN", "")
    monkeypatch.setattr("bot.web.server.WEB_BASE_PATH", "")
    server = WebApiServer(manager, host="127.0.0.1", port=8765)
    auth = AuthContext(user_id=42, token_used=True, account_id="member", capabilities={
        CAP_VIEW_FILE_TREE, CAP_READ_FILE_CONTENT, CAP_WRITE_FILES, CAP_TERMINAL_EXEC, CAP_MANAGE_BOTS,
    })
    monkeypatch.setattr(server, "_auth_context", lambda request: auth)
    monkeypatch.setattr(server, "_can_operate_bot", lambda auth, alias: alias == "main")
    return server, auth


@pytest.mark.asyncio
async def test_remote_files_use_ssh_root_and_enforce_file_permissions(tmp_path, monkeypatch):
    server, auth = _server(tmp_path, monkeypatch)
    connection = Mock()
    connection.list_directory.return_value = {"working_dir": CONFIG["root"], "entries": [{"name": "app.py", "is_dir": False}], "is_virtual_root": False}
    connection.read_file.return_value = {"filename": "app.py", "content": "remote", "last_modified_ns": "123"}
    connection.write_file.return_value = {"path": "app.py", "last_modified_ns": "456"}
    connection.execute.return_value = {"stdout": "/srv/project", "returncode": 0}
    service = Mock()
    service.get.return_value = connection
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.get("/api/bots/main/ls")
        assert (await response.json())["data"]["entries"][0]["name"] == "app.py"
        response = await client.get("/api/bots/MAIN/files/read?filename=app.py")
        assert (await response.json())["data"]["content"] == "remote"
        response = await client.post("/api/bots/main/files/write", json={"path": "app.py", "content": "new", "expected_mtime_ns": "123"})
        assert response.status == 200
        connection.write_file.assert_called_once_with("/srv/project/app.py", "new", root="/srv/project", expected_mtime_ns="123", encoding="utf-8")
        auth.capabilities.remove(CAP_WRITE_FILES)
        response = await client.post("/api/bots/main/files/write", json={"path": "app.py", "content": "unauthorized"})
        assert response.status == 403
        assert connection.write_file.call_count == 1
        response = await client.post("/api/bots/MAIN/exec", json={"command": "pwd"})
        assert response.status == 200
        connection.execute.assert_called_once_with("pwd", root="/srv/project")
        response = await client.get("/api/bots/main/workspace/search?query=local-only")
        assert response.status == 409
        assert (await response.json())["error"]["code"] == "remote_feature_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("route_alias", ["", "MAIN"])
async def test_remote_terminal_checks_bot_access_and_uses_remote_factory(tmp_path, monkeypatch, route_alias):
    server, auth = _server(tmp_path, monkeypatch)
    connection = Mock()
    connection.canonical_root.return_value = "/srv/project/subdir"
    service = Mock()
    service.get.return_value = connection
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    server._terminal_manager.create = AsyncMock(return_value={"started": True})
    request = make_mocked_request("POST", "/api/terminal/session/create", match_info={"alias": route_alias} if route_alias else {})
    body = {"owner_id": "tab-1", "cwd": "/srv/project/subdir", **({} if route_alias else {"bot_alias": "main"})}
    response = await remote_routes.create_terminal(server, request, auth, body, (90, 30))
    assert response.status == 200
    call = server._terminal_manager.create.call_args
    assert call.args == (42, "tab-1")
    assert call.kwargs["cwd"] == "/srv/project/subdir"
    process = call.kwargs["process_factory"]()
    assert process.is_pty is True
    connection.open_terminal.assert_called_once_with("/srv/project/subdir", cols=90, rows=30)
    monkeypatch.setattr(server, "_can_operate_bot", lambda auth, alias: False)
    with pytest.raises(WebApiError, match="无权访问"):
        await remote_routes.create_terminal(server, request, auth, body, (90, 30))
    assert server._terminal_manager.create.await_count == 1


@pytest.mark.asyncio
async def test_remote_bot_persistence_keeps_local_runtime_separate(tmp_path, monkeypatch):
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(tmp_path)), str(storage))
    profile = await manager.add_bot(
        "remote", supported_execution_modes=["native_agent"], default_execution_mode="native_agent",
        remote_workspace={**CONFIG, "password": "must-not-persist"},
    )
    assert Path(profile.working_dir).is_dir()
    assert Path(profile.working_dir).is_relative_to(tmp_path / "runtime-data" / "remote-workspaces")
    assert profile.remote_workspace["root"] == "/srv/project"
    assert "must-not-persist" not in storage.read_text(encoding="utf-8")
    reloaded = MultiBotManager(manager.main_profile, str(storage)).managed_profiles["remote"]
    assert reloaded.remote_workspace == profile.remote_workspace
    with pytest.raises(ValueError, match="工作区已绑定"):
        await manager.set_bot_workdir("remote", str(tmp_path))


@pytest.mark.asyncio
async def test_remote_draft_connection_is_checked_before_binding_root():
    service = Mock()
    service.connection_config.side_effect = WebApiError(403, "forbidden", "connection belongs to another user")
    from unittest.mock import patch
    with patch.object(remote_routes, "get_remote_workspace_service", return_value=service):
        with pytest.raises(WebApiError):
            await remote_routes.prepare_create(SimpleNamespace(), SimpleNamespace(user_id=42), {"connection_id": "other", "root": "/etc"})
    service.bind_root.assert_not_called()


@pytest.mark.asyncio
async def test_ssh_login_confirmation_and_remote_creation_contract(tmp_path, monkeypatch):
    from bot.web.permission_store import BotPermissionStore

    server, auth = _server(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_can_operate_bot", lambda auth, alias: True)
    monkeypatch.setattr("bot.web.server._BOT_PERMISSION_STORE", BotPermissionStore(tmp_path / "permissions.json"))
    service = Mock()
    service.connect.side_effect = [
        remote_routes.RemoteWorkspaceError(409, "host_key_confirmation_required", "Confirm host key", {"host_key_fingerprint": CONFIG["host_key_fingerprint"]}),
        dict(CONFIG),
    ]
    service.connection_config.return_value = dict(CONFIG)
    service.bind_root.return_value = dict(CONFIG)
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    async with TestClient(TestServer(server._build_app())) as client:
        login = {"host": CONFIG["host"], "username": CONFIG["username"], "password": "secret"}
        response = await client.post("/api/remote/connections", json=login)
        payload = await response.json()
        assert response.status == 409
        assert payload["error"]["code"] == "remote_host_key_unknown"
        assert payload["error"]["data"]["fingerprint"] == CONFIG["host_key_fingerprint"]
        response = await client.post("/api/remote/connections", json={**login, "host_key_fingerprint": CONFIG["host_key_fingerprint"]})
        assert response.status == 200
        response = await client.post("/api/admin/bots", json={
            "alias": "remote", "supported_execution_modes": ["native_agent"], "default_execution_mode": "native_agent",
            "remote_workspace": {"connection_id": CONFIG["connection_id"], "root": CONFIG["root"]},
        })
        data = await response.json()
        assert response.status == 200, data
        bot = data["data"]["bot"]
        assert bot["remote_workspace"] == CONFIG
        assert CONFIG["root"] in (Path(bot["working_dir"]) / "AGENTS.md").read_text(encoding="utf-8")
        service.connection_config.assert_called_once_with(CONFIG["connection_id"], auth.user_id)


@pytest.mark.asyncio
async def test_agent_bridge_scopes_tokens_and_rejects_changed_workspaces(tmp_path, monkeypatch):
    from bot.remote_workspace.chat import prepare_remote_chat
    from bot.remote_workspace import tools

    server, _auth = _server(tmp_path, monkeypatch)
    profile = server.manager.main_profile
    bridge = prepare_remote_chat(profile, "http://127.0.0.1:8765")
    import json
    token = json.loads(bridge.config_path.read_text(encoding="utf-8"))["token"]
    execute = Mock(return_value={"stdout": "remote", "returncode": 0})
    monkeypatch.setattr(tools, "execute_remote_tool", execute)
    body = {"tool": "exec", "arguments": {"commands": ["pwd"]}}
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.post("/api/remote/agent-tools", json=body)
        assert response.status == 401
        response = await client.post("/api/remote/agent-tools", json=body, headers={"X-TCB-Remote-Token": token})
        assert response.status == 200
        assert execute.call_args.args[0]["root"] == "/srv/project"
        profile.remote_workspace = {**CONFIG, "root": "/srv/different"}
        response = await client.post("/api/remote/agent-tools", json=body, headers={"X-TCB-Remote-Token": token})
        assert response.status == 401
        assert execute.call_count == 1


def test_agent_tools_batch_commands_and_edit_with_optimistic_version(monkeypatch):
    from bot.remote_workspace import tools

    connection = Mock()
    connection.canonical_root.return_value = "/srv/project/src"
    connection.execute.return_value = {"stdout": "ok", "returncode": 0}
    service = Mock()
    service.get.return_value = connection
    monkeypatch.setattr(tools, "get_remote_workspace_service", lambda: service)
    tools.execute_remote_tool(CONFIG, "exec", {"commands": ["pwd", "ls"], "cwd": "src"})
    connection.execute.assert_called_once_with("set -e\npwd\nls", root="/srv/project/src", timeout=60, max_output=12000)
    connection.read_file.return_value = {"content": "old text", "last_modified_ns": "17", "encoding": "utf-8-sig"}
    tools.execute_remote_tool(CONFIG, "edit", {"path": "app.py", "old_text": "old", "new_text": "new"})
    connection.write_file.assert_called_once_with("app.py", "new text", root="/srv/project", expected_mtime_ns="17", encoding="utf-8-sig")
    connection.read_file.return_value["content"] = "old old"
    with pytest.raises(remote_routes.RemoteWorkspaceError, match="exactly once"):
        tools.execute_remote_tool(CONFIG, "edit", {"path": "app.py", "old_text": "old", "new_text": "new"})
    assert connection.write_file.call_count == 1
