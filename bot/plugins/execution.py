from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .host_api import resolve_workspace_path


def payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def count_tree_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    stack = list(nodes)
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(item for item in list(node.get("children") or []) if isinstance(item, dict))
    return total


def resolve_input_payload(
    bot_alias: str,
    input_payload: dict[str, Any],
    workspace_root_for: Callable[[str], Path],
) -> dict[str, Any]:
    resolved_input = dict(input_payload or {})
    path_value = resolved_input.get("path")
    if path_value is None:
        return resolved_input
    raw_path = Path(str(path_value))
    if raw_path.is_absolute():
        resolved_input["path"] = str(raw_path.expanduser().resolve())
        return resolved_input
    resolved_input["path"] = str(resolve_workspace_path(workspace_root_for(bot_alias), str(path_value)))
    return resolved_input


def build_payload_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    tracks = [item for item in list(payload.get("tracks") or []) if isinstance(item, dict)]
    rows = [item for item in list(payload.get("rows") or []) if isinstance(item, dict)]
    roots = [item for item in list(payload.get("roots") or []) if isinstance(item, dict)]
    nodes = [item for item in list(payload.get("nodes") or []) if isinstance(item, dict)]
    return {
        "payload_bytes": payload_bytes(payload),
        "track_count": len(tracks),
        "segment_count": sum(len(track.get("segments") or []) for track in tracks),
        "row_count": len(rows),
        "node_count": count_tree_nodes(roots) + count_tree_nodes(nodes),
    }


def validate_render_result(
    plugin_id: str,
    view,
    result: dict[str, Any],
    *,
    expect_session: bool,
) -> dict[str, Any]:
    renderer = str(result.get("renderer") or "")
    if renderer != view.renderer:
        raise RuntimeError(f"插件 renderer 不匹配: expected={view.renderer} actual={renderer}")
    payload = {
        "pluginId": plugin_id,
        "viewId": view.id,
        "title": str(result.get("title") or view.title or ""),
        "renderer": renderer,
    }
    if expect_session:
        session_id = str(result.get("sessionId") or "")
        if not session_id:
            raise RuntimeError("插件未返回 sessionId")
        return {
            **payload,
            "mode": "session",
            "sessionId": session_id,
            "summary": dict(result.get("summary") or {}),
            "initialWindow": dict(result.get("initialWindow") or {}),
        }
    return {
        **payload,
        "mode": "snapshot",
        "payload": dict(result.get("payload") or {}),
    }


def normalize_action_result(result: dict[str, Any]) -> dict[str, Any]:
    refresh = str(result.get("refresh") or "none").strip() or "none"
    if refresh not in {"none", "view", "session"}:
        refresh = "none"
    host_effects = result.get("hostEffects") or []
    if not isinstance(host_effects, list):
        raise RuntimeError("插件 action hostEffects 必须是数组")
    return {
        "message": str(result.get("message") or ""),
        "refresh": refresh,
        "hostEffects": [dict(item) for item in host_effects if isinstance(item, dict)],
        "closeSession": bool(result.get("closeSession", False)),
    }
