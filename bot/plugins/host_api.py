from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.web.workspace_search_service import build_file_outline

from .artifacts import ArtifactStore
from .models import PluginManifest


class PluginHostPermissionError(RuntimeError):
    def __init__(self, permission: str):
        super().__init__(f"permission_denied:{permission}")
        self.permission = permission


def resolve_workspace_path(workspace_root: Path, candidate: str) -> Path:
    root = workspace_root.expanduser().resolve()
    raw = Path(str(candidate or ""))
    resolved = raw.expanduser().resolve() if raw.is_absolute() else (root / raw).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"路径越界: {candidate}")
    return resolved


@dataclass(frozen=True)
class PluginHostContext:
    bot_alias: str
    plugin_id: str
    workspace_root: Path


class PluginHostApi:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts

    def _require(self, allowed: bool, permission: str) -> None:
        if not allowed:
            raise PluginHostPermissionError(permission)

    def _coerce_artifact_bytes(self, params: dict[str, Any]) -> bytes:
        if "contentBase64" in params:
            return base64.b64decode(str(params.get("contentBase64") or "").encode("utf-8"))
        text = params.get("text")
        if text is not None:
            encoding = str(params.get("encoding") or "utf-8")
            return str(text).encode(encoding)
        content = params.get("content")
        if isinstance(content, str):
            encoding = str(params.get("encoding") or "utf-8")
            return content.encode(encoding)
        raise ValueError("artifact 内容不能为空")

    async def dispatch(
        self,
        context: PluginHostContext,
        manifest: PluginManifest,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        permissions = manifest.runtime.permissions
        if method == "host.workspace.read_text":
            self._require(permissions.workspace_read, "workspaceRead")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or ""))
            encoding = str(params.get("encoding") or "utf-8")
            return {
                "path": str(path),
                "content": path.read_text(encoding=encoding),
            }
        if method == "host.workspace.read_bytes":
            self._require(permissions.workspace_read, "workspaceRead")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or ""))
            return {
                "path": str(path),
                "contentBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        if method == "host.workspace.stat":
            self._require(permissions.workspace_read, "workspaceRead")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or ""))
            if not path.exists():
                return {
                    "path": str(path),
                    "exists": False,
                    "isDir": False,
                    "size": 0,
                    "mtimeNs": 0,
                }
            stat = path.stat()
            return {
                "path": str(path),
                "exists": True,
                "isDir": path.is_dir(),
                "size": stat.st_size,
                "mtimeNs": stat.st_mtime_ns,
            }
        if method == "host.workspace.list_dir":
            self._require(permissions.workspace_list, "workspaceList")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or "."))
            entries: list[dict[str, Any]] = []
            for entry in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                stat = entry.stat()
                entries.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "isDir": entry.is_dir(),
                        "size": stat.st_size,
                        "mtimeNs": stat.st_mtime_ns,
                    }
                )
            return {"path": str(path), "entries": entries}
        if method == "host.workspace.outline":
            self._require(permissions.workspace_read, "workspaceRead")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or ""))
            relative_path = path.relative_to(context.workspace_root.expanduser().resolve()).as_posix()
            outline = build_file_outline(context.workspace_root, relative_path)
            return {
                "path": relative_path,
                "items": list(outline.get("items") or []),
            }
        if method == "host.temp.write_artifact":
            self._require(permissions.temp_artifacts, "tempArtifacts")
            record = self.artifacts.write(
                bot_alias=context.bot_alias,
                plugin_id=context.plugin_id,
                filename=str(params.get("filename") or "artifact.bin"),
                content=self._coerce_artifact_bytes(params),
            )
            return {
                "artifactId": record.artifact_id,
                "filename": record.filename,
                "sizeBytes": record.size_bytes,
            }
        raise ValueError(f"unknown host api method: {method}")
