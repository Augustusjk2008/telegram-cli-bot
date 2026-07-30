"""Pyright 的 LSP 初始化、活动文档同步与位置归一化。"""

from __future__ import annotations

import asyncio
import os
import sys
import sysconfig
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .document_store import (
    LanguageDocument,
    build_content_change,
    parse_text_document_sync_capability,
)
from .external_source_registry import (
    ApprovedRoot,
    ExternalSourceError,
    ExternalSourceRegistry,
    ExternalSourceUriError,
    canonicalize_approved_roots,
)


_PYTHON_EXTENSIONS = {".py", ".pyi"}
_PYTHON_LANGUAGE_IDS = {"python", "py"}
_POSITION_ENCODINGS = {"utf-8", "utf-16"}


class LspClientProtocol(Protocol):
    async def request(self, method: str, params: dict[str, Any]) -> Any: ...

    async def notify(self, method: str, params: dict[str, Any]) -> None: ...


def discover_python_interpreter(
    workspace_root: Path | str,
    *,
    current_executable: Path | str | None = None,
) -> Path | None:
    """按工作区虚拟环境优先级选择 Pyright 使用的解释器。"""

    root = Path(workspace_root).expanduser().resolve()
    environments = [root / ".venv", root / "venv"]
    if (root / "pyvenv.cfg").is_file():
        environments.insert(0, root)
    for environment in environments:
        for relative in (Path("Scripts/python.exe"), Path("bin/python3"), Path("bin/python")):
            candidate = environment / relative
            if candidate.is_file():
                return candidate.resolve()

    fallback = Path(current_executable or sys.executable).expanduser()
    return fallback.resolve() if fallback.is_file() else None


