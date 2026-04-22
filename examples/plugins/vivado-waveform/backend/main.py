from __future__ import annotations

import json
import sys
from pathlib import Path

from vcd_parser import parse_vcd


def render_view(input_payload: dict[str, object]) -> dict[str, object]:
    path = Path(str(input_payload["path"])).resolve()
    parsed = parse_vcd(path)
    return {
        "renderer": "waveform",
        "title": path.name,
        "payload": {
            "path": str(path),
            **parsed,
        },
    }


def write_response(request_id: object, *, result: dict[str, object] | None = None, error: str | None = None) -> None:
    payload: dict[str, object] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = {"code": -32000, "message": error}
    else:
        payload["result"] = result or {}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    try:
        if method == "plugin.initialize":
            write_response(request_id, result={"ok": True, "name": "vivado-waveform"})
        elif method == "plugin.render_view":
            view_input = dict(params.get("input") or {})
            write_response(request_id, result=render_view(view_input))
        elif method == "plugin.shutdown":
            write_response(request_id, result={"ok": True})
        else:
            write_response(request_id, error=f"unsupported method: {method}")
    except Exception as exc:  # pragma: no cover - plugin runtime catches via stdio
        write_response(request_id, error=str(exc))
