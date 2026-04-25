from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

from hex_parser import parse_hex_document

NEXT_REQUEST_ID = 9000
PLUGIN_CONFIG: dict[str, object] = {}


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def respond(request_id: Any, result: dict[str, Any] | None = None, error: str | None = None) -> None:
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
        raise RuntimeError(str(response["error"].get("message") or "读取二进制文件失败"))
    content_base64 = str((response.get("result") or {}).get("contentBase64") or "")
    return base64.b64decode(content_base64.encode("ascii"))


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少文件路径")
    payload = parse_hex_document(path, read_bytes(path), PLUGIN_CONFIG)
    return {
        "renderer": "hex",
        "title": str(payload.get("title") or Path(path).name),
        "payload": payload,
    }


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    try:
        if method == "plugin.initialize":
            context = dict(params.get("context") or {})
            plugin = dict(context.get("plugin") or {})
            PLUGIN_CONFIG.clear()
            PLUGIN_CONFIG.update(dict(plugin.get("config") or {}))
            respond(request_id, {"ok": True, "name": "hex-preview"})
        elif method == "plugin.render_view":
            respond(request_id, render_view(dict(params.get("input") or {})))
        elif method == "plugin.open_view":
            respond(request_id, render_view(dict(params.get("input") or {})))
        elif method == "plugin.shutdown":
            respond(request_id, {"ok": True})
        else:
            respond(request_id, error=f"unsupported method: {method}")
    except Exception as exc:  # pragma: no cover
        respond(request_id, error=str(exc))
