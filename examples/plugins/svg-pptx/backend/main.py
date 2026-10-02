from __future__ import annotations

import base64
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from plugin_sdk import PluginServer
from worker_runner import DEFAULTS, bounded_config, run_worker


server = PluginServer("svg-pptx", defaults=DEFAULTS)
SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_COUNTER = 0
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def install_command() -> str:
    requirements = str(Path(__file__).resolve().parent.parent / "requirements.txt")
    if os.name == "nt":
        return f'& "{sys.executable}" -m pip install -r "{requirements}"'
    return f'{shlex.quote(sys.executable)} -m pip install -r {shlex.quote(requirements)}'


def read_source(path: str, config: dict[str, int]) -> bytes:
    if not path or Path(path).suffix.lower() != ".svg":
        raise ValueError("请选择 .svg 文件")
    host_limits = (server.context.get("host") or {}).get("limits") or {}
    limit = min(config["maxSourceBytes"], int(host_limits.get("readBytes", 32 * 1024 * 1024)))
    response = server.host_call("host.workspace.stat", {"path": path})
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or "读取 SVG 文件信息失败"))
    stat = response.get("result") or {}
    if not stat.get("exists") or stat.get("isDir"):
        raise ValueError("SVG 文件不存在或不是普通文件")
    if int(stat.get("size", 0)) > limit:
        raise ValueError(f"SVG 文件超过限制: {limit} bytes")
    source = server.read_bytes(path, error_message="读取 SVG 失败")
    if len(source) > limit:
        raise ValueError(f"SVG 文件超过限制: {limit} bytes")
    return source


def convert(path: str, operation: str) -> dict[str, Any]:
    config = bounded_config(server.config)
    source = read_source(path, config)
    host_limits = (server.context.get("host") or {}).get("limits") or {}
    return run_worker(
        operation, source, config,
        max_artifact_bytes=int(host_limits.get("artifactBytes", 32 * 1024 * 1024)),
    )


def report_from_result(result: dict[str, Any]) -> dict[str, Any]:
    report = {"width": 0, "height": 0, "textCount": 0, "layerCount": 0, "warnings": [], "errors": []}
    report.update(result.get("report") or {})
    if not result.get("ok"):
        report["errors"] = [str(result.get("error") or "SVG 转换失败")]
    if result.get("missingDependencies"):
        report["errors"].append("请在宿主 Python 中安装依赖: " + install_command())
    return report


def inspect(path: str) -> dict[str, Any]:
    try:
        return report_from_result(convert(path, "inspect"))
    except Exception as exc:
        return report_from_result({"ok": False, "error": str(exc)})


def table(path: str, report: dict[str, Any]) -> dict[str, Any]:
    errors = list(report["errors"])
    return {
        "columns": [
            {"id": "file", "title": "SVG"},
            {"id": "dimensions", "title": "画布尺寸"},
            {"id": "textCount", "title": "文本框", "kind": "number"},
            {"id": "layerCount", "title": "图片层", "kind": "number"},
            {"id": "warnings", "title": "提示", "wrap": True},
            {"id": "errors", "title": "不可导出原因", "wrap": True},
        ],
        "rows": [{"id": "svg", "cells": {
            "file": Path(path).name,
            "dimensions": f"{report['width']:g} × {report['height']:g}",
            "textCount": report["textCount"],
            "layerCount": report["layerCount"],
            "warnings": "; ".join(report["warnings"]),
            "errors": "; ".join(errors),
        }}],
        "actions": [{
            "id": "export-pptx", "label": "导出 PPTX", "target": "plugin",
            "location": "toolbar", "variant": "primary", "disabled": bool(errors),
            "tooltip": "; ".join(errors), "payload": {"path": path},
        }],
    }


def open_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    global SESSION_COUNTER
    path = str(input_payload.get("path") or "")
    report = inspect(path)
    SESSION_COUNTER += 1
    session_id = f"svg-pptx-{SESSION_COUNTER}"
    SESSIONS[session_id] = {"path": path, "report": report}
    payload = table(path, report)
    return {
        "renderer": "table", "title": Path(path).name, "mode": "session", "sessionId": session_id,
        "summary": {"columns": payload["columns"], "actions": payload["actions"], "totalRows": 1, "defaultPageSize": 1},
        "initialWindow": {"offset": 0, "limit": 1, "totalRows": 1, "rows": payload["rows"]},
    }


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "")
    return {"renderer": "table", "title": Path(path).name, "payload": table(path, inspect(path))}


def get_view_window(params: dict[str, Any]) -> dict[str, Any]:
    session = SESSIONS[str(params.get("sessionId") or "")]
    offset = max(0, int(params.get("offset") or 0))
    limit = max(1, int(params.get("limit") or 1))
    rows = table(session["path"], session["report"])["rows"]
    query = str(params.get("query") or "").casefold()
    if query and query not in str(rows[0]["cells"]).casefold():
        rows = []
    return {"offset": offset, "limit": limit, "totalRows": len(rows), "rows": rows[offset:offset + limit]}


def invoke_action(params: dict[str, Any]) -> dict[str, Any]:
    if params.get("actionId") != "export-pptx":
        raise ValueError("未知 SVG 操作")
    session_id = str(params.get("sessionId") or "")
    session = SESSIONS[session_id] if session_id else None
    path = session["path"] if session else str((params.get("payload") or {}).get("path") or "")
    # Always reread and revalidate, even if the view was opened successfully.
    try:
        result = convert(path, "export")
        report = report_from_result(result)
        if session is not None:
            session["report"] = report
        if report["errors"]:
            return {"message": "; ".join(report["errors"]), "refresh": "view"}
        content = base64.b64decode(result["contentBase64"], validate=True)
        filename = Path(path).with_suffix(".pptx").name
        artifact = server.write_artifact(filename, content, CONTENT_TYPE, error_message="写入 PPTX 产物失败")
        return {
            "message": "已导出 PPTX", "refresh": "view",
            "hostEffects": [{"type": "download_artifact", "artifactId": artifact["artifactId"], "filename": artifact["filename"]}],
        }
    except Exception as exc:
        if session is not None:
            session["report"] = report_from_result({"ok": False, "error": str(exc)})
        return {"message": str(exc), "refresh": "view"}


def dispose_view(params: dict[str, Any]) -> dict[str, Any]:
    return {"disposed": SESSIONS.pop(str(params.get("sessionId") or ""), None) is not None}


if __name__ == "__main__":
    server.register_handler("plugin.get_view_window", get_view_window)
    server.register_handler("plugin.invoke_action", invoke_action)
    server.register_handler("plugin.dispose_view", dispose_view)
    server.run(render_view, open_view=open_view, shutdown=SESSIONS.clear)
