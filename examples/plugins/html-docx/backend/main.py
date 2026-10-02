from __future__ import annotations

import base64
import ntpath
import os
import shlex
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from plugin_sdk import PluginServer
from worker_runner import DEFAULTS, bounded_config, run_worker

server = PluginServer("html-docx", defaults=DEFAULTS)
SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_COUNTER = 0
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def install_command() -> str:
    requirements = str(Path(__file__).resolve().parent.parent / "requirements.txt")
    if os.name == "nt":
        return f'& "{sys.executable}" -m pip install -r "{requirements}"'
    return f'{shlex.quote(sys.executable)} -m pip install -r {shlex.quote(requirements)}'


@contextmanager
def operation_budget():
    config = bounded_config(server.config)
    server.deadline = time.monotonic() + config["conversionTimeoutSeconds"]
    try:
        yield config
    except TimeoutError as exc:
        raise TimeoutError(f"HTML 转换超时: {config['conversionTimeoutSeconds']}s（包含文件与资源读取）") from exc
    finally:
        server.deadline = None


def read_file(path: str, limit: int) -> bytes:
    host_limits = (server.context.get("host") or {}).get("limits") or {}
    limit = min(limit, int(host_limits.get("readBytes", 33554432)))
    response = server.host_call("host.workspace.stat", {"path": path})
    if response.get("error"):
        raise ValueError(str(response["error"].get("message") or "读取文件信息失败"))
    stat = response.get("result") or {}
    if not stat.get("exists") or stat.get("isDir"):
        raise ValueError(f"文件不存在或不是普通文件: {path}")
    if int(stat.get("size", 0)) > limit:
        raise ValueError(f"文件超过读取限额 {limit} bytes: {path}")
    content = server.read_bytes(path, error_message=f"读取文件失败: {path}")
    if len(content) > limit:
        raise ValueError(f"文件超过读取限额 {limit} bytes: {path}")
    return content


def resource_path(source_path: str, reference: str) -> str:
    decoded = unquote(reference.strip()).replace("\\", "/")
    parsed = urlsplit(decoded)
    if (not parsed.path or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
            or ntpath.isabs(decoded) or ntpath.splitdrive(decoded)[0]
            or any(ord(char) < 32 for char in decoded) or ":" in decoded):
        raise ValueError(f"图片必须是工作区内的相对路径: {reference}")
    # Host API resolves the path and enforces the workspace/symlink boundary.
    return str(Path(source_path).parent / parsed.path)


def convert(path: str, operation: str, config: dict) -> dict:
    if not path or Path(path).suffix.lower() not in {".html", ".htm"}:
        raise ValueError("请选择 UTF-8 .html 或 .htm 文件")
    source = read_file(path, config["maxSourceBytes"])
    host_limits = (server.context.get("host") or {}).get("limits") or {}
    arguments = {"deadline": server.deadline, "max_artifact_bytes": int(host_limits.get("artifactBytes", 33554432))}
    discovery = run_worker("inspect", source, config, **arguments)
    report = report_from_result(discovery)
    if report["errors"]:
        return discovery
    resources: dict[str, bytes] = {}
    total = 0
    for reference in dict.fromkeys(report["resources"]):
        try:
            content = read_file(resource_path(path, reference), config["maxResourceBytes"] - total)
        except TimeoutError:
            raise
        except Exception as exc:
            report["errors"].append(f"图片 {reference}: {exc}")
            return {"ok": True, "report": report}
        total += len(content)
        resources[reference] = content
    return run_worker(operation, source, config, resources=resources, **arguments)


def report_from_result(result: dict) -> dict:
    report = {"title": "", "paragraphCount": 0, "tableCount": 0, "imageCount": 0,
              "warnings": [], "errors": [], "resources": []}
    report.update(result.get("report") or {})
    if not result.get("ok"):
        report["errors"] = [str(result.get("error") or "HTML 转换失败")]
    if result.get("missingDependencies"):
        report["errors"].append("请在宿主 Python 中安装依赖: " + install_command())
    return report


def inspect(path: str) -> dict:
    try:
        with operation_budget() as config:
            return report_from_result(convert(path, "inspect", config))
    except Exception as exc:
        return report_from_result({"ok": False, "error": str(exc)})


