from __future__ import annotations

import asyncio
import json

from aiohttp import web

from bot.language_server.external_source_registry import (
    ExternalSourceError,
    ExternalSourceRegistry,
)
from bot.web.api_common import WebApiError
from bot.web.auth_store import CAP_READ_FILE_CONTENT


_DEFAULT_EXTERNAL_SOURCE_REGISTRY = ExternalSourceRegistry()


def get_external_source_registry(server) -> ExternalSourceRegistry:
    registry = getattr(server, "external_source_registry", None)
    if registry is not None:
        return registry
    return _DEFAULT_EXTERNAL_SOURCE_REGISTRY


def _looks_like_absolute_source_id(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        text.startswith(("/", "\\"))
        or (len(text) >= 3 and text[1] == ":" and text[2] in {"/", "\\"})
        or text.lower().startswith("file:")
    )


def _parse_external_read_query(request: web.Request) -> tuple[str, str, int, str | None]:
    source_id = str(
        request.match_info.get("source_id")
        or request.query.get("source_id")
        or request.query.get("sourceId")
        or ""
    ).strip()
    if not source_id:
        raise WebApiError(400, "missing_source_id", "缺少外部源码 source_id")
    if _looks_like_absolute_source_id(source_id) or "/" in source_id or "\\" in source_id:
        raise WebApiError(400, "external_source_absolute_path", "外部源码只能使用 source_id，不能提交路径")
    mode = str(request.query.get("mode") or "cat").strip().lower()
    raw_lines = str(request.query.get("lines") or ("80" if mode in {"head", "preview"} else "0"))
    try:
        lines = int(raw_lines)
    except ValueError as exc:
        raise WebApiError(400, "external_source_invalid_lines", "外部源码行数无效") from exc
    requested_encoding = request.query.get("encoding") or None
    return source_id, mode, lines, requested_encoding


async def _read_external_source(request: web.Request, server) -> web.Response:
    auth = await server._with_capability(request, CAP_READ_FILE_CONTENT)
    alias = server._manager_alias(request)
    source_id, mode, lines, requested_encoding = _parse_external_read_query(request)
    workspace = server._workspace_file_root(alias, auth)
    provider_id = str(request.query.get("provider") or request.query.get("provider_id") or "").strip().lower() or None
    registry = get_external_source_registry(server)
    try:
        # Older clients only send source_id.  Resolve it inside the trusted
        # registry first, then pass its bound provider back into read() so every
        # request still validates alias/user/workspace/provider scope without
        # requiring a client-supplied provider value.
        if provider_id is None:
            record = await asyncio.to_thread(
                registry.resolve,
                source_id,
                alias=alias,
                user_id=server._chat_user_id(auth),
                workspace_root=workspace,
            )
            provider_id = record.provider_id
        data = await asyncio.to_thread(
            registry.read,
            source_id,
            alias=alias,
            user_id=server._chat_user_id(auth),
            workspace_root=workspace,
            provider_id=provider_id,
            mode=mode,
            lines=lines,
            requested_encoding=requested_encoding,
        )
    except ExternalSourceError as exc:
        raise WebApiError(exc.status, exc.code, exc.message) from exc
    # Keep the ordinary files/read contract: nanosecond timestamps are strings
    # so browser clients do not lose precision when parsing JSON numbers.
    if isinstance(data.get("last_modified_ns"), int):
        data = {**data, "last_modified_ns": str(data["last_modified_ns"])}
    response = web.json_response(
        {"ok": True, "data": data},
        dumps=lambda value: json.dumps(value, ensure_ascii=False),
    )
    response.enable_compression()
    return response


async def _read_file_or_external(request: web.Request, server) -> web.Response:
    has_source_id = bool(
        str(request.match_info.get("source_id") or "").strip()
        or str(request.query.get("source_id") or request.query.get("sourceId") or "").strip()
    )
    if has_source_id:
        return await _read_external_source(request, server)
    return await server.read_file(request)


