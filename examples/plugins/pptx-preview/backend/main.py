from __future__ import annotations

from pathlib import Path
from typing import Any

from plugin_sdk import PluginServer
from pptx_parser import parse_pptx_document


server = PluginServer(
    "pptx-preview",
    defaults={"maxSlides": 80, "libreOfficePath": ""},
)


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        current = int(value)
    except (TypeError, ValueError):
        current = default
    return max(minimum, min(maximum, current))


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 PPTX 路径")
    limits = {
        "max_slides": _coerce_int(server.config.get("maxSlides"), 80, 1, 300),
    }
    payload = parse_pptx_document(
        path,
        server.read_bytes(path, error_message="读取 PPTX 失败"),
        write_artifact=lambda filename, content, content_type: server.write_artifact(
            filename,
            content,
            content_type,
            error_message="写入插件图片失败",
        ),
        limits=limits,
        libreoffice_path=str(server.config.get("libreOfficePath") or ""),
    )
    return {
        "renderer": "document",
        "title": str(payload.get("title") or Path(path).name),
        "payload": payload,
    }


if __name__ == "__main__":
    server.run(render_view)
