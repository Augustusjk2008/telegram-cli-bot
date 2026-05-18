from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mermaid_visio.artifact_packager import package_results
from mermaid_visio.export_actions import export_selected
from mermaid_visio.flowchart_parser import parse_flowchart
from mermaid_visio.host_rpc import emit, read_workspace_text, write_artifact
from mermaid_visio.models import DiagramStatus, PluginConfig
from mermaid_visio.normalizer import normalize_ir
from mermaid_visio.source_extractor import extract_diagrams

SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_COUNTER = 0


def respond(request_id: Any, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error:
        payload["error"] = {"code": -32000, "message": error}
    else:
        payload["result"] = result or {}
    emit(payload)


def plugin_config(context: dict[str, Any]) -> PluginConfig:
    return PluginConfig.from_payload(dict(((context.get("plugin") or {}).get("config") or {})))


def table_summary(statuses: list[DiagramStatus]) -> dict[str, Any]:
    return {
        "columns": [
            {"id": "title", "title": "图"},
            {"id": "status", "title": "状态"},
            {"id": "line", "title": "起始行", "kind": "number", "align": "right"},
            {"id": "nodes", "title": "节点", "kind": "number", "align": "right"},
            {"id": "edges", "title": "连线", "kind": "number", "align": "right"},
            {"id": "warnings", "title": "警告", "wrap": True},
            {"id": "output", "title": "输出", "wrap": True},
        ],
        "totalRows": len(statuses),
        "defaultPageSize": max(1, min(50, len(statuses) or 1)),
        "actions": [{"id": "export-all", "label": "全部导出 VSDX", "target": "plugin", "location": "toolbar", "variant": "primary"}],
    }


def table_rows(statuses: list[DiagramStatus]) -> list[dict[str, Any]]:
    rows = []
    for status in statuses:
        disabled = status.status == "error" and bool(status.error)
        rows.append(
            {
                "id": status.source.source_id,
                "cells": {
                    "title": status.source.title,
                    "status": _status_label(status.status),
                    "line": status.source.start_line,
                    "nodes": status.node_count,
                    "edges": status.edge_count,
                    "warnings": "; ".join(status.warnings),
                    "output": status.artifact_filename or status.error,
                },
                "actions": [{"id": "export-one", "label": "导出", "target": "plugin", "location": "row", "disabled": disabled}],
            }
        )
    return rows


def open_view(input_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER
    path = str(input_payload.get("path") or "")
    config = plugin_config(context)
    content = read_workspace_text(path)
    if len(content.encode("utf-8")) > config.max_source_bytes:
        raise RuntimeError(f"文件超过限制: {config.max_source_bytes} bytes")
    statuses = [_build_status(source, config) for source in extract_diagrams(path, content)]
    SESSION_COUNTER += 1
    session_id = f"{((context.get('host') or {}).get('botAlias') or 'main')}-mermaid-visio-{SESSION_COUNTER}"
    SESSIONS[session_id] = {"path": path, "statuses": statuses, "config": config}
    return {
        "renderer": "table",
        "title": Path(path).name,
        "mode": "session",
        "sessionId": session_id,
        "summary": table_summary(statuses),
        "initialWindow": {"offset": 0, "limit": len(statuses), "totalRows": len(statuses), "rows": table_rows(statuses)},
    }


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session = SESSIONS[str(params.get("sessionId") or "")]
    statuses = _filter_statuses(session["statuses"], str(params.get("query") or ""))
    offset = int(params.get("offset") or 0)
    limit = int(params.get("limit") or len(statuses) or 1)
    return {
        "offset": offset,
        "limit": limit,
        "totalRows": len(statuses),
        "rows": table_rows(statuses[offset:offset + limit]),
    }


def invoke_action(params: dict[str, Any]) -> dict[str, Any]:
    session = SESSIONS[str(params.get("sessionId") or "")]
    statuses: list[DiagramStatus] = session["statuses"]
    config: PluginConfig = session["config"]
    action_id = str(params.get("actionId") or "")
    payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
    selected = statuses
    if action_id == "export-one":
        row_id = str(payload.get("rowId") or "")
        selected = [status for status in statuses if status.source.source_id == row_id]
    if len(selected) > config.max_diagrams_per_export:
        return {"message": f"图数量超过批量限制: {len(selected)} > {config.max_diagrams_per_export}", "refresh": "session"}
    if not selected:
        return {"message": "没有可导出的图", "refresh": "session"}

    results = export_selected(selected, config)
    if not any(result.ok for result in results):
        return {"message": results[0].error if results else "没有可导出的图", "refresh": "session"}
    filename, content, content_type = package_results(results)
    artifact_id = write_artifact(filename, content, content_type)
    return {
        "message": "已导出",
        "refresh": "session",
        "hostEffects": [{"type": "download_artifact", "artifactId": artifact_id, "filename": filename}],
    }


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    session_id = str(params.get("sessionId") or "")
    return {"disposed": SESSIONS.pop(session_id, None) is not None}


def _build_status(source, config: PluginConfig) -> DiagramStatus:
    status = DiagramStatus(source=source)
    if not source.code.strip():
        status.status = "error"
        status.error = "Mermaid 图为空"
        return status
    try:
        ir = normalize_ir(parse_flowchart(source.code), config)
        status.node_count = len(ir.nodes)
        status.edge_count = len(ir.edges)
        status.warnings = list(ir.warnings)
    except Exception as exc:
        status.status = "error"
        status.error = str(exc)
    return status


def _filter_statuses(statuses: list[DiagramStatus], query: str) -> list[DiagramStatus]:
    keyword = query.strip().lower()
    if not keyword:
        return statuses
    return [status for status in statuses if keyword in status.source.title.lower()]


def _status_label(status: str) -> str:
    return {"ready": "待导出", "done": "已导出", "error": "失败"}.get(status, status)


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    context = params.get("context") if isinstance(params.get("context"), dict) else {}
    try:
        if method == "plugin.initialize":
            respond(request_id, {"ok": True, "name": "mermaid-visio"})
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
    except Exception as exc:
        respond(request_id, error=str(exc))
