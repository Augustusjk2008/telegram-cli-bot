"""TypeScript / JavaScript 的 LSP 初始化、活动文档同步与位置归一化。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .pyright import (
    LspClientProtocol,
    _POSITION_ENCODINGS,
    _api_position_to_lsp,
    _file_uri_to_path,
    _lsp_range_to_api,
)
from .document_store import LanguageDocument, build_content_change, parse_text_document_sync_capability


_TYPESCRIPT_EXTENSIONS = {".ts", ".tsx", ".mts", ".cts"}
_JAVASCRIPT_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}
_TYPESCRIPT_LANGUAGE_IDS = {"", "typescript", "typescriptreact", "ts", "tsx"}
_JAVASCRIPT_LANGUAGE_IDS = {"", "javascript", "javascriptreact", "js", "jsx"}
_EXTERNAL_DEPENDENCY_PARTS = {"node_modules", ".yarn", ".pnp", ".pnpm"}
_SOURCE_DEFINITION_COMMAND = "_typescript.goToSourceDefinition"
_TSSERVER_REQUEST_COMMAND = "typescript.tsserverRequest"


def discover_project_typescript_sdk(workspace_root: Path | str) -> Path | None:
    """仅接受工作区内标准 ``node_modules/typescript`` SDK，避免符号链接逃逸。"""

    root = Path(workspace_root).expanduser().resolve()
    candidate = _normalize_typescript_sdk_path(root / "node_modules" / "typescript" / "lib" / "tsserver.js")
    if candidate is None:
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _normalize_typescript_sdk_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    candidate = Path(value).expanduser()
    candidates = (
        (candidate / "lib" / "tsserver.js", candidate / "tsserver.js")
        if candidate.is_dir()
        else (candidate,)
    )
    for item in candidates:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if resolved.name == "tsserver.js" and resolved.is_file():
            return resolved
    return None


class TypeScriptProvider:
    provider_id = "typescript"

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        managed_sdk_path: Path | str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.project_sdk_path = discover_project_typescript_sdk(self.workspace_root)
        self.managed_sdk_path = _normalize_typescript_sdk_path(managed_sdk_path)
        self.position_encoding = "utf-16"
        self.supports_implementation = False
        self.supports_source_definition = False
        self.supports_tsserver_request = False
        self.sync_open_close = True
        self.sync_change_kind = 1
        self._documents: dict[str, tuple[int, str]] = {}
        self._navigation_lock = asyncio.Lock()

    @property
    def open_document_count(self) -> int:
        return len(self._documents)

    async def initialize(self, client: LspClientProtocol) -> None:
        root_uri = self.workspace_root.as_uri()
        result = await client.request(
            "initialize",
            {
                "processId": os.getpid(),
                "clientInfo": {"name": "Orbit Safe Claw", "version": "1"},
                "locale": "zh-CN",
                "rootPath": str(self.workspace_root),
                "rootUri": root_uri,
                "workspaceFolders": [{"uri": root_uri, "name": self.workspace_root.name}],
                "initializationOptions": self._initialization_options(),
                "capabilities": {
                    "general": {"positionEncodings": ["utf-16", "utf-8"]},
                    "window": {"workDoneProgress": True},
                    # 不向语言服务器承诺工作区配置读取能力；避免让工作区控制的
                    # 编辑器配置、插件或自动获取策略进入 Orbit 进程。
                    "workspace": {"workspaceFolders": True, "configuration": False},
                    "textDocument": {
                        "definition": {"dynamicRegistration": False, "linkSupport": True},
                        "implementation": {"dynamicRegistration": False, "linkSupport": True},
                        "synchronization": {
                            "dynamicRegistration": False,
                            "didSave": False,
                            "willSave": False,
                            "willSaveWaitUntil": False,
                        },
                    },
                },
            },
        )
        capabilities = result.get("capabilities") if isinstance(result, Mapping) else None
        if not isinstance(capabilities, Mapping):
            capabilities = {}
        encoding = str(capabilities.get("positionEncoding") or "utf-16").strip().lower()
        self.position_encoding = encoding if encoding in _POSITION_ENCODINGS else "utf-16"
        self.supports_implementation = bool(capabilities.get("implementationProvider"))
        self.sync_open_close, self.sync_change_kind = parse_text_document_sync_capability(
            capabilities.get("textDocumentSync")
        )
        execute_commands = capabilities.get("executeCommandProvider")
        commands = execute_commands.get("commands") if isinstance(execute_commands, Mapping) else None
        advertised_commands = (
            {str(command) for command in commands if isinstance(command, str)}
            if isinstance(commands, list)
            else set()
        )
        self.supports_source_definition = _SOURCE_DEFINITION_COMMAND in advertised_commands
        self.supports_tsserver_request = _TSSERVER_REQUEST_COMMAND in advertised_commands
        await client.notify("initialized", {})

    async def sync_documents(
        self,
        client: LspClientProtocol,
        documents: Sequence[LanguageDocument | Mapping[str, Any]],
    ) -> list[LanguageDocument]:
        synced: list[LanguageDocument] = []
        async with self._navigation_lock:
            for raw in documents:
                document = LanguageDocument.from_value(raw)
                target = (self.workspace_root / document.path).resolve()
                if not self._is_workspace_typescript_file(target, document.language_id):
                    continue
                if await self._sync_snapshot(client, document):
                    synced.append(document)
        return synced

    async def replay_documents(
        self,
        client: LspClientProtocol,
        documents: Sequence[LanguageDocument | Mapping[str, Any]],
    ) -> list[LanguageDocument]:
        return await self.sync_documents(client, documents)

    async def close_documents(
        self,
        client: LspClientProtocol,
        documents: Iterable[LanguageDocument | Mapping[str, Any] | str],
    ) -> list[str]:
        closed: list[str] = []
        async with self._navigation_lock:
            for raw in documents:
                if isinstance(raw, str):
                    path = raw.strip().replace("\\", "/")
                elif isinstance(raw, LanguageDocument):
                    path = raw.path
                elif isinstance(raw, Mapping):
                    path = str(raw.get("path") or "").strip().replace("\\", "/")
                else:
                    continue
                if not path:
                    continue
                target = (self.workspace_root / path).resolve()
                try:
                    target.relative_to(self.workspace_root)
                except ValueError:
                    continue
                uri = target.as_uri()
                if self._documents.pop(uri, None) is None:
                    continue
                if self.sync_open_close:
                    await client.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
                closed.append(path)
        return closed

    async def _sync_snapshot(self, client: LspClientProtocol, document: LanguageDocument) -> bool:
        target = (self.workspace_root / document.path).resolve()
        uri = target.as_uri()
        previous = self._documents.get(uri)
        if previous is not None:
            if document.version < previous[0] or (
                document.version == previous[0] and document.content != previous[1]
            ):
                return False
            if document.version == previous[0]:
                return False
            change = build_content_change(
                previous[1], document.content, change_kind=self.sync_change_kind, encoding=self.position_encoding,
            )
            await client.notify(
                "textDocument/didChange",
                {"textDocument": {"uri": uri, "version": document.version}, "contentChanges": [change]},
            )
        elif self.sync_open_close:
            await client.notify(
                "textDocument/didOpen",
                {"textDocument": {
                    "uri": uri,
                    "languageId": self._lsp_language_id(target),
                    "version": document.version,
                    "text": document.content,
                }},
            )
        self._documents[uri] = (document.version, document.content)
        return True

    def _initialization_options(self) -> dict[str, object]:
        tsserver: dict[str, str] = {}
        if self.project_sdk_path is not None:
            tsserver["path"] = str(self.project_sdk_path)
        if self.managed_sdk_path is not None and self.managed_sdk_path != self.project_sdk_path:
            tsserver["fallbackPath"] = str(self.managed_sdk_path)
        return {
            "tsserver": tsserver,
            # typescript-language-server 将此选项传给 tsserver，防止 ATA 在
            # 打开文件或解析 import 时下载 @types 依赖。
            "disableAutomaticTypingAcquisition": True,
            # 仅允许 Orbit 显式给出的固定插件集合；阶段 5 没有受信任插件，
            # 所以绝不从工作区、客户端请求或 tsserver probe path 接受插件。
            "plugins": [],
        }

    def handle_server_request(self, method: str, params: Any) -> Any:
        """拒绝服务端修改请求，并只返回受控的工作区元数据。"""

        if method == "workspace/workspaceFolders":
            return [{"uri": self.workspace_root.as_uri(), "name": self.workspace_root.name}]
        if method == "workspace/configuration":
            items = params.get("items") if isinstance(params, Mapping) else None
            return [{} for _item in items] if isinstance(items, list) else []
        if method == "workspace/applyEdit":
            return {"applied": False}
        if method == "window/showDocument":
            return {"success": False}
        if method in {
            "client/registerCapability",
            "client/unregisterCapability",
            "window/workDoneProgress/create",
            "window/showMessageRequest",
        }:
            return None
        from .jsonrpc import LspJsonRpcServerRequestError

        raise LspJsonRpcServerRequestError(-32601, f"客户端不支持服务端请求: {method}")

    async def navigate(
        self,
        client: LspClientProtocol,
        *,
        kind: str,
        path: Path | str,
        language_id: str,
        version: int,
        content: str,
        line: int,
        column: int,
    ) -> list[dict[str, object]]:
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in {"definition", "implementation"}:
            raise ValueError("代码导航类型无效")
        if normalized_kind == "implementation" and not self.supports_implementation:
            return []

        target = Path(path).expanduser().resolve()
        if not self._is_workspace_typescript_file(target, language_id):
            return []
        text = str(content)
        async with self._navigation_lock:
            uri = target.as_uri()
            await self._sync_active_document(
                client,
                uri=uri,
                language_id=self._lsp_language_id(target),
                version=max(0, int(version)),
                content=text,
            )
            position = _api_position_to_lsp(
                text,
                line=max(1, int(line)),
                column=max(1, int(column)),
                encoding=self.position_encoding,
            )
            if normalized_kind == "definition" and self.supports_source_definition:
                response = await client.request(
                    "workspace/executeCommand",
                    {
                        "command": _SOURCE_DEFINITION_COMMAND,
                        "arguments": [uri, position],
                    },
                )
            else:
                if normalized_kind == "implementation" and self.supports_tsserver_request:
                    await self._prime_project(client, uri)
                response = await client.request(
                    f"textDocument/{normalized_kind}",
                    {
                        "textDocument": {"uri": uri},
                        "position": position,
                    },
                )
            return self._normalize_locations(response, active_path=target, active_content=text)

    async def _prime_project(self, client: LspClientProtocol, uri: str) -> None:
        """让 tsserver 完成 configured/inferred project 装载后再查询实现。"""

        try:
            await client.request(
                "workspace/executeCommand",
                {
                    "command": _TSSERVER_REQUEST_COMMAND,
                    "arguments": [
                        "projectInfo",
                        {"file": uri, "needFileNameList": False},
                        {},
                    ],
                },
            )
        except Exception:
            # 预热命令是 TypeScript Language Server 扩展；即使某个兼容服务
            # 声明后拒绝它，仍继续使用标准 implementation 请求。
            return

    async def _sync_active_document(
        self,
        client: LspClientProtocol,
        *,
        uri: str,
        language_id: str,
        version: int,
        content: str,
    ) -> None:
        previous = self._documents.get(uri)
        if previous is None:
            effective_version = version
            await client.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": language_id,
                        "version": version,
                        "text": content,
                    }
                },
            )
        elif previous[1] != content:
            effective_version = max(version, previous[0] + 1)
            change = build_content_change(
                previous[1], content, change_kind=self.sync_change_kind, encoding=self.position_encoding,
            )
            await client.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": effective_version},
                    "contentChanges": [change],
                },
            )
        else:
            effective_version = previous[0]
        self._documents[uri] = (effective_version, content)

    def _is_workspace_typescript_file(self, path: Path, language_id: str) -> bool:
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            return False
        normalized_language = str(language_id or "").strip().lower()
        suffix = path.suffix.lower()
        if suffix in _TYPESCRIPT_EXTENSIONS:
            return normalized_language in _TYPESCRIPT_LANGUAGE_IDS
        if suffix in _JAVASCRIPT_EXTENSIONS:
            return normalized_language in _JAVASCRIPT_LANGUAGE_IDS
        return False

    @staticmethod
    def _lsp_language_id(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".tsx":
            return "typescriptreact"
        if suffix == ".jsx":
            return "javascriptreact"
        return "typescript" if suffix in _TYPESCRIPT_EXTENSIONS else "javascript"

    def _normalize_locations(
        self,
        response: Any,
        *,
        active_path: Path,
        active_content: str,
    ) -> list[dict[str, object]]:
        if response is None:
            return []
        raw_items = response if isinstance(response, list) else [response]
        items: list[dict[str, object]] = []
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                continue
            uri = str(raw.get("targetUri") or raw.get("uri") or "").strip()
            target = _file_uri_to_path(uri)
            if target is None:
                continue
            try:
                target = target.resolve()
                relative = target.relative_to(self.workspace_root)
            except (OSError, ValueError):
                # 外部源码令牌注册表在阶段 9 接入；在此之前不暴露绝对路径。
                continue
            if any(part.lower() in _EXTERNAL_DEPENDENCY_PARTS for part in relative.parts):
                continue
            target_range = raw.get("targetRange") or raw.get("range")
            selection_range = raw.get("targetSelectionRange") or raw.get("range")
            if not isinstance(target_range, Mapping) or not isinstance(selection_range, Mapping):
                continue
            snapshot = self._documents.get(target.as_uri())
            if target == active_path:
                target_content = active_content
            elif snapshot is not None:
                target_content = snapshot[1]
            elif target.is_file():
                try:
                    target_content = target.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
            else:
                continue
            normalized_range = _lsp_range_to_api(target_content, target_range, self.position_encoding)
            normalized_selection = _lsp_range_to_api(target_content, selection_range, self.position_encoding)
            if normalized_range is None or normalized_selection is None:
                continue
            items.append(
                {
                    "target_type": "workspace",
                    "path": relative.as_posix(),
                    "provider": self.provider_id,
                    "range": normalized_range,
                    "selection_range": normalized_selection,
                }
            )
        return items
