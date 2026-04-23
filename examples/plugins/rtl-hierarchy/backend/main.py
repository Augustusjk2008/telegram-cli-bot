from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SESSION_COUNTER = 0
NEXT_REQUEST_ID = 9000
SESSIONS: dict[str, dict[str, Any]] = {}


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def call_host(method: str, params: dict[str, Any]) -> dict[str, Any]:
    global NEXT_REQUEST_ID
    request_id = NEXT_REQUEST_ID
    NEXT_REQUEST_ID += 1
    emit({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    while True:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(0)
        message = json.loads(line)
        if message.get("method"):
            continue
        if int(message.get("id") or 0) == request_id:
            return message


def workspace_read_text(path: str) -> str:
    response = call_host("host.workspace.read_text", {"path": path, "encoding": "utf-8"})
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or "读取层级失败"))
    return str((response.get("result") or {}).get("content") or "")


def make_node(node_id: str, label: str, *, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "expandable": bool(children),
        "children": children or [],
        "actions": [
            {"id": "open-source", "label": "打开源码", "target": "plugin", "location": "node"},
            {"id": "copy-name", "label": "复制名", "target": "host", "location": "node", "hostAction": {"type": "copy_text", "text": label}},
        ],
    }


def parse_tree(text: str) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        depth = indent // 2
        label = raw_line.strip()
        parent_id = stack[depth - 1][1]["id"] if depth > 0 and len(stack) >= depth else ""
        node_id = label if not parent_id else f"{parent_id}.{label}"
        node = make_node(node_id, label)
        while len(stack) > depth:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
            stack[-1][1]["expandable"] = True
        else:
            roots.append(node)
        stack.append((depth, node))
    return roots


def clone_nodes(nodes: list[dict[str, Any]], *, include_children: bool) -> list[dict[str, Any]]:
    cloned: list[dict[str, Any]] = []
    for node in nodes:
        children = clone_nodes(node.get("children") or [], include_children=include_children) if include_children else []
        cloned.append(
            {
                "id": node["id"],
                "label": node["label"],
                "expandable": bool(node.get("children")),
                "children": children if include_children else [],
                "actions": list(node.get("actions") or []),
            }
        )
    return cloned


def find_node(nodes: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    for node in nodes:
        if node["id"] == node_id:
            return node
        found = find_node(node.get("children") or [], node_id)
        if found:
            return found
    return None


def search_nodes(nodes: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    keyword = query.strip().lower()
    if not keyword:
        return clone_nodes(nodes, include_children=False)
    matched: list[dict[str, Any]] = []
    for node in nodes:
        if keyword in str(node.get("label") or "").lower():
            matched.append(
                {
                    "id": node["id"],
                    "label": node["label"],
                    "expandable": bool(node.get("children")),
                    "actions": list(node.get("actions") or []),
                }
            )
        matched.extend(search_nodes(node.get("children") or [], query))
    return matched


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(Path(str(input_payload.get("path") or "design.hier")).resolve())
    roots = parse_tree(workspace_read_text(path))
    return {
        "renderer": "tree",
        "title": Path(path).name,
        "payload": {
            "roots": clone_nodes(roots, include_children=False),
            "actions": [
                {
                    "id": "open-timing",
                    "label": "打开 Timing",
                    "target": "host",
                    "location": "toolbar",
                    "hostAction": {
                        "type": "open_plugin_view",
                        "pluginId": "timing-report",
                        "viewId": "timing-table",
                        "title": "timing.rpt",
                        "input": {"path": "reports/timing.rpt"},
                    },
                }
            ],
        },
    }


def open_view(input_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER
    path = str(Path(str(input_payload.get("path") or "design.hier")).resolve())
    roots = parse_tree(workspace_read_text(path))
    SESSION_COUNTER += 1
    session_id = f"{((context.get('host') or {}).get('botAlias') or 'main')}-hier-{SESSION_COUNTER}"
    SESSIONS[session_id] = {"path": path, "roots": roots}
    return {
        "renderer": "tree",
        "title": Path(path).name,
        "mode": "session",
        "sessionId": session_id,
        "summary": {
            "roots": clone_nodes(roots, include_children=False),
            "searchable": True,
            "actions": [
                {
                    "id": "open-timing",
                    "label": "打开 Timing",
                    "target": "host",
                    "location": "toolbar",
                    "hostAction": {
                        "type": "open_plugin_view",
                        "pluginId": "timing-report",
                        "viewId": "timing-table",
                        "title": "timing.rpt",
                        "input": {"path": "reports/timing.rpt"},
                    },
                }
            ],
        },
        "initialWindow": {"roots": clone_nodes(roots, include_children=False)},
    }


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session = SESSIONS[str(params.get("sessionId") or "")]
    if params.get("kind") == "children":
        node = find_node(session["roots"], str(params.get("nodeId") or ""))
        return {
            "nodeId": str(params.get("nodeId") or ""),
            "nodes": clone_nodes(list(node.get("children") or []) if node else [], include_children=False),
        }
    return {"roots": search_nodes(session["roots"], str(params.get("query") or ""))}


def invoke_action(params: dict[str, Any]) -> dict[str, Any]:
    action_id = str(params.get("actionId") or "")
    payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
    node_id = str(payload.get("nodeId") or "")
    if action_id == "open-source":
        return {
            "message": "已打开源码",
            "hostEffects": [{"type": "open_file", "path": "src/index.ts", "line": 12}],
        }
    return {
        "message": "已复制",
        "hostEffects": [{"type": "copy_text", "text": node_id}],
    }


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    return {"disposed": SESSIONS.pop(session_id, None) is not None}


def respond(request_id: Any, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error:
        payload["error"] = {"code": -32000, "message": error}
    else:
        payload["result"] = result or {}
    emit(payload)


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    context = params.get("context") if isinstance(params.get("context"), dict) else {}
    try:
        if method == "plugin.initialize":
            respond(request_id, {"ok": True, "name": "rtl-hierarchy"})
        elif method == "plugin.render_view":
            respond(request_id, render_view(dict(params.get("input") or {})))
        elif method == "plugin.open_view":
            respond(request_id, open_view(dict(params.get("input") or {}), context))
        elif method == "plugin.get_view_window":
            respond(request_id, get_view_window(dict(params)))
        elif method == "plugin.invoke_action":
            respond(request_id, invoke_action(dict(params)))
        elif method == "plugin.dispose_view":
            respond(request_id, dispose_view(dict(params)))
        elif method == "plugin.shutdown":
            respond(request_id, {"ok": True})
        else:
            respond(request_id, error=f"unsupported method: {method}")
    except Exception as exc:  # pragma: no cover
        respond(request_id, error=str(exc))