def discover_python_external_roots(
    interpreter: Path | str | None,
    *,
    typeshed_roots: Iterable[Path | str] = (),
) -> tuple[ApprovedRoot, ...]:
    """Return only canonical Python dependency roots suitable for read-only source."""

    candidates: list[tuple[Path, str]] = []
    selected: Path | None = None
    selected_prefix: Path | None = None
    if interpreter is not None:
        try:
            candidate = Path(interpreter).expanduser().resolve()
            if candidate.is_file():
                selected = candidate
        except OSError:
            selected = None
    if selected is not None:
        prefix = selected.parent.parent if selected.parent.name.lower() in {"scripts", "bin"} else selected.parent
        selected_prefix = prefix.resolve(strict=False)
        candidates.append((prefix, "python-prefix"))
        candidates.extend(
            (
                (prefix / "Lib", "python-stdlib"),
                (prefix / "Lib" / "site-packages", "python-site-packages"),
                (prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}", "python-stdlib"),
                (prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages", "python-site-packages"),
            )
        )
    host_prefixes = {
        Path(sys.prefix).expanduser().resolve(strict=False),
        Path(sys.base_prefix).expanduser().resolve(strict=False),
    }
    if selected_prefix is None or selected_prefix in host_prefixes:
        for name, label in (
            ("stdlib", "python-stdlib"),
            ("platstdlib", "python-stdlib"),
            ("purelib", "python-site-packages"),
            ("platlib", "python-site-packages"),
        ):
            value = sysconfig.get_path(name)
            if value:
                candidates.append((Path(value), label))
    for value in typeshed_roots:
        candidates.append((Path(value), "pyright-typeshed"))
    # Pyright packages typeshed differently across managed and PATH installs.
    # Probe only fixed, trusted installation layouts; never recursively search a workspace.
    prefixes = {selected_prefix} if selected_prefix is not None else host_prefixes
    for prefix in prefixes:
        candidates.extend(
            (
                (prefix / "typeshed", "pyright-typeshed"),
                (prefix / "typeshed-fallback", "pyright-typeshed"),
                (prefix / "lib" / "node_modules" / "pyright" / "dist" / "typeshed-fallback", "pyright-typeshed"),
                (prefix / "lib" / "node_modules" / "pyright-internal" / "typeshed-fallback", "pyright-typeshed"),
            )
        )
    return canonicalize_approved_roots(candidates)


def discover_pyright_typeshed_roots(command: Sequence[str] = ()) -> tuple[Path, ...]:
    """Find typeshed beside a trusted Pyright command without scanning a workspace."""

    candidates: list[Path] = []
    for value in command:
        try:
            entry = Path(str(value or "")).expanduser()
        except (TypeError, ValueError):
            continue
        if not entry.is_file():
            continue
        try:
            entry = entry.resolve()
        except OSError:
            continue
        parents = (entry.parent, entry.parent.parent, entry.parent.parent.parent)
        for parent in parents:
            candidates.extend(
                (
                    parent / "typeshed-fallback",
                    parent / "dist" / "typeshed-fallback",
                    parent / "pyright" / "dist" / "typeshed-fallback",
                )
            )
    roots = canonicalize_approved_roots((item, "pyright-typeshed") for item in candidates)
    return tuple(item.path for item in roots)


class PyrightProvider:
    provider_id = "pyright"

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        current_executable: Path | str | None = None,
        external_source_registry: ExternalSourceRegistry | None = None,
        source_registry: ExternalSourceRegistry | None = None,
        bot_alias: str = "",
        user_id: int = 0,
        source_context: Mapping[str, Any] | None = None,
        typeshed_roots: Iterable[Path | str] = (),
        pyright_command: Sequence[str] = (),
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.discovered_python_interpreter = discover_python_interpreter(
            self.workspace_root,
            current_executable=current_executable,
        )
        # A workspace-controlled virtualenv executable is untrusted input.  Merely
        # pointing Pyright at it can cause the language server to execute it while
        # probing search paths.  Discover it for status/future approval, but only
        # configure the interpreter already running Orbit (or an explicitly
        # injected equivalent in tests), which is inside the existing trust boundary.
        trusted_interpreter = Path(current_executable or sys.executable).expanduser()
        self.python_interpreter = trusted_interpreter.resolve() if trusted_interpreter.is_file() else None
        self.external_source_registry = (
            external_source_registry if external_source_registry is not None else source_registry
        )
        context = source_context if isinstance(source_context, Mapping) else {}
        self.external_source_alias = str(bot_alias or context.get("bot_alias") or context.get("alias") or "").strip().lower()
        try:
            self.external_source_user_id = int(user_id if user_id is not None else context.get("user_id") or 0)
        except (TypeError, ValueError):
            self.external_source_user_id = 0
        self.external_source_roots = discover_python_external_roots(
            self.discovered_python_interpreter or self.python_interpreter,
            typeshed_roots=(*typeshed_roots, *discover_pyright_typeshed_roots(pyright_command)),
        )
        self.position_encoding = "utf-16"
        self.supports_implementation = False
        self.sync_open_close = True
        self.sync_change_kind = 1
        self._documents: dict[str, tuple[int, str]] = {}
        self._navigation_lock = asyncio.Lock()

    @property
    def open_document_count(self) -> int:
        return len(self._documents)

    def set_external_source_context(self, *, alias: str, user_id: int) -> None:
        self.external_source_alias = str(alias or "").strip().lower()
        self.external_source_user_id = int(user_id)

    def approved_external_roots(self) -> tuple[ApprovedRoot, ...]:
        return self.external_source_roots

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
                "capabilities": {
                    "general": {"positionEncodings": ["utf-16", "utf-8"]},
                    "window": {"workDoneProgress": True},
                    # Pyright consumes the explicit didChangeConfiguration payload below.
                    # Advertising dynamic configuration without serving its values would
                    # make Pyright replace the selected interpreter with null settings.
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
        await client.notify(
            "workspace/didChangeConfiguration",
            {"settings": {"python": self._python_settings()}},
        )

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
                if not self._is_workspace_python_file(target, document.language_id):
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
                previous[1],
                document.content,
                change_kind=self.sync_change_kind,
                encoding=self.position_encoding,
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
                    "languageId": document.language_id,
                    "version": document.version,
                    "text": document.content,
                }},
            )
        self._documents[uri] = (document.version, document.content)
        return True

    def handle_server_request(self, method: str, params: Any) -> Any:
        """Answer the small set of workspace/client requests Pyright may issue."""

        if method == "workspace/workspaceFolders":
            return [{"uri": self.workspace_root.as_uri(), "name": self.workspace_root.name}]
        if method == "workspace/configuration":
            items = params.get("items") if isinstance(params, Mapping) else None
            if not isinstance(items, list):
                return []
            python_settings = self._python_settings()
            answers: list[Any] = []
            for item in items:
                section = str(item.get("section") or "") if isinstance(item, Mapping) else ""
                if section == "python":
                    answers.append(python_settings)
                elif section == "python.analysis":
                    answers.append(dict(python_settings["analysis"]))
                elif section in {"", "pyright"}:
                    answers.append({"python": python_settings} if not section else {})
                else:
                    answers.append(None)
            return answers
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

    def _python_settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = {
            "analysis": {
                "diagnosticMode": "openFilesOnly",
                "autoSearchPaths": True,
                "useLibraryCodeForTypes": True,
            }
        }
        if self.python_interpreter is not None:
            settings["pythonPath"] = str(self.python_interpreter)
        return settings

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
        if not self._is_workspace_python_file(target, language_id) and not self._is_registered_external_source(
            active_source_id,
            target,
            language_id,
        ):
            return []
        async with self._navigation_lock:
            uri = target.as_uri()
            await self._sync_active_document(
                client,
                uri=uri,
                language_id="python",
                version=max(0, int(version)),
                content=str(content),
            )
            method = f"textDocument/{normalized_kind}"
            response = await client.request(
                method,
                {
                    "textDocument": {"uri": uri},
                    "position": _api_position_to_lsp(
                        str(content),
                        line=max(1, int(line)),
                        column=max(1, int(column)),
                        encoding=self.position_encoding,
                    ),
                },
            )
            return self._normalize_locations(
                response,
                active_path=target,
                active_content=str(content),
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

    def _is_workspace_python_file(self, path: Path, language_id: str) -> bool:
        try:
            relative = path.relative_to(self.workspace_root)
        except ValueError:
            return False
        normalized_language = str(language_id or "").strip().lower()
        relative_parts = {part.lower() for part in relative.parts}
        if (
            (relative.parts and relative.parts[0].lower() in {".venv", "venv"})
            or "site-packages" in relative_parts
            or "dist-packages" in relative_parts
        ):
            return False
        return path.suffix.lower() in _PYTHON_EXTENSIONS and (
            not normalized_language or normalized_language in _PYTHON_LANGUAGE_IDS
        )

    def _is_registered_external_source(self, source_id: str, target: Path, language_id: str) -> bool:
        if target.suffix.lower() not in _PYTHON_EXTENSIONS:
            return False
        normalized_language = str(language_id or "").strip().lower()
        if normalized_language and normalized_language not in _PYTHON_LANGUAGE_IDS:
            return False
        return self._resolve_registered_external_source(source_id, target) is not None

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
            except (OSError, RuntimeError):
                continue
            try:
                relative = target.relative_to(self.workspace_root)
            except ValueError:
                relative = None
            relative_parts = {part.lower() for part in relative.parts} if relative is not None else set()
            is_workspace_dependency = relative is not None and (
                (relative.parts and relative.parts[0].lower() in {".venv", "venv"})
                or "site-packages" in relative_parts
                or "dist-packages" in relative_parts
            )
            target_range = raw.get("targetRange") or raw.get("range")
            selection_range = raw.get("targetSelectionRange") or raw.get("range")
            if not isinstance(target_range, Mapping) or not isinstance(selection_range, Mapping):
                continue
            source_record = None
            if relative is None or is_workspace_dependency:
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
                    target_content = target.read_text(encoding="utf-8", errors="replace")
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


def _api_position_to_lsp(content: str, *, line: int, column: int, encoding: str) -> dict[str, int]:
    lines = content.splitlines()
    line_index = max(0, int(line) - 1)
    line_text = lines[line_index] if line_index < len(lines) else ""
    codepoint_index = min(max(0, int(column) - 1), len(line_text))
    prefix = line_text[:codepoint_index]
    character = _text_units(prefix, encoding)
    return {"line": line_index, "character": character}


def _lsp_range_to_api(
    content: str,
    value: Mapping[str, Any],
    encoding: str,
) -> dict[str, dict[str, int]] | None:
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        return None
    return {
        "start": _lsp_position_to_api(content, start, encoding),
        "end": _lsp_position_to_api(content, end, encoding),
    }


def _lsp_position_to_api(content: str, value: Mapping[str, Any], encoding: str) -> dict[str, int]:
    try:
        line_index = max(0, int(value.get("line") or 0))
        character = max(0, int(value.get("character") or 0))
    except (TypeError, ValueError):
        line_index = 0
        character = 0
    lines = content.splitlines()
    line_text = lines[line_index] if line_index < len(lines) else ""
    codepoint_index = _units_to_codepoint_index(line_text, character, encoding)
    return {"line": line_index + 1, "column": codepoint_index + 1}


def _text_units(value: str, encoding: str) -> int:
    if encoding == "utf-8":
        return len(value.encode("utf-8"))
    return len(value.encode("utf-16-le")) // 2


def _units_to_codepoint_index(value: str, units: int, encoding: str) -> int:
    consumed = 0
    for index, character in enumerate(value):
        next_consumed = consumed + _text_units(character, encoding)
        if next_consumed > units:
            return index
        consumed = next_consumed
        if consumed == units:
            return index + 1
    return len(value)


def _file_uri_to_path(uri: str) -> Path | None:
    value = str(uri or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() != "file":
        raise ExternalSourceUriError("外部源码 URI 不受支持，仅支持 file://")
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path = f"//{parsed.netloc}{path}"
    if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)
