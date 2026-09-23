"""Remote workspace endpoints using the existing Web authentication and SSH pool."""
from __future__ import annotations

import asyncio
import json
import posixpath
from typing import Any

from aiohttp import web

from bot.platform.terminal import PtyWrapper
from bot.remote_workspace.transport import RemoteWorkspaceError, get_remote_workspace_service, join_remote_path
from bot.remote_workspace.tools import resolve_remote_directory
from bot.web.api_common import WebApiError, _require_capability, get_profile_or_raise
from bot.web.auth_store import (
    CAP_MANAGE_BOTS, CAP_MUTATE_BROWSE_STATE, CAP_READ_FILE_CONTENT,
    CAP_TERMINAL_EXEC, CAP_VIEW_FILE_TREE, CAP_WRITE_FILES,
)


def _response(data: dict[str, Any]) -> web.Response:
    response = web.json_response({"ok": True, "data": data}, dumps=lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    response.enable_compression()
    return response


def _relative_target(path: Any, current: str, platform: str = "posix") -> str:
    text = str(path or "").strip()
    return join_remote_path(current, text, platform)


async def prepare_create(server, auth, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WebApiError(400, "invalid_remote_workspace", "远程工作区配置必须是对象")
    service = get_remote_workspace_service()
    config = service.connection_config(str(value.get("connection_id") or ""), auth.user_id)
    return await asyncio.to_thread(service.bind_root, config, str(value.get("root") or config["root"]))


async def create_terminal(server, request: web.Request, auth, body: dict[str, Any], size) -> web.Response | None:
    alias = str(request.match_info.get("alias") or body.get("bot_alias") or "").strip().lower()
    if not alias:
        return None
    auth = server._bot_auth(auth, alias)
    _require_capability(auth, CAP_TERMINAL_EXEC)
    profile = get_profile_or_raise(server.manager, alias)
    if not profile.remote_workspace:
        return None
    config = dict(profile.remote_workspace)
    cwd = str(body.get("cwd") or config["root"])
    # Resolve the directory without enumerating its files on each terminal open.
    service = get_remote_workspace_service()
    connection = await asyncio.to_thread(service.get, config)
    cwd = await asyncio.to_thread(resolve_remote_directory, connection, cwd, config["root"], config.get("platform", "posix"))
    cols, rows = size or (120, 40)

    def open_process():
        return PtyWrapper(
            connection.open_terminal(cwd, cols=cols, rows=rows),
            is_pty=True,
            read_timeout_supported=True,
        )

    data = await server._terminal_manager.create(
        auth.user_id, server._resolve_terminal_owner_id(body.get("owner_id")),
        cwd=cwd, shell_type="ssh", cols=cols, rows=rows, process_factory=open_process,
    )
    return _response(data)


def middleware(server):
    browse_dirs: dict[tuple[str, int], str] = {}

    @web.middleware
    async def dispatch(request: web.Request, handler):
        try:
            alias = str(request.match_info.get("alias") or "").strip().lower()
            profile = None if not alias else (
                server.manager.main_profile if alias == server.manager.main_profile.alias
                else server.manager.managed_profiles.get(alias)
            )
            if alias and profile is not None and profile.remote_workspace:
                route = request.match_info.route.resource.canonical
                marker = "/api/bots/{alias}/"
                suffix = route.split(marker, 1)[-1] if marker in route else ""
                result = await _workspace_request(server, request, profile, suffix, browse_dirs)
                if result is not None:
                    return result
            return await handler(request)
        except RemoteWorkspaceError as exc:
            if exc.code == "host_key_confirmation_required":
                raise WebApiError(409, "remote_host_key_unknown", exc.message, {
                    "fingerprint": exc.data.get("host_key_fingerprint", ""),
                }) from exc
            raise WebApiError(exc.status, exc.code, exc.message, exc.data) from exc

    return dispatch


async def _workspace_request(server, request, profile, suffix, browse_dirs):
    operations = {
        ("GET", "pwd"): CAP_VIEW_FILE_TREE,
        ("GET", "ls"): CAP_VIEW_FILE_TREE,
        ("POST", "cd"): CAP_MUTATE_BROWSE_STATE,
        ("POST", "files/reveal"): CAP_VIEW_FILE_TREE,
        ("GET", "files/read"): CAP_READ_FILE_CONTENT,
        ("POST", "files/write"): CAP_WRITE_FILES,
        ("POST", "files/create"): CAP_WRITE_FILES,
        ("POST", "files/mkdir"): CAP_WRITE_FILES,
        ("POST", "exec"): CAP_TERMINAL_EXEC,
    }
    capability = operations.get((request.method, suffix))
    if capability is None:
        # Unsupported workspace features must never act on the local control
        # directory. Conversation/history storage remains local as intended.
        unsupported = suffix.startswith((
            "files/", "workspace/", "git/", "debug/", "plugins/", "terminal-actions/",
            "native-agent/history/", "workdir", "chat/attachments",
        )) or suffix in {"git", "debug", "plugins"}
        if unsupported:
            await server._with_capability(request, CAP_VIEW_FILE_TREE)
            raise WebApiError(409, "remote_feature_unavailable", "远程工作区当前支持聊天、文件树、文本读写和终端")
        return None
    auth = await server._with_capability(request, capability)
    config = profile.remote_workspace
    root = config["root"]
    platform = config.get("platform", "posix")
    key = (profile.alias, auth.user_id)
    current = browse_dirs.get(key, root)
    if suffix == "pwd":
        return _response({"working_dir": root})
    service = get_remote_workspace_service()
    connection = await asyncio.to_thread(service.get, config)
    if suffix == "ls":
        return _response(await asyncio.to_thread(
            connection.list_directory, _relative_target(request.query.get("path"), current, platform), root=root,
        ))
    if suffix == "files/read":
        try:
            limit = max(0, int(request.query.get("lines", "20"))) if request.query.get("mode") == "head" else 0
        except ValueError as exc:
            raise WebApiError(400, "invalid_lines", "行数必须是整数") from exc
        data = await asyncio.to_thread(
            connection.read_file, _relative_target(request.query.get("filename"), current, platform), root=root, limit=limit,
        )
        return _response(data)
    body = await server._parse_json(request)
    if suffix == "cd":
        directory = await asyncio.to_thread(resolve_remote_directory, connection, _relative_target(body.get("path"), current, platform), root, platform)
        browse_dirs[key] = directory
        return _response({"working_dir": directory, "is_virtual_root": False})
    if suffix == "files/reveal":
        return _response(await asyncio.to_thread(_reveal, connection, root, current, body.get("path"), platform))
    if suffix == "files/write":
        if not isinstance(body.get("content"), str):
            raise WebApiError(400, "invalid_content", "文件内容必须是文本")
        return _response(await asyncio.to_thread(
            connection.write_file, _relative_target(body.get("path"), current, platform), body["content"], root=root,
            expected_mtime_ns=body.get("expected_mtime_ns"),
            encoding=body.get("encoding") or "utf-8",
        ))
    if suffix in {"files/create", "files/mkdir"}:
        name = str(body.get("filename" if suffix == "files/create" else "name") or "").strip()
        if not name or name in {".", ".."} or "/" in name or "\x00" in name or (platform == "windows" and "\\" in name):
            raise WebApiError(400, "invalid_filename", "请输入有效的文件或文件夹名称")
        parent = _relative_target(body.get("parent_path"), current, platform)
        path = join_remote_path(parent, name, platform)
        if suffix == "files/mkdir":
            data = await asyncio.to_thread(connection.mkdir, path, root=root)
        else:
            data = await asyncio.to_thread(connection.create_file, path, str(body.get("content") or ""), root=root)
        return _response(data)
    if suffix == "exec":
        command = str(body.get("command") or "").strip()
        if not command:
            raise WebApiError(400, "empty_command", "命令不能为空")
        return _response(await asyncio.to_thread(connection.execute, command, root=root))
    return None


def _reveal(connection, root: str, current: str, path: Any, platform: str = "posix") -> dict[str, Any]:
    target = _relative_target(path, current, platform)
    if platform != "windows":
        target = posixpath.normpath(target)
    if target != root and not target.startswith(root.rstrip("/") + "/"):
        raise WebApiError(403, "forbidden_path", "路径不在远程工作区内")
    relative = posixpath.relpath(target, root)
    parts = [] if relative == "." else relative.split("/")
    branches = {}
    branch = ""
    for index in range(len(parts) + 1):
        listing = connection.list_directory(posixpath.join(root, branch), root=root)
        branches[branch] = listing["entries"]
        if index == len(parts):
            break
        entry = next((item for item in listing["entries"] if item["name"] == parts[index]), None)
        if entry is None:
            raise WebApiError(404, "path_not_found", "文件或文件夹不存在")
        if not entry["is_dir"]:
            if index < len(parts) - 1:
                raise WebApiError(404, "path_not_found", "文件或文件夹不存在")
            break
        branch = posixpath.join(branch, parts[index])
    return {
        "root_path": root, "highlight_path": "" if relative == "." else relative,
        "expanded_paths": [item for item in branches if item], "branches": branches,
    }


def register(app: web.Application, server) -> None:
    async def agent_tools(request):
        from bot.remote_workspace.chat import resolve_remote_chat_token, remote_workspace_fingerprint
        from bot.remote_workspace.tools import execute_remote_tool
        scoped = resolve_remote_chat_token(request.headers.get("X-TCB-Remote-Token", ""))
        if scoped is None:
            raise WebApiError(401, "remote_agent_unauthorized", "Remote agent capability is invalid")
        profile = get_profile_or_raise(server.manager, scoped.alias)
        if (profile.archived or not profile.enabled or profile.working_dir != scoped.working_dir
                or remote_workspace_fingerprint(profile) != remote_workspace_fingerprint(scoped)):
            raise WebApiError(403, "remote_agent_scope_changed", "Remote agent workspace is no longer active")
        body = await server._parse_json(request)
        try:
            data = await asyncio.to_thread(execute_remote_tool, profile.remote_workspace, str(body.get("tool") or ""), body.get("arguments"))
        except ValueError as exc:
            raise WebApiError(400, "invalid_remote_tool", str(exc)) from exc
        return _response(data)

    async def connect(request):
        auth = await server._with_capability(request, CAP_MANAGE_BOTS)
        body = await server._parse_json(request)
        result = await asyncio.to_thread(get_remote_workspace_service().connect, auth.user_id, body)
        return _response(result)

    async def directories(request):
        auth = await server._with_capability(request, CAP_MANAGE_BOTS)
        service = get_remote_workspace_service()
        config = service.connection_config(request.match_info["connection_id"], auth.user_id)
        connection = await asyncio.to_thread(service.get, config)
        platform = config.get("platform", "posix")
        target = join_remote_path(config["root"], request.query.get("path") or config["root"], platform)
        browse_root = target[:4] if platform == "windows" else "/"
        result = await asyncio.to_thread(connection.list_directory, target, root=browse_root)
        return _response(result)

    async def reconnect(request):
        auth = await server._with_capability(request, CAP_MANAGE_BOTS)
        profile = get_profile_or_raise(server.manager, server._manager_alias(request))
        if not profile.remote_workspace:
            raise WebApiError(400, "not_remote_workspace", "当前智能体没有远程工作区")
        body = await server._parse_json(request)
        # Reauthentication cannot silently change the host, identity, or root
        # of an existing conversation. Changing targets requires a new agent.
        config = {**profile.remote_workspace}
        for field in ("key_filename", "host_key_fingerprint", "platform"):
            if field in body and body[field] != config.get(field, "posix" if field == "platform" else ""):
                raise WebApiError(409, "remote_connection_bound", "重新登录使用已绑定的主机密钥和私钥路径；更换连接配置请新建智能体")
        for field in ("password", "passphrase"):
            if field in body:
                config[field] = body[field]
        result = await asyncio.to_thread(
            get_remote_workspace_service().connect, auth.user_id, config,
            connection_id=config["connection_id"],
        )
        return _response(result)

    app.router.add_post("/api/remote/connections", connect)
    app.router.add_get("/api/remote/connections/{connection_id}/directories", directories)
    app.router.add_post("/api/bots/{alias}/remote/connect", reconnect)
    app.router.add_post("/api/remote/agent-tools", agent_tools)
