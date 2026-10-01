from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_sdk import PluginServer
from zip_parser import parse_zip_tree


server = PluginServer("zip-preview")


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 ZIP 路径")
    return {
        "renderer": "tree",
        "title": Path(path).name,
        "payload": parse_zip_tree(
            path,
            server.read_bytes(path, error_message="读取 ZIP 失败"),
            server.config,
        ),
    }


if __name__ == "__main__":
    server.run(render_view)
