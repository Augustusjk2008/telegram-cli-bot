from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_sdk import PluginServer
from xlsx_parser import parse_xlsx_document


server = PluginServer("xlsx-preview")


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 XLSX 路径")
    payload = parse_xlsx_document(
        path,
        server.read_bytes(path, error_message="读取 XLSX 失败"),
    )
    return {
        "renderer": "document",
        "title": str(payload.get("title") or Path(path).name),
        "payload": payload,
    }


if __name__ == "__main__":
    server.run(render_view)