def table(path: str, report: dict) -> dict:
    errors = "; ".join(report["errors"])
    return {
        "columns": [
            {"id": "file", "title": "HTML"}, {"id": "title", "title": "报告标题", "wrap": True},
            {"id": "paragraphCount", "title": "段落", "kind": "number"},
            {"id": "tableCount", "title": "表格", "kind": "number"},
            {"id": "imageCount", "title": "图片", "kind": "number"},
            {"id": "warnings", "title": "转换提示", "wrap": True},
            {"id": "errors", "title": "不可导出原因", "wrap": True},
        ],
        "rows": [{"id": "html", "cells": {
            "file": Path(path).name, "title": report["title"],
            "paragraphCount": report["paragraphCount"], "tableCount": report["tableCount"],
            "imageCount": report["imageCount"], "warnings": "; ".join(report["warnings"]), "errors": errors,
        }}],
        "actions": [{"id": "export-docx", "label": "导出 DOCX", "target": "plugin",
                     "location": "toolbar", "variant": "primary", "disabled": bool(errors),
                     "tooltip": errors, "payload": {"path": path}}],
    }


def open_view(input_payload: dict) -> dict:
    global SESSION_COUNTER
    path = str(input_payload.get("path") or "")
    report = inspect(path)
    SESSION_COUNTER += 1
    session_id = f"html-docx-{SESSION_COUNTER}"
    SESSIONS[session_id] = {"path": path, "report": report}
    payload = table(path, report)
    return {"renderer": "table", "title": Path(path).name, "mode": "session", "sessionId": session_id,
            "summary": {"columns": payload["columns"], "actions": payload["actions"], "totalRows": 1, "defaultPageSize": 1},
            "initialWindow": {"offset": 0, "limit": 1, "totalRows": 1, "rows": payload["rows"]}}


def render_view(input_payload: dict) -> dict:
    path = str(input_payload.get("path") or "")
    return {"renderer": "table", "title": Path(path).name, "payload": table(path, inspect(path))}


def get_view_window(params: dict) -> dict:
    session = SESSIONS[str(params.get("sessionId") or "")]
    offset = max(0, int(params.get("offset") or 0))
    limit = max(1, int(params.get("limit") or 1))
    rows = table(session["path"], session["report"])["rows"]
    if str(params.get("query") or "").casefold() not in str(rows[0]["cells"]).casefold():
        rows = []
    return {"offset": offset, "limit": limit, "totalRows": len(rows), "rows": rows[offset:offset + limit]}


def invoke_action(params: dict) -> dict:
    if params.get("actionId") != "export-docx":
        raise ValueError("未知 HTML 操作")
    session_id = str(params.get("sessionId") or "")
    session = SESSIONS[session_id] if session_id else None
    path = session["path"] if session else str((params.get("payload") or {}).get("path") or "")
    try:
        with operation_budget() as config:
            # Source and resources are reread on every export, regardless of preview state.
            result = convert(path, "export", config)
            report = report_from_result(result)
            if session is not None:
                session["report"] = report
            if report["errors"]:
                return {"message": "; ".join(report["errors"]), "refresh": "view"}
            content = base64.b64decode(result["contentBase64"], validate=True)
            artifact = server.write_artifact(Path(path).with_suffix(".docx").name, content, CONTENT_TYPE,
                                             error_message="写入 DOCX 产物失败")
            return {"message": "已导出 DOCX", "refresh": "view", "hostEffects": [{
                "type": "download_artifact", "artifactId": artifact["artifactId"], "filename": artifact["filename"],
            }]}
    except Exception as exc:
        if session is not None:
            session["report"] = report_from_result({"ok": False, "error": str(exc)})
        return {"message": str(exc), "refresh": "view"}


def dispose_view(params: dict) -> dict:
    return {"disposed": SESSIONS.pop(str(params.get("sessionId") or ""), None) is not None}


if __name__ == "__main__":
    server.register_handler("plugin.get_view_window", get_view_window)
    server.register_handler("plugin.invoke_action", invoke_action)
    server.register_handler("plugin.dispose_view", dispose_view)
    server.run(render_view, open_view=open_view, shutdown=SESSIONS.clear)
