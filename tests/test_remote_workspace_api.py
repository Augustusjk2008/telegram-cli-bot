from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from bot.manager import MultiBotManager
from bot.models import BotProfile
from bot.remote_workspace import RemoteWorkspaceError
from bot.web.api_common import AuthContext, WebApiError
from bot.web.api_common import get_session_for_alias
from bot.web.auth_store import CAP_GIT_OPS, CAP_MANAGE_BOTS, CAP_READ_FILE_CONTENT, CAP_TERMINAL_EXEC, CAP_VIEW_FILE_TREE, CAP_WRITE_FILES
from bot.web import api_service
from bot.web.routes import remote_routes
from bot.web.server import WebApiServer


CONFIG = {
    "connection_id": "a" * 32,
    "host": "remote.example", "port": 22, "username": "developer", "root": "/srv/project",
    "host_key_fingerprint": "SHA256:" + "a" * 43, "key_filename": "",
}
NEW_CONFIG = {**CONFIG, "connection_id": "b" * 32, "host": "new.example", "root": "/srv/new-project"}


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
async def test_execute_plan_saves_in_remote_workspace_before_creating_conversation(tmp_path, monkeypatch):
    server, _auth = _server(tmp_path, monkeypatch)
    connection = Mock()
    connection.mkdir.side_effect = [RemoteWorkspaceError(409, "path_exists", "Exists"), None]
    connection.create_file.side_effect = [RemoteWorkspaceError(409, "path_exists", "Exists"), None]
    service = Mock()
    service.get.return_value = connection
    monkeypatch.setattr("bot.remote_workspace.get_remote_workspace_service", lambda: service)
    create_conversation = AsyncMock(return_value={"conversation": {"id": "new"}, "messages": []})
    monkeypatch.setattr(api_service, "create_conversation", create_conversation)

    result = await api_service.execute_plan(server.manager, "main", 42, "# Ship\nDo it", title="Ship")

    service.get.assert_called_once_with(CONFIG)
    assert connection.mkdir.call_args_list == [
        (("docs",), {"root": CONFIG["root"]}),
        (("docs/plan",), {"root": CONFIG["root"]}),
    ]
    first_path = connection.create_file.call_args_list[0].args[0]
    second_path = connection.create_file.call_args_list[1].args[0]
    assert first_path.startswith("docs/plan/") and first_path.endswith("-ship.md")
    assert second_path == first_path.removesuffix(".md") + "-2.md"
    assert connection.create_file.call_args_list[1].args[1:] == ("# Ship\nDo it\n",)
    assert connection.create_file.call_args_list[1].kwargs == {"root": CONFIG["root"]}
    assert result["plan_path"] == second_path
    assert second_path in result["execution_message"]
    create_conversation.assert_awaited_once()
    assert not (Path(server.manager.main_profile.working_dir) / "docs" / "plan").exists()


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


def _forbid_local_git(server, monkeypatch):
    for name in dir(server):
        if name.startswith(("get_git_", "post_git_", "put_git_", "patch_git_")):
            monkeypatch.setattr(server, name, AsyncMock(side_effect=AssertionError("remote request reached local Git")))
    monkeypatch.setattr("bot.web.git_service._run_git", Mock(side_effect=AssertionError("local Git executed")))


