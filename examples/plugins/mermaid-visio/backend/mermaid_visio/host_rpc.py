from __future__ import annotations

import base64
import json
import sys
from typing import Any

NEXT_REQUEST_ID = 9000


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


def read_workspace_text(path: str) -> str:
    response = call_host("host.workspace.read_text", {"path": path, "encoding": "utf-8"})
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or "读取 Mermaid 文件失败"))
    return str((response.get("result") or {}).get("content") or "")


def write_artifact(filename: str, content: bytes, content_type: str) -> str:
    response = call_host(
        "host.temp.write_artifact",
        {
            "filename": filename,
            "contentBase64": base64.b64encode(content).decode("ascii"),
            "contentType": content_type,
        },
    )
    if response.get("error"):
        raise RuntimeError(str(response["error"].get("message") or "写入导出产物失败"))
    return str((response.get("result") or {}).get("artifactId") or "")
