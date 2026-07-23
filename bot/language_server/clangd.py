"""clangd 的 C/C++ LSP 初始化、工程配置与语义导航。"""

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


_CLANGD_EXTENSIONS = {
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hh",
    ".hpp",
    ".hxx",
}
_CLANGD_LANGUAGE_IDS = {"", "c", "cpp", "c++"}
_DEFAULT_FALLBACK_FLAGS = ("-std=c++17",)
_UNSAFE_COMMAND_ARGUMENT_PREFIXES = ("--query-driver",)
_COMMON_BUILD_DIRECTORIES = (
    "build",
    "out",
    ".build",
    "cmake-build-debug",
    "cmake-build-release",
    "build-debug",
    "build-release",
)
_COMMON_BUILD_CONFIGURATIONS = ("debug", "release", "relwithdebinfo", "minsizerel")


def discover_compile_commands(workspace_root: Path | str) -> Path | None:
    """Find a compilation database without recursively scanning user files."""

    root = Path(workspace_root).expanduser().resolve()
    candidates: list[Path] = [root / "compile_commands.json"]
    for directory in _COMMON_BUILD_DIRECTORIES:
        base = root / directory
        candidates.append(base / "compile_commands.json")
        candidates.extend(
            base / configuration / "compile_commands.json"
            for configuration in _COMMON_BUILD_CONFIGURATIONS
        )
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    return None


def discover_clangd_project_config(workspace_root: Path | str) -> Path | None:
    """Return the first supported root-level clangd configuration file."""

    root = Path(workspace_root).expanduser().resolve()
    for name in (".clangd", "compile_flags.txt"):
        candidate = root / name
        if candidate.is_file():
            return candidate.resolve()
    return None


class ClangdProvider:
    provider_id = "clangd"

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        runtime_cache_dir: Path | str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.compilation_database = discover_compile_commands(self.workspace_root)
        self.compile_commands_dir = (
            self.compilation_database.parent if self.compilation_database is not None else None
        )
        self.project_config = discover_clangd_project_config(self.workspace_root)
        self.using_fallback_flags = (
            self.compilation_database is None and self.project_config is None
        )
        self.fallback_flags = list(_DEFAULT_FALLBACK_FLAGS if self.using_fallback_flags else ())
        self.position_encoding = "utf-16"
        self.supports_implementation = False
        self.sync_open_close = True
        self.sync_change_kind = 1
        self._documents: dict[str, tuple[int, str]] = {}
        self._navigation_lock = asyncio.Lock()
        self.runtime_cache_dir: Path | None = None
        if runtime_cache_dir is not None:
            try:
                cache = Path(runtime_cache_dir).expanduser().resolve()
                cache.mkdir(parents=True, exist_ok=True)
                self.runtime_cache_dir = cache
            except OSError:
                # clangd still works with its normal cache policy; the runtime
                # never writes a fallback cache into the repository.
                self.runtime_cache_dir = None

    @property
    def open_document_count(self) -> int:
        return len(self._documents)

    @property
    def configuration_summary(self) -> str:
        if self.compilation_database is not None:
            return f"compile_commands.json: {self.compilation_database.parent.name or '.'}"
        if self.project_config is not None:
            return self.project_config.name
        return "fallback flags"

    def prepare_command(self, command: tuple[str, ...]) -> tuple[str, ...]:
        """Add only provider-owned flags to the trusted catalog command."""

        # clangd speaks LSP over stdio by default.  Older local configurations
        # may still carry the removed ``--stdio`` switch, so drop it rather
        # than making a valid clangd installation fail during initialization.
        args = [
            argument
            for index, argument in enumerate(command)
            if index == 0 or argument != "--stdio"
        ]
        for argument in args[1:]:
            normalized = str(argument).strip().lower()
            if any(
                normalized == prefix or normalized.startswith(f"{prefix}=")
                for prefix in _UNSAFE_COMMAND_ARGUMENT_PREFIXES
            ):
                raise ValueError("clangd 不允许使用 --query-driver")
        if not any(arg == "--background-index" or arg.startswith("--background-index=") for arg in args):
            args.append("--background-index")
        if not any(arg.startswith("--background-index-priority") for arg in args):
            args.append("--background-index-priority=background")
        if self.compile_commands_dir is not None and not any(
            arg.startswith("--compile-commands-dir") for arg in args
        ):
            args.append(f"--compile-commands-dir={self.compile_commands_dir}")
        return tuple(args)

    def process_environment(self) -> dict[str, str] | None:
        """Keep clangd's persistent index under the per-runtime data root."""

        if self.runtime_cache_dir is None:
            return None
        environment = os.environ.copy()
        environment["XDG_CACHE_HOME"] = str(self.runtime_cache_dir)
        environment["LOCALAPPDATA"] = str(self.runtime_cache_dir)
        return environment

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
                "initializationOptions": {"fallbackFlags": list(self.fallback_flags)},
                "capabilities": {
                    "general": {"positionEncodings": ["utf-16", "utf-8"]},
                    "window": {"workDoneProgress": True},
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
                if not self._is_workspace_clang_file(target, document.language_id):
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

    def handle_server_request(self, method: str, params: Any) -> Any:
        """Answer harmless workspace requests and reject edits/config injection."""

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
        if not self._is_workspace_clang_file(target, language_id):
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
            response = await client.request(
                f"textDocument/{normalized_kind}",
                {
                    "textDocument": {"uri": uri},
                    "position": _api_position_to_lsp(
                        text,
                        line=max(1, int(line)),
                        column=max(1, int(column)),
                        encoding=self.position_encoding,
                    ),
                },
            )
            return self._normalize_locations(response, active_path=target, active_content=text)

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

    def _is_workspace_clang_file(self, path: Path, language_id: str) -> bool:
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            return False
        return (
            path.suffix.lower() in _CLANGD_EXTENSIONS
            and str(language_id or "").strip().lower() in _CLANGD_LANGUAGE_IDS
        )

    @staticmethod
    def _lsp_language_id(path: Path) -> str:
        return "c" if path.suffix.lower() == ".c" else "cpp"

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
                # External dependency source tokens are introduced in stage 9.
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
