from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_sdk import PluginServer


server = PluginServer("plugin-sdk-template")


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少文件路径")
    return {
        "renderer": "document",
        "title": Path(path).name,
        "payload": {"path": path},
    }


if __name__ == "__main__":
    server.run(render_view)

