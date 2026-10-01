from __future__ import annotations

from pathlib import Path
from typing import Any

from hex_parser import parse_hex_document
from plugin_sdk import PluginServer


server = PluginServer("hex-preview")


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少文件路径")
    payload = parse_hex_document(
        path,
        server.read_bytes(path, error_message="读取二进制文件失败"),
        server.config,
    )
    return {
        "renderer": "hex",
        "title": str(payload.get("title") or Path(path).name),
        "payload": payload,
    }


if __name__ == "__main__":
    server.run(render_view)
