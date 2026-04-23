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
        raise RuntimeError(str(response["error"].get("message") or "读取报告失败"))
    return str((response.get("result") or {}).get("content") or "")


def write_artifact(filename: str, text: str) -> str:
    response = call_host("host.temp.write_artifact", {"filename": filename, "text": text, "encoding": "utf-8"})
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or "导出失败"))
    return str((response.get("result") or {}).get("artifactId") or "")


def parse_slack(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value


def parse_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return rows
    start_index = 1 if "," in raw_lines[0] and ("slack" in raw_lines[0].lower() or "path" in raw_lines[0].lower()) else 0
    for index, line in enumerate(raw_lines[start_index:], start=1):
        if "," in line:
            endpoint, slack = [part.strip() for part in line.split(",", 1)]
        else:
            parts = line.split()
            endpoint = parts[0] if parts else f"path-{index}"
            slack = parts[-1] if len(parts) > 1 else "0"
        rows.append(
            {
                "id": f"path-{index}",
                "cells": {
                    "endpoint": endpoint or f"path-{index}",
                    "slack": parse_slack(slack),
                },
                "actions": [
                    {"id": "open-source", "label": "打开源码", "target": "plugin", "location": "row"},
                    {"id": "export-row", "label": "导出行", "target": "plugin", "location": "row"},
                ],
            }
        )
    return rows


def filtered_rows(rows: list[dict[str, Any]], query: str, sort: dict[str, Any] | None) -> list[dict[str, Any]]:
    next_rows = rows
    keyword = query.strip().lower()
    if keyword:
        next_rows = [
            row for row in next_rows
            if keyword in str(row["cells"].get("endpoint") or "").lower()
        ]
    if sort and sort.get("columnId") == "slack":
        reverse = str(sort.get("direction") or "asc") == "desc"
        next_rows = sorted(next_rows, key=lambda row: float(row["cells"].get("slack") or 0), reverse=reverse)
    return next_rows


def paged_rows(rows: list[dict[str, Any]], offset: int, limit: int) -> list[dict[str, Any]]:
    return rows[offset:offset + limit]


def build_summary(total_rows: int, default_page_size: int) -> dict[str, Any]:
    return {
        "columns": [
            {"id": "endpoint", "title": "Endpoint"},
            {"id": "slack", "title": "Slack", "kind": "number", "align": "right", "sortable": True},
        ],
        "totalRows": total_rows,
        "defaultPageSize": default_page_size,
        "actions": [
            {"id": "export-all", "label": "导出 CSV", "target": "plugin", "location": "toolbar", "variant": "primary"}
        ],
    }


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(Path(str(input_payload.get("path") or "timing.rpt")).resolve())
    rows = parse_rows(workspace_read_text(path))
    return {
        "renderer": "table",
        "title": Path(path).name,
        "payload": {
            "columns": build_summary(len(rows), max(len(rows), 1))["columns"],
            "rows": rows,
            "actions": build_summary(len(rows), max(len(rows), 1))["actions"],
        },
    }


def open_view(input_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER
    path = str(Path(str(input_payload.get("path") or "timing.rpt")).resolve())
    rows = parse_rows(workspace_read_text(path))
    default_page_size = int(((context.get("plugin") or {}).get("config") or {}).get("defaultPageSize") or 50)
    SESSION_COUNTER += 1
    session_id = f"{((context.get('host') or {}).get('botAlias') or 'main')}-timing-{SESSION_COUNTER}"
    SESSIONS[session_id] = {
        "path": path,
        "rows": rows,
        "summary": build_summary(len(rows), default_page_size),
    }
    return {
        "renderer": "table",
        "title": Path(path).name,
        "mode": "session",
        "sessionId": session_id,
        "summary": SESSIONS[session_id]["summary"],
        "initialWindow": {
            "offset": 0,
            "limit": default_page_size,
            "totalRows": len(rows),
            "rows": paged_rows(rows, 0, default_page_size),
        },
    }


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    session = SESSIONS[session_id]
    offset = int(params.get("offset") or 0)
    limit = int(params.get("limit") or session["summary"]["defaultPageSize"])
    sort = params.get("sort") if isinstance(params.get("sort"), dict) else None
    rows = filtered_rows(session["rows"], str(params.get("query") or ""), sort)
    return {
        "offset": offset,
        "limit": limit,
        "totalRows": len(rows),
        "rows": paged_rows(rows, offset, limit),
        "appliedSort": sort,
    }


def invoke_action(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    session = SESSIONS[session_id]
    action_id = str(params.get("actionId") or "")
    payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
    if action_id == "open-source":
        return {
            "message": "已打开源码",
            "hostEffects": [{"type": "open_file", "path": "src/index.ts", "line": 12}],
        }

    rows = session["rows"]
    if action_id == "export-row":
        row_id = str(payload.get("rowId") or "")
        rows = [row for row in rows if row["id"] == row_id]
    csv_lines = ["endpoint,slack"]
    for row in rows:
        csv_lines.append(f"{row['cells'].get('endpoint')},{row['cells'].get('slack')}")
    artifact_id = write_artifact("timing.csv", "\n".join(csv_lines) + "\n")
    return {
        "message": "已导出",
        "refresh": "session",
        "hostEffects": [
            {"type": "download_artifact", "artifactId": artifact_id, "filename": "timing.csv"}
        ],
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
            respond(request_id, {"ok": True, "name": "timing-report"})
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
