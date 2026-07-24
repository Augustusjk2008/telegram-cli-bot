"""clangd 的 C/C++ LSP 初始化、工程配置与语义导航。"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
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
from .external_source_registry import (
    ApprovedRoot,
    ExternalSourceError,
    ExternalSourceRegistry,
    canonicalize_approved_roots,
)


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


def _compile_command_arguments(value: Mapping[str, Any]) -> list[str]:
    arguments = value.get("arguments")
    if isinstance(arguments, list):
        return [str(item) for item in arguments if str(item or "").strip()]
    command = str(value.get("command") or "").strip()
    if not command:
        return []
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return []


def _compile_command_include_args(arguments: Sequence[str]) -> list[str]:
    roots: list[str] = []
    index = 0
    while index < len(arguments):
        argument = str(arguments[index] or "").strip()
        index += 1
        normalized = argument.lower()
        matched = False
        for prefix in ("/external:i", "-isystem", "-iquote"):
            if normalized == prefix:
                if index < len(arguments):
                    roots.append(str(arguments[index]).strip().strip('"'))
                    index += 1
                matched = True
                break
            if normalized.startswith(prefix + "="):
                roots.append(argument[len(prefix) + 1 :].strip().strip('"'))
                matched = True
                break
            if normalized.startswith(prefix):
                roots.append(argument[len(prefix) :].strip().strip('"'))
                matched = True
                break
        if matched:
            continue
        if argument == "-I":
            if index < len(arguments):
                roots.append(str(arguments[index]).strip().strip('"'))
                index += 1
            continue
        if argument.startswith("-I") and len(argument) > 2:
            roots.append(argument[2:].strip().strip('"'))
            continue
        if normalized == "/i":
            if index < len(arguments):
                roots.append(str(arguments[index]).strip().strip('"'))
                index += 1
            continue
        if normalized.startswith("/i") and len(argument) > 2:
            roots.append(argument[2:].strip().strip('"'))
    return [item for item in roots if item]


def discover_clangd_external_roots(
    workspace_root: Path | str,
    *,
    compilation_database: Path | str | None = None,
    compiler_include_roots: Iterable[Path | str] = (),
    clang_resource_dirs: Iterable[Path | str] = (),
    trusted_compiler_commands: Iterable[Path | str] = (),
) -> tuple[ApprovedRoot, ...]:
    """Discover include roots without executing workspace-controlled commands."""

    root = Path(workspace_root).expanduser().resolve()
    candidates: list[tuple[Path, str]] = []
    database = Path(compilation_database).expanduser().resolve() if compilation_database else discover_compile_commands(root)
    if database is not None and database.is_file():
        try:
            raw = json.loads(database.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = []
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, Mapping):
                    continue
                base = Path(str(entry.get("directory") or database.parent)).expanduser()
                if not base.is_absolute():
                    base = database.parent / base
                base = base.resolve(strict=False)
                for include in _compile_command_include_args(_compile_command_arguments(entry)):
                    candidate = Path(include).expanduser()
                    if not candidate.is_absolute():
                        candidate = base / candidate
                    candidates.append((candidate, "compile-command-include"))

    for value in compiler_include_roots:
        candidates.append((Path(value), "compiler-system-include"))
    include_env = str(os.environ.get("INCLUDE") or "").strip()
    if include_env:
        candidates.extend((Path(item), "windows-include") for item in include_env.split(os.pathsep) if item.strip())

    for value in clang_resource_dirs:
        candidates.append((Path(value), "clang-resource"))

    # These are fixed system locations; no compiler from a project command is executed.
    if os.name != "nt":
        for value in ("/usr/include", "/usr/local/include", "/opt/local/include"):
            candidates.append((Path(value), "compiler-system-include"))
    executables: list[str] = [str(value) for value in trusted_compiler_commands if str(value or "").strip()]
    executables.extend(
        executable
        for executable_name in ("clang", "clang++", "gcc", "g++")
        if (executable := shutil.which(executable_name))
    )
    seen_executables: set[str] = set()
    for executable in executables:
        compiler = Path(executable).expanduser()
        if not compiler.is_absolute():
            resolved_executable = shutil.which(str(compiler))
            if not resolved_executable:
                continue
            compiler = Path(resolved_executable)
        try:
            compiler = compiler.resolve(strict=False)
        except OSError:
            continue
        executable_key = os.path.normcase(str(compiler))
        if executable_key in seen_executables:
            continue
        seen_executables.add(executable_key)
        candidates.append((compiler.parent.parent / "include", "compiler-system-include"))
        clang_lib = compiler.parent.parent / "lib" / "clang"
        if clang_lib.is_dir():
            try:
                candidates.extend((item / "include", "clang-resource") for item in clang_lib.iterdir() if item.is_dir())
            except OSError:
                pass
    return canonicalize_approved_roots(candidates)


class ClangdProvider:
    provider_id = "clangd"

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        runtime_cache_dir: Path | str | None = None,
        external_source_registry: ExternalSourceRegistry | None = None,
        source_registry: ExternalSourceRegistry | None = None,
        bot_alias: str = "",
        user_id: int = 0,
        source_context: Mapping[str, Any] | None = None,
        compiler_include_roots: Iterable[Path | str] = (),
        clang_resource_dirs: Iterable[Path | str] = (),
        trusted_compiler_commands: Iterable[Path | str] = (),
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.compilation_database = discover_compile_commands(self.workspace_root)
        self.compile_commands_dir = (
            self.compilation_database.parent if self.compilation_database is not None else None
        )
        self.project_config = discover_clangd_project_config(self.workspace_root)
        self.external_source_registry = (
            external_source_registry if external_source_registry is not None else source_registry
        )
        context = source_context if isinstance(source_context, Mapping) else {}
        self.external_source_alias = str(bot_alias or context.get("bot_alias") or context.get("alias") or "").strip().lower()
        try:
            self.external_source_user_id = int(user_id if user_id is not None else context.get("user_id") or 0)
        except (TypeError, ValueError):
            self.external_source_user_id = 0
        self.external_source_roots = discover_clangd_external_roots(
            self.workspace_root,
            compilation_database=self.compilation_database,
            compiler_include_roots=compiler_include_roots,
            clang_resource_dirs=clang_resource_dirs,
            trusted_compiler_commands=trusted_compiler_commands,
        )
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

    def set_external_source_context(self, *, alias: str, user_id: int) -> None:
        self.external_source_alias = str(alias or "").strip().lower()
        self.external_source_user_id = int(user_id)

    def approved_external_roots(self) -> tuple[ApprovedRoot, ...]:
        return self.external_source_roots

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

    async def close_external_sources(
        self,
        client: LspClientProtocol,
        source_ids: Iterable[str],
    ) -> list[str]:
        closed: list[str] = []
        async with self._navigation_lock:
            for raw_source_id in source_ids:
                source_id = str(raw_source_id or "").strip()
                record = self._resolve_external_source_id(source_id)
                if record is None:
                    continue
                uri = record.path.as_uri()
                if self._documents.pop(uri, None) is None:
                    continue
                if self.sync_open_close:
                    await client.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
                closed.append(source_id)
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
        source_id: str = "",
    ) -> list[dict[str, object]]:
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in {"definition", "implementation"}:
            raise ValueError("代码导航类型无效")
        if normalized_kind == "implementation" and not self.supports_implementation:
            return []
        target = Path(path).expanduser().resolve()
        active_source_id = str(source_id or "").strip()
        if not self._is_workspace_clang_file(target, language_id) and not self._is_registered_external_source(
            active_source_id,
            target,
            language_id,
        ):
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
            return self._normalize_locations(
                response,
                active_path=target,
                active_content=text,
                active_source_id=active_source_id,
            )

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

    def _is_registered_external_source(self, source_id: str, target: Path, language_id: str) -> bool:
        if str(language_id or "").strip().lower() not in _CLANGD_LANGUAGE_IDS:
            return False
        return self._resolve_registered_external_source(source_id, target) is not None

    @staticmethod
    def _lsp_language_id(path: Path) -> str:
        return "c" if path.suffix.lower() == ".c" else "cpp"

    def _normalize_locations(
        self,
        response: Any,
        *,
        active_path: Path,
        active_content: str,
        active_source_id: str = "",
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
                relative = None
            target_range = raw.get("targetRange") or raw.get("range")
            selection_range = raw.get("targetSelectionRange") or raw.get("range")
            if not isinstance(target_range, Mapping) or not isinstance(selection_range, Mapping):
                continue
            source_record = None
            if relative is None:
                source_record = (
                    self._resolve_registered_external_source(active_source_id, target)
                    if active_source_id and target == active_path
                    else self._register_external_source(uri)
                )
                if source_record is None:
                    continue
                if target == active_path and source_record.source_id == active_source_id:
                    target_content = active_content
                else:
                    target_content = self.external_source_registry.read(
                        source_record.source_id,
                        alias=self.external_source_alias,
                        user_id=self.external_source_user_id,
                        workspace_root=self.workspace_root,
                        provider_id=self.provider_id,
                        mode="cat",
                    )["content"]
                if not isinstance(target_content, str):
                    continue
            else:
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
            if source_record is not None:
                items.append(
                    {
                        "target_type": "external",
                        "path": source_record.display_path,
                        "display_path": source_record.display_path,
                        "source_id": source_record.source_id,
                        "provider": self.provider_id,
                        "range": normalized_range,
                        "selection_range": normalized_selection,
                    }
                )
            else:
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

    def _register_external_source(self, uri: str):
        registry = self.external_source_registry
        if registry is None or not self.external_source_alias:
            return None
        return registry.register(
            uri=uri,
            alias=self.external_source_alias,
            user_id=self.external_source_user_id,
            workspace_root=self.workspace_root,
            provider_id=self.provider_id,
            approved_roots=self.external_source_roots,
        )

    def _resolve_registered_external_source(self, source_id: str, target: Path):
        record = self._resolve_external_source_id(source_id)
        return record if record is not None and record.path == target else None

    def _resolve_external_source_id(self, source_id: str):
        registry = self.external_source_registry
        if registry is None or not self.external_source_alias or not source_id:
            return None
        try:
            record = registry.resolve(
                source_id,
                alias=self.external_source_alias,
                user_id=self.external_source_user_id,
                workspace_root=self.workspace_root,
                provider_id=self.provider_id,
            )
        except ExternalSourceError:
            return None
        return record
