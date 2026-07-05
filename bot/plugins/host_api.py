from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.web.workspace_search_service import build_file_outline, normalize_workspace_path_input

from .artifacts import ArtifactStore
from .models import PluginHostLimits, PluginManifest


class PluginHostPermissionError(RuntimeError):
    def __init__(self, permission: str):
        super().__init__(f"permission_denied:{permission}")
        self.permission = permission


def resolve_workspace_path(workspace_root: Path, candidate: str) -> Path:
    root = workspace_root.expanduser().resolve()
    raw = Path(normalize_workspace_path_input(str(candidate or "")))
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

    def _ensure_regular_file_within_limit(self, path: Path, limit: int) -> None:
        try:
            stat = path.stat()
        except OSError as exc:
            raise ValueError(f"无法读取文件: {path}") from exc
        if not path.is_file():
            raise ValueError(f"路径不是普通文件: {path}")
        if stat.st_size > limit:
            raise ValueError(f"文件超过插件读取限额: {stat.st_size} > {limit}")

    def _read_file_bytes(self, path: Path, limits: PluginHostLimits) -> bytes:
        self._ensure_regular_file_within_limit(path, limits.read_bytes)
        with path.open("rb") as handle:
            data = handle.read(limits.read_bytes + 1)
        if len(data) > limits.read_bytes:
            raise ValueError(f"文件超过插件读取限额: {len(data)} > {limits.read_bytes}")
        return data

    def _check_artifact_size(self, size: int, limits: PluginHostLimits) -> None:
        if size > limits.artifact_bytes:
            raise ValueError(f"插件产物大小超过限额: {size} > {limits.artifact_bytes}")

    def _estimate_base64_size(self, content: str) -> int:
        cleaned = "".join(str(content or "").split())
        if not cleaned:
            return 0
        padding = len(cleaned) - len(cleaned.rstrip("="))
        return max(0, (len(cleaned) * 3) // 4 - padding)

    def _coerce_artifact_bytes(self, params: dict[str, Any], limits: PluginHostLimits) -> bytes:
        if "contentBase64" in params:
            content = str(params.get("contentBase64") or "")
            self._check_artifact_size(self._estimate_base64_size(content), limits)
            try:
                data = base64.b64decode(content.encode("utf-8"))
            except binascii.Error as exc:
                raise ValueError("artifact base64 内容无效") from exc
            self._check_artifact_size(len(data), limits)
            return data
        text = params.get("text")
        if text is not None:
            encoding = str(params.get("encoding") or "utf-8")
            data = str(text).encode(encoding)
            self._check_artifact_size(len(data), limits)
            return data
        content = params.get("content")
        if isinstance(content, str):
            encoding = str(params.get("encoding") or "utf-8")
            data = content.encode(encoding)
            self._check_artifact_size(len(data), limits)
            return data
        raise ValueError("artifact 内容不能为空")

    async def dispatch(
        self,
        context: PluginHostContext,
        manifest: PluginManifest,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        permissions = manifest.runtime.permissions
        limits = manifest.runtime.limits
        if method == "host.workspace.read_text":
            self._require(permissions.workspace_read, "workspaceRead")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or ""))
            encoding = str(params.get("encoding") or "utf-8")
            return {
                "path": str(path),
                "content": self._read_file_bytes(path, limits).decode(encoding),
            }
        if method == "host.workspace.read_bytes":
            self._require(permissions.workspace_read, "workspaceRead")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or ""))
            return {
                "path": str(path),
                "contentBase64": base64.b64encode(self._read_file_bytes(path, limits)).decode("ascii"),
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
            if not path.is_dir():
                raise ValueError(f"路径不是目录: {path}")
            for entry in path.iterdir():
                if len(entries) > limits.directory_entries:
                    break
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
            truncated = len(entries) > limits.directory_entries
            entries = entries[: limits.directory_entries]
            entries.sort(key=lambda item: (not item["isDir"], str(item["name"]).lower()))
            return {
                "path": str(path),
                "entries": entries,
                "truncated": truncated,
                "entryLimit": limits.directory_entries,
            }
        if method == "host.workspace.outline":
            self._require(permissions.workspace_read, "workspaceRead")
            path = resolve_workspace_path(context.workspace_root, str(params.get("path") or ""))
            self._ensure_regular_file_within_limit(path, limits.read_bytes)
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
                content=self._coerce_artifact_bytes(params, limits),
                content_type=str(params.get("contentType") or params.get("content_type") or "application/octet-stream"),
                limits=limits,
            )
            return {
                "artifactId": record.artifact_id,
                "filename": record.filename,
                "sizeBytes": record.size_bytes,
                "contentType": record.content_type,
            }
        raise ValueError(f"unknown host api method: {method}")
