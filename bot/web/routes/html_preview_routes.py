from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiohttp import web

from bot.web.api_common import WebApiError, get_chat_session_for_alias, get_profile_or_raise
from bot.web.auth_store import CAP_ADMIN_OPS, CAP_READ_FILE_CONTENT
from bot.web.files_service import get_browser_directory, require_real_browser_directory, resolve_safe_path
from bot.web.html_preview_service import (
    HTML_EXTENSIONS, directory_identity, entry_url, inject_bridge, read_resource, resource_prefix,
    security_headers, validate_relative_path,
)


def reject_remote(profile) -> None:
    if profile.remote_workspace:
        raise WebApiError(409, "remote_html_preview_unavailable", "远程工作区不支持本地 HTML 预览")


def _scope(server, alias: str, user_id: int, agent_id: str):
    profile = get_profile_or_raise(server.manager, alias)
    reject_remote(profile)
    profile, agent, session = get_chat_session_for_alias(server.manager, alias, user_id, agent_id)
    if not profile.enabled or profile.archived or not agent.enabled:
        raise WebApiError(410, "preview_scope_changed", "预览工作区已不可用")
    if session.working_dir.startswith(("\\\\", "//")):
        raise WebApiError(400, "unsafe_preview_path", "不允许 UNC 工作区")
    root = os.path.realpath(session.working_dir)
    if root.startswith(("\\\\", "//")):
        raise WebApiError(400, "unsafe_preview_path", "不允许 UNC 工作区")
    try:
        root_stat = os.stat(root)
    except OSError as exc:
        raise WebApiError(410, "preview_scope_changed", "预览工作区已不可用") from exc
    identity = (
        id(profile), session.bot_id, agent.id, id(agent) if agent.id != "main" else None,
        id(session), profile.working_dir, os.path.realpath(profile.working_dir),
        session.working_dir, root, root_stat.st_dev, root_stat.st_ino,
        # Keep identities alive so deleting/recreating a scope cannot reuse its id.
        profile, session, agent if agent.id != "main" else None,
    )
    return identity, root, session


def _entry(root: str, browser_dir: str, filename: str, allow_external: bool) -> tuple[str, str]:
    # Creation accepts the existing admin absolute-path contract. Resource URLs
    # are always relative and deliberately have a stricter grammar.
    normalized = filename.replace("\\", "/")
    if normalized.startswith("//"):
        raise WebApiError(400, "unsafe_preview_path", "不允许 UNC 路径")
    path_components = normalized[3:] if len(normalized) > 2 and normalized[1:3] == ":/" else normalized.lstrip("/")
    validate_relative_path(path_components)
    target = resolve_safe_path(browser_dir, filename, allow_external_paths=allow_external)
    try:
        inside = os.path.commonpath([root, target]) == root
    except ValueError:
        inside = False
    if not inside:
        if not allow_external:
            raise WebApiError(403, "preview_path_forbidden", "文件不在工作区内")
        resolved_parts = Path(target).parts[1:] if Path(target).anchor else Path(target).parts
        validate_relative_path("/".join(resolved_parts))
        root = os.path.dirname(target)
    relative = Path(os.path.relpath(target, root)).as_posix()
    validate_relative_path(relative)
    if Path(relative).suffix.lower() not in HTML_EXTENSIONS:
        raise WebApiError(415, "preview_entry_type", "预览入口必须是 HTML 文件")
    return root, relative


def _base_path(server, request: web.Request) -> str:
    base = server._web_base_path()
    return base if base and request.path.startswith(base + "/") else ""


def is_resource_request(path: str, base: str) -> bool:
    return path.startswith("/api/file-previews/") or bool(base and path.startswith(base + "/api/file-previews/"))


def register(app: web.Application, server) -> None:
    async def create(request: web.Request) -> web.Response:
        alias = server._manager_alias(request)
        # Check workspace kind before capability or any host filesystem access.
        reject_remote(get_profile_or_raise(server.manager, alias))
        auth = await server._with_capability(request, CAP_READ_FILE_CONTENT)
        body = await server._parse_json(request)
        filename = body.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            raise WebApiError(400, "invalid_filename", "请输入 HTML 文件路径")
        agent_id = server._request_agent_id(request)
        identity, workspace, session = _scope(server, alias, auth.user_id, agent_id)
        browser_dir = require_real_browser_directory(get_browser_directory(session))
        root, relative = _entry(workspace, browser_dir, filename, CAP_ADMIN_OPS in auth.capabilities)
        # Verify real size and readability before issuing a ticket.
        await asyncio.to_thread(read_resource, root, relative)
        if _scope(server, alias, auth.user_id, agent_id)[0] != identity:
            raise WebApiError(410, "preview_scope_changed", "预览工作区已改变")
        preview = server.html_preview_store.create(
            owner=(auth.account_id, auth.user_id), alias=alias, agent_id=agent_id,
            identity=identity, root=root, entry_path=relative,
        )
        return web.json_response({"ok": True, "data": {
            "session_id": preview.session_id, "entry_url": entry_url(preview, _base_path(server, request)),
            "entry_path": preview.entry_path, "expires_at": preview.expires_at,
        }})

    async def close(request: web.Request) -> web.Response:
        auth = await server._with_auth(request)
        alias = server._manager_alias(request)
        server.html_preview_store.revoke(
            request.match_info["session_id"], owner=(auth.account_id, auth.user_id),
            alias=alias, agent_id=server._request_agent_id(request),
        )
        return web.json_response({"ok": True})

    async def resource(request: web.Request) -> web.Response:
        preview = server.html_preview_store.get(request.match_info["session_id"])

        def validate_scope() -> None:
            try:
                identity, _, _ = _scope(server, preview.alias, preview.owner[1], preview.agent_id)
                if identity != preview.identity or directory_identity(preview.root) != preview.root_identity:
                    raise WebApiError(410, "preview_scope_changed", "预览工作区已改变")
            except WebApiError as exc:
                server.html_preview_store.invalidate(preview.session_id)
                raise WebApiError(410, "preview_scope_changed", "预览工作区已改变，请重新打开") from exc

        validate_scope()
        data, mime = await asyncio.to_thread(read_resource, preview.root, request.match_info["path"])
        # Revocation, expiration and workspace changes also win over in-flight IO.
        server.html_preview_store.get(preview.session_id)
        validate_scope()
        prefix = resource_prefix(_base_path(server, request), preview.session_id)
        if mime in {"text/html", "application/xhtml+xml"}:
            data = inject_bridge(data, preview, prefix, xhtml=mime == "application/xhtml+xml")
        headers = security_headers(request.host, prefix)
        textual = mime.startswith("text/") or mime in {"application/json", "application/xhtml+xml"}
        response = web.Response(
            body=data if request.method != "HEAD" else b"", content_type=mime,
            charset="utf-8" if textual else None, headers=headers,
        )
        response.headers["Content-Length"] = str(len(data))
        return response

    app.router.add_post("/api/bots/{alias}/files/html-preview", create)
    app.router.add_delete("/api/bots/{alias}/files/html-preview/{session_id}", close)
    app.router.add_get("/api/file-previews/{session_id}/{path:.*}", resource)
