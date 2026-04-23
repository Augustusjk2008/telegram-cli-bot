from __future__ import annotations

import json
from typing import Any


def encode_request(request_id: int, method: str, params: dict[str, Any]) -> bytes:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def encode_result(request_id: int, result: dict[str, Any]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, ensure_ascii=False) + "\n").encode("utf-8")


def encode_error(request_id: int, message: str, *, code: int = -32000, data: Any = None) -> bytes:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if data is not None:
        payload["error"]["data"] = data
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def decode_message(line: bytes | str) -> dict[str, Any]:
    if isinstance(line, bytes):
        text = line.decode("utf-8")
    else:
        text = line
    return json.loads(text)


def unwrap_result(message: dict[str, Any]) -> dict[str, Any]:
    error = message.get("error")
    if error:
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "插件执行失败")
        else:
            detail = str(error)
        raise RuntimeError(detail)
    result = message.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("插件 result 不是对象")
    return dict(result)
