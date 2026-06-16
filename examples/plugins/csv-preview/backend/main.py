from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

from csv_parser import parse_csv_table, query_csv_window

NEXT_REQUEST_ID = 9000
SESSIONS: dict[str, dict[str, Any]] = {}


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(
    request_id: Any, result: dict[str, Any] | None = None, error: str | None = None
) -> None:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error:
        payload["error"] = {"code": -32000, "message": error}
    else:
        payload["result"] = result or {}
    emit(payload)


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


def read_bytes(path: str) -> bytes:
    response = call_host("host.workspace.read_bytes", {"path": path})
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or "读取 CSV 失败"))
    content_base64 = str((response.get("result") or {}).get("contentBase64") or "")
    return base64.b64decode(content_base64.encode("ascii"))


def resolve_path(input_payload: dict[str, Any]) -> str:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 CSV 路径")
    return str(Path(path))


def open_view(input_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(input_payload)
    default_page_size = int(
        ((context.get("plugin") or {}).get("config") or {}).get("defaultPageSize") or 50
    )
    table = parse_csv_table(path, read_bytes(path), default_page_size)
    session_id = f"{((context.get('host') or {}).get('botAlias') or 'main')}-csv-{len(SESSIONS) + 1}"
    SESSIONS[session_id] = {
        "path": path,
        "table": table,
    }
    initial_window = query_csv_window(table, offset=0, limit=default_page_size)
    return {
        "renderer": "table",
        "title": table["title"],
        "mode": "session",
        "sessionId": session_id,
        "summary": {
            "columns": table["columns"],
            "totalRows": len(table["rows"]),
            "defaultPageSize": default_page_size,
            "actions": [],
        },
        "initialWindow": initial_window,
    }


def render_view(
    input_payload: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    opened = open_view(input_payload, context)
    window = opened["initialWindow"]
    return {
        "renderer": "table",
        "title": opened["title"],
        "payload": {
            "columns": opened["summary"]["columns"],
            "rows": window["rows"],
            "actions": opened["summary"].get("actions") or [],
        },
    }


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    session = SESSIONS[session_id]
    table = session["table"]
    return query_csv_window(
        table,
        offset=int(params.get("offset") or 0),
        limit=int(params.get("limit") or table["metadata"]["defaultPageSize"]),
        query=str(params.get("query") or ""),
        sort=params.get("sort") if isinstance(params.get("sort"), dict) else None,
    )


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    return {"disposed": SESSIONS.pop(session_id, None) is not None}


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    context = params.get("context") if isinstance(params.get("context"), dict) else {}
    try:
        if method == "plugin.initialize":
            respond(request_id, {"ok": True, "name": "csv-preview"})
        elif method == "plugin.render_view":
            respond(request_id, render_view(dict(params.get("input") or {}), context))
        elif method == "plugin.open_view":
            respond(request_id, open_view(dict(params.get("input") or {}), context))
        elif method == "plugin.get_view_window":
            respond(request_id, get_view_window(dict(params)))
        elif method == "plugin.dispose_view":
            respond(request_id, dispose_view(dict(params)))
        elif method == "plugin.shutdown":
            respond(request_id, {"ok": True})
        else:
            respond(request_id, error=f"unsupported method: {method}")
    except Exception as exc:  # pragma: no cover
        respond(request_id, error=str(exc))
