from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_sdk import PluginServer
from zip_parser import ZipIndex, build_zip_index


server = PluginServer("zip-preview")
SESSION_COUNTER = 0
SESSIONS: dict[str, ZipIndex] = {}


def _read_index(input_payload: dict[str, Any]) -> ZipIndex:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 ZIP 路径")
    return build_zip_index(path, server.read_bytes(path, error_message="读取 ZIP 失败"), server.config)


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
        raise RuntimeError("ZIP 预览会话不存在或已释放")
    if params.get("op") != "children":
        raise RuntimeError("ZIP 预览仅支持 children 请求")
    node_id = str(params["nodeId"]) if params.get("nodeId") is not None else None
    return {"op": "children", "nodeId": node_id, "nodes": index.get_nodes(node_id)}


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    return {"disposed": SESSIONS.pop(str(params.get("sessionId") or ""), None) is not None}


def shutdown() -> None:
    SESSIONS.clear()


if __name__ == "__main__":
    server.register_handler("plugin.get_view_window", get_view_window)
    server.register_handler("plugin.dispose_view", dispose_view)
    server.run(render_view, open_view=open_view, shutdown=shutdown)