@pytest.mark.asyncio
@pytest.mark.parametrize("method,suffix,body,operation,args,kwargs", [
    ("GET", "git", None, "overview", (), {}),
    ("GET", "git/diff?path=a%20b.txt&staged=true", None, "diff", ("a b.txt",), {"staged": True}),
    ("POST", "git/stage", {"paths": ["a b.txt"]}, "stage", (["a b.txt"],), {}),
    ("POST", "git/unstage", {"paths": ["a b.txt"]}, "unstage", (["a b.txt"],), {}),
    ("POST", "git/commit", {"message": "remote commit"}, "commit", ("remote commit",), {}),
])
async def test_remote_git_allowlist_permissions_and_local_isolation(
    tmp_path, monkeypatch, method, suffix, body, operation, args, kwargs,
):
    server, auth = _server(tmp_path, monkeypatch)
    _forbid_local_git(server, monkeypatch)
    local = Path(server.manager.main_profile.working_dir)
    before = {path.relative_to(local): path.read_bytes() for path in local.rglob("*") if path.is_file()}
    service, connection, git = Mock(), Mock(), Mock()
    service.get.return_value = connection
    payload = {"path": "a b.txt", "diff": "remote diff", "staged": True, "truncated": False} if operation == "diff" else {
        "repo_found": True, "working_dir": CONFIG["root"],
    }
    messages = {"stage": "已暂存所选文件", "unstage": "已取消暂存所选文件", "commit": "已创建提交"}
    expected = {"message": messages[operation], "overview": payload} if operation in messages else payload
    getattr(git, operation).return_value = payload
    factory = Mock(return_value=git)
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    monkeypatch.setattr(remote_routes, "RemoteGitService", factory)
    async with TestClient(TestServer(server._build_app())) as client:
        url = f"/api/bots/MAIN/{suffix}"
        response = await client.request(method, url, json=body)
        assert response.status == 403
        service.get.assert_not_called()
        auth.capabilities.add(CAP_GIT_OPS)
        # Git access does not require file-tree permission.
        auth.capabilities.remove(CAP_VIEW_FILE_TREE)
        response = await client.request(method, url, json=body)
        assert response.status == 200, await response.text()
        assert (await response.json())["data"] == expected
        factory.assert_called_once_with(connection, CONFIG["root"])
        getattr(git, operation).assert_called_once_with(*args, **kwargs)
        monkeypatch.setattr(server, "_can_operate_bot", lambda auth, alias: False)
        response = await client.request(method, url, json=body)
        assert response.status == 403
        assert getattr(git, operation).call_count == 1
    assert {path.relative_to(local): path.read_bytes() for path in local.rglob("*") if path.is_file()} == before


@pytest.mark.asyncio
async def test_all_other_remote_git_routes_remain_unavailable(tmp_path, monkeypatch):
    server, auth = _server(tmp_path, monkeypatch)
    auth.capabilities.add(CAP_GIT_OPS)
    _forbid_local_git(server, monkeypatch)
    service = Mock()
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    app = server._build_app()
    allowed = {("GET", "git"), ("GET", "git/diff"), ("POST", "git/stage"), ("POST", "git/unstage"), ("POST", "git/commit")}
    routes = [(route.method, route.resource.canonical) for route in app.router.routes()
              if route.method != "HEAD" and route.resource.canonical.startswith("/api/bots/{alias}/git")]
    async with TestClient(TestServer(app)) as client:
        for method, path in routes:
            suffix = path.removeprefix("/api/bots/{alias}/")
            if (method, suffix) in allowed:
                continue
            url = path.replace("{alias}", "main").replace("{job_id}", "test-job")
            response = await client.request(method, url, json={})
            assert response.status == 409, (method, path, await response.text())
            assert (await response.json())["error"]["code"] == "remote_feature_unavailable"
        auth.capabilities.remove(CAP_GIT_OPS)
        response = await client.post("/api/bots/main/git/init", json={})
        assert response.status == 403
    service.get.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(409, "remote_git_not_found"), (401, "remote_auth_failed"), (502, "remote_connection_failed")])
