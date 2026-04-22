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


def decode_message(line: bytes | str) -> dict[str, Any]:
    if isinstance(line, bytes):
        text = line.decode("utf-8")
    else:
        text = line
    return json.loads(text)
