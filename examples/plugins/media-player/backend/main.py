from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_sdk import PluginServer


server = PluginServer("media-player")

AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav"}
VIDEO_EXTENSIONS = {".mp4", ".ogv", ".webm"}


def _relative_workspace_path(path_value: str) -> str:
    host = server.context.get("host") or {}
    workspace_root = Path(str(host.get("workspaceRoot") or "")).expanduser().resolve()
    target = Path(path_value).expanduser()
    if not target.is_absolute():
        target = workspace_root / target
    target = target.resolve()
    try:
        return target.relative_to(workspace_root).as_posix()
    except ValueError as exc:
        raise RuntimeError("媒体文件必须位于工作区内") from exc


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(input_payload.get("path") or "").strip()
    if not raw_path:
        raise RuntimeError("缺少媒体文件路径")

    extension = Path(raw_path).suffix.lower()
    if extension in VIDEO_EXTENSIONS:
        media_type = "video"
    elif extension in AUDIO_EXTENSIONS:
        media_type = "audio"
    else:
        raise RuntimeError("不支持的媒体格式")

    path = _relative_workspace_path(raw_path)
    return {
        "renderer": "media",
        "title": Path(path).name,
        "payload": {"path": path, "mediaType": media_type},
    }


if __name__ == "__main__":
    server.run(render_view)