async def test_remote_git_preserves_error_codes(tmp_path, monkeypatch, status, code):
    server, auth = _server(tmp_path, monkeypatch)
    auth.capabilities.add(CAP_GIT_OPS)
    service = Mock()
    service.get.side_effect = remote_routes.RemoteWorkspaceError(status, code, "remote failure")
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.get("/api/bots/main/git")
        assert response.status == status
        assert (await response.json())["error"]["code"] == code


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
@pytest.mark.parametrize("target", [CONFIG, {**CONFIG, "platform": "windows", "root": "/C:/Projects/demo"}])
async def test_remote_bot_persistence_keeps_local_runtime_separate(tmp_path, monkeypatch, target):
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(tmp_path)), str(storage))
    profile = await manager.add_bot(
        "remote", supported_execution_modes=["native_agent"], default_execution_mode="native_agent",
        remote_workspace={**target, "password": "must-not-persist"},
    )
    assert Path(profile.working_dir).is_dir()
    assert Path(profile.working_dir).is_relative_to(tmp_path / "runtime-data" / "remote-workspaces")
    assert profile.remote_workspace["root"] == target["root"]
    assert profile.remote_workspace.get("platform") == target.get("platform")
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
async def test_existing_remote_bot_update_checks_draft_owner_and_resets_session(tmp_path, monkeypatch):
    from bot.remote_workspace.chat import prepare_remote_chat, resolve_remote_chat_token

    server, auth = _server(tmp_path, monkeypatch)
    profile = server.manager.main_profile
    control_dir = profile.working_dir
    session = get_session_for_alias(server.manager, "main", auth.user_id)
    session.codex_session_id = "codex-old"
    session.native_agent_session_id = "native-old"
    session.active_conversation_id = "conversation-old"
    prior_epoch = session.session_epoch
    old_bridge = prepare_remote_chat(profile, "http://127.0.0.1:8765")
    import json
    old_token = json.loads(old_bridge.config_path.read_text(encoding="utf-8"))["token"]

    service = Mock()
    service.connection_config.return_value = NEW_CONFIG
    service.bind_root.return_value = NEW_CONFIG
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    history = Mock()
    history.has_active_conversation.return_value = True
    history.summarize_active_conversation.return_value = {"history_count": 1}
    monkeypatch.setattr(api_service, "_get_chat_history_service", lambda _session: history)
    body = {"remote_workspace": {
        "connection_id": NEW_CONFIG["connection_id"], "root": NEW_CONFIG["root"],
        "host": "forged.example", "password": "must-not-persist",
    }}

    async with TestClient(TestServer(server._build_app())) as client:
        session.is_processing = True
        response = await client.patch("/api/admin/bots/main/workdir", json={**body, "force_reset": True})
        assert response.status == 409
        assert (await response.json())["error"]["code"] == "workdir_change_blocked_processing"
        session.is_processing = False

        response = await client.patch("/api/admin/bots/main/workdir", json=body)
        payload = await response.json()
        assert response.status == 409
        assert payload["error"]["code"] == "workdir_change_requires_reset"
        assert payload["error"]["data"]["current_working_dir"] == CONFIG["root"]
        assert payload["error"]["data"]["requested_working_dir"] == NEW_CONFIG["root"]
        assert profile.remote_workspace == CONFIG
        assert session.codex_session_id == "codex-old"

        service.connection_config.side_effect = remote_routes.RemoteWorkspaceError(404, "remote_connection_not_found", "Remote connection not found")
        response = await client.patch("/api/admin/bots/main/workdir", json={**body, "force_reset": True})
        assert response.status == 404
        assert profile.remote_workspace == CONFIG
        service.connection_config.side_effect = None

        auth.capabilities.remove(CAP_MANAGE_BOTS)
        response = await client.patch("/api/admin/bots/main/workdir", json={**body, "force_reset": True})
        assert response.status == 403
        assert profile.remote_workspace == CONFIG
        auth.capabilities.add(CAP_MANAGE_BOTS)

        checked_connections = service.connection_config.call_count
        monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, _alias: False)
        response = await client.patch("/api/admin/bots/main/workdir", json={**body, "force_reset": True})
        assert response.status == 403
        assert service.connection_config.call_count == checked_connections
        monkeypatch.setattr(server, "_can_operate_bot", lambda _auth, alias: alias == "main")

        response = await client.patch("/api/admin/bots/main/workdir", json={**body, "force_reset": True})
        payload = await response.json()
        assert response.status == 200, payload
        assert payload["data"]["bot"]["remote_workspace"] == NEW_CONFIG

    service.connection_config.assert_called_with(NEW_CONFIG["connection_id"], auth.user_id)
    service.bind_root.assert_called_with(NEW_CONFIG, NEW_CONFIG["root"])
    history.reset_active_conversation.assert_called_once_with(session)
    assert profile.working_dir == control_dir
    assert profile.remote_workspace == NEW_CONFIG
    assert session.codex_session_id is None
    assert session.native_agent_session_id is None
    assert session.active_conversation_id is None
    assert session.session_epoch == prior_epoch + 1
    assert NEW_CONFIG["host"] in (Path(control_dir) / "AGENTS.md").read_text(encoding="utf-8")
    assert resolve_remote_chat_token(old_token) is None
    reloaded = MultiBotManager(BotProfile(alias="main", working_dir=control_dir), str(server.manager.storage_file))
    assert reloaded.main_profile.remote_workspace == NEW_CONFIG
    assert "must-not-persist" not in server.manager.app_settings_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_managed_remote_bot_update_persists_same_control_directory(tmp_path):
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(tmp_path)), str(storage))
    profile = await manager.add_bot(
        "remote", supported_execution_modes=["native_agent"], default_execution_mode="native_agent",
        remote_workspace=CONFIG,
    )
    control_dir = profile.working_dir

    await manager.set_bot_remote_workspace("remote", NEW_CONFIG)

    assert profile.working_dir == control_dir
    assert NEW_CONFIG["root"] in (Path(control_dir) / "CLAUDE.md").read_text(encoding="utf-8")
    reloaded = MultiBotManager(manager.main_profile, str(storage)).managed_profiles["remote"]
    assert reloaded.remote_workspace == NEW_CONFIG
    assert reloaded.working_dir == control_dir


