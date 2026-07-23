"""Pyright 的 LSP 初始化、活动文档同步与位置归一化。"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname


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


class PyrightProvider:
    provider_id = "pyright"

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        current_executable: Path | str | None = None,
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
        self.position_encoding = "utf-16"
        self.supports_implementation = False
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

        await client.notify("initialized", {})
        await client.notify(
            "workspace/didChangeConfiguration",
            {"settings": {"python": self._python_settings()}},
        )

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
    ) -> list[dict[str, object]]:
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in {"definition", "implementation"}:
            raise ValueError("代码导航类型无效")
        if normalized_kind == "implementation" and not self.supports_implementation:
            return []

        target = Path(path).expanduser().resolve()
        if not self._is_workspace_python_file(target, language_id):
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
            return self._normalize_locations(response, active_path=target, active_content=str(content))

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
            await client.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": effective_version},
                    "contentChanges": [{"text": content}],
                },
            )
        else:
            effective_version = previous[0]
        self._documents[uri] = (effective_version, content)

    def _is_workspace_python_file(self, path: Path, language_id: str) -> bool:
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            return False
        normalized_language = str(language_id or "").strip().lower()
        return path.suffix.lower() in _PYTHON_EXTENSIONS and (
            not normalized_language or normalized_language in _PYTHON_LANGUAGE_IDS
        )

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
            target = target.resolve()
            try:
                relative = target.relative_to(self.workspace_root)
            except ValueError:
                # 外部源码令牌注册表在阶段 9 接入；在此之前不暴露绝对路径。
                continue
            relative_parts = {part.lower() for part in relative.parts}
            if (
                (relative.parts and relative.parts[0].lower() in {".venv", "venv"})
                or "site-packages" in relative_parts
                or "dist-packages" in relative_parts
            ):
                # 即使虚拟环境位于工作区目录内，它仍是阶段 9 才能开放的
                # 外部依赖源码，不能伪装成可编辑的 workspace 目标。
                continue
            if not target.is_file():
                continue
            target_range = raw.get("targetRange") or raw.get("range")
            selection_range = raw.get("targetSelectionRange") or raw.get("range")
            if not isinstance(target_range, Mapping) or not isinstance(selection_range, Mapping):
                continue
            target_content = active_content if target == active_path else target.read_text(encoding="utf-8", errors="replace")
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
    parsed = urlparse(str(uri or ""))
    if parsed.scheme.lower() != "file":
        return None
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        path = f"//{parsed.netloc}{path}"
    if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)