def register(app: web.Application, server) -> None:
    async def read_file_route(request: web.Request) -> web.Response:
        return await _read_file_or_external(request, server)

    async def external_source_route(request: web.Request) -> web.Response:
        return await _read_external_source(request, server)

    app.router.add_get("/api/language-servers/status", server.get_language_server_catalog)
    app.router.add_post("/api/language-servers/refresh", server.refresh_language_server_catalog)
    app.router.add_get("/api/bots/{alias}/pwd", server.get_pwd)
    app.router.add_get("/api/bots/{alias}/ls", server.get_ls)
    app.router.add_get("/api/bots/{alias}/workspace/quick-open", server.get_workspace_quick_open)
    app.router.add_get("/api/bots/{alias}/workspace/search", server.get_workspace_search)
    app.router.add_get("/api/bots/{alias}/workspace/outline", server.get_workspace_outline)
    app.router.add_get("/api/bots/{alias}/workspace/language-servers", server.get_workspace_language_servers)
    app.router.add_post(
        "/api/bots/{alias}/workspace/language-servers/restart",
        server.post_workspace_language_server_restart,
    )
    app.router.add_post(
        "/api/bots/{alias}/workspace/language-servers/{provider_id}/restart",
        server.post_workspace_language_server_restart,
    )
    app.router.add_get("/api/bots/{alias}/workspace/inline-completion/config", server.get_workspace_inline_completion_config)
    app.router.add_post(
        "/api/bots/{alias}/workspace/resolve-definition",
        server.post_workspace_resolve_definition,
    )
    app.router.add_post(
        "/api/bots/{alias}/workspace/code-navigation/resolve",
        server.post_workspace_code_navigation_resolve,
    )
    app.router.add_post(
        "/api/bots/{alias}/workspace/code-navigation/cancel",
        server.post_workspace_code_navigation_cancel,
    )
    app.router.add_post(
        "/api/bots/{alias}/workspace/code-navigation/documents/sync",
        server.post_workspace_code_navigation_documents_sync,
    )
    app.router.add_post(
        "/api/bots/{alias}/workspace/code-navigation/documents/close",
        server.post_workspace_code_navigation_documents_close,
    )
    app.router.add_post("/api/bots/{alias}/workspace/inline-completion", server.post_workspace_inline_completion)
    app.router.add_post("/api/bots/{alias}/cd", server.post_cd)
    app.router.add_post("/api/bots/{alias}/files/upload", server.upload_file)
    app.router.add_post("/api/bots/{alias}/chat/attachments", server.upload_chat_attachment)
    app.router.add_post("/api/bots/{alias}/chat/attachments/delete", server.delete_chat_attachment_view)
    app.router.add_post("/api/bots/{alias}/files/mkdir", server.create_directory_view)
    app.router.add_post("/api/bots/{alias}/workdir/mkdir", server.create_workdir_directory_view)
    app.router.add_post("/api/bots/{alias}/files/open-workdir", server.open_workdir_view)
    app.router.add_post("/api/bots/{alias}/files/reveal", server.post_files_reveal)
    app.router.add_post("/api/bots/{alias}/files/write", server.write_file_view)
    app.router.add_post("/api/bots/{alias}/files/create", server.create_text_file_view)
    app.router.add_post("/api/bots/{alias}/files/rename", server.rename_path_view)
    app.router.add_post("/api/bots/{alias}/files/copy", server.copy_path_view)
    app.router.add_post("/api/bots/{alias}/files/move", server.move_path_view)
    app.router.add_post("/api/bots/{alias}/files/delete", server.delete_path_view)
    app.router.add_get("/api/bots/{alias}/files/download", server.download_file)
    # External source reads share the existing file endpoint for clients that
    # already know ``files/read``.  The handler ignores ``filename`` whenever
    # source_id is present, so an absolute path can never reach file services.
    app.router.add_get("/api/bots/{alias}/files/read", read_file_route)
    app.router.add_get(
        "/api/bots/{alias}/files/read-external",
        external_source_route,
    )
    app.router.add_get(
        "/api/bots/{alias}/files/external-read",
        external_source_route,
    )
    app.router.add_get(
        "/api/bots/{alias}/workspace/external-sources/{source_id}",
        external_source_route,
    )
    app.router.add_get(
        "/api/bots/{alias}/workspace/external-source/{source_id}",
        external_source_route,
    )