@pytest.mark.asyncio
async def test_failed_remote_bot_save_restores_profile_and_instructions(tmp_path, monkeypatch):
    storage = tmp_path / "bots.json"
    storage.write_text('{"bots": []}', encoding="utf-8")
    manager = MultiBotManager(BotProfile(alias="main", working_dir=str(tmp_path)), str(storage))
    profile = await manager.add_bot(
        "remote", supported_execution_modes=["native_agent"], default_execution_mode="native_agent",
        remote_workspace=CONFIG,
    )
    instructions = Path(profile.working_dir) / "AGENTS.md"
    before = instructions.read_text(encoding="utf-8")
    monkeypatch.setattr(manager, "_save_profiles", Mock(side_effect=OSError("save failed")))

    with pytest.raises(OSError, match="save failed"):
        await manager.set_bot_remote_workspace("remote", NEW_CONFIG)

    assert profile.remote_workspace == CONFIG
    assert instructions.read_text(encoding="utf-8") == before
    assert MultiBotManager(manager.main_profile, str(storage)).managed_profiles["remote"].remote_workspace == CONFIG


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
async def test_disconnect_remote_closes_only_an_authorized_bot_connection(tmp_path, monkeypatch):
    server, auth = _server(tmp_path, monkeypatch)
    service = Mock()
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.post("/api/bots/MAIN/remote/disconnect")
        assert response.status == 200
        assert (await response.json())["data"] == {"disconnected": True}
        service.get.assert_called_once_with(CONFIG)
        service.get.return_value.close.assert_called_once_with()

        auth.capabilities.remove(CAP_MANAGE_BOTS)
        response = await client.post("/api/bots/main/remote/disconnect")
        assert response.status == 403
        service.get.return_value.close.assert_called_once()


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


@pytest.mark.asyncio
async def test_windows_routes_normalize_native_paths_and_bind_platform(tmp_path, monkeypatch):
    server, _auth = _server(tmp_path, monkeypatch)
    config = {**CONFIG, "platform": "windows", "root": "/C:/Projects/demo"}
    server.manager.main_profile.remote_workspace = config
    service, connection = Mock(), Mock()
    service.get.return_value = connection
    service.connection_config.return_value = config
    connection.read_file.return_value = {"filename": "中文.txt", "content": "hello", "last_modified_ns": "hash"}
    connection.list_directory.return_value = {"working_dir": "/D:/code", "entries": [], "is_virtual_root": False}
    monkeypatch.setattr(remote_routes, "get_remote_workspace_service", lambda: service)
    async with TestClient(TestServer(server._build_app())) as client:
        response = await client.get("/api/bots/main/files/read", params={"filename": r"C:\Projects\demo\中文.txt"})
        assert response.status == 200
        connection.read_file.assert_called_once_with("/C:/Projects/demo/中文.txt", root=config["root"], limit=0)
        response = await client.get(f"/api/remote/connections/{config['connection_id']}/directories", params={"path": r"D:\code"})
        assert response.status == 200
        connection.list_directory.assert_called_once_with("/D:/code", root="/D:/")
        response = await client.post("/api/bots/main/remote/connect", json={"platform": "posix", "password": "secret"})
        assert response.status == 409
        service.connect.assert_not_called()
