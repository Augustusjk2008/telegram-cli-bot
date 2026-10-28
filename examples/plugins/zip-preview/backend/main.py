from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from plugin_sdk import PluginServer
from zip_parser import ArchiveIndex, build_archive_index, extract_archive


server = PluginServer("zip-preview")
SESSION_COUNTER = 0
SESSIONS: dict[str, ArchiveIndex] = {}


def _read_index(input_payload: dict[str, Any]) -> ArchiveIndex:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少压缩包路径")
    return build_archive_index(path, server.read_bytes(path, error_message="读取压缩包失败"), server.config)


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    index = _read_index(input_payload)
    return {
        "renderer": "tree",
        "title": Path(index.path).name,
        "payload": index.snapshot(),
    }


def open_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER
    index = _read_index(input_payload)
    summary = index.summary()
    SESSION_COUNTER += 1
    bot_alias = (server.context.get("host") or {}).get("botAlias") or "main"
    session_id = f"{bot_alias}-zip-{SESSION_COUNTER}"
    SESSIONS[session_id] = index
    return {
        "renderer": "tree",
        "title": Path(index.path).name,
        "mode": "session",
        "sessionId": session_id,
        "summary": summary,
        "initialWindow": {"op": "children", "nodeId": None, "nodes": summary["roots"]},
    }


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    index = SESSIONS.get(str(params.get("sessionId") or ""))
    if index is None:
        raise RuntimeError("压缩包预览会话不存在或已释放")
    if params.get("op") != "children":
        raise RuntimeError("压缩包预览仅支持 children 请求")
    node_id = str(params["nodeId"]) if params.get("nodeId") is not None else None
    return {"op": "children", "nodeId": node_id, "nodes": index.get_nodes(node_id)}


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    return {"disposed": SESSIONS.pop(str(params.get("sessionId") or ""), None) is not None}


def invoke_action(params: dict[str, Any]) -> dict[str, Any]:
    if str(params.get("actionId") or "") != "extract-here":
        raise RuntimeError("未知压缩包操作")
    session = SESSIONS.get(str(params.get("sessionId") or ""))
    if session is None:
        raise RuntimeError("压缩包预览会话不存在或已释放")

    files, total_bytes, archive_format = extract_archive(
        session.path,
        server.read_bytes(session.path, error_message="读取压缩包失败"),
        server.config,
        write_bytes=server.write_bytes,
        make_directory=server.make_directory,
    )
    parent = str(PurePosixPath(session.path).parent)
    if parent == ".":
        parent = ""
    target_label = parent or "所在文件夹"
    return {
        "message": f"已解压 {files} 个文件（{total_bytes} bytes）到 {target_label}",
        "refresh": "session",
        "hostEffects": [{"type": "reveal_in_files", "path": parent or "."}],
        "archiveFormat": archive_format,
    }


def shutdown() -> None:
    SESSIONS.clear()


if __name__ == "__main__":
    server.register_handler("plugin.get_view_window", get_view_window)
    server.register_handler("plugin.invoke_action", invoke_action)
    server.register_handler("plugin.dispose_view", dispose_view)
    server.run(render_view, open_view=open_view, shutdown=shutdown)
