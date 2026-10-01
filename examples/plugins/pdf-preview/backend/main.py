from __future__ import annotations

from pathlib import Path
from typing import Any

from pdf_parser import parse_pdf_document
from plugin_sdk import PluginServer


server = PluginServer("pdf-preview")


def render_view(input_payload: dict[str, Any]) -> dict[str, Any]:
    path = str(input_payload.get("path") or "").strip()
    if not path:
        raise RuntimeError("缺少 PDF 路径")
    payload = parse_pdf_document(
        path,
        server.read_bytes(path, error_message="读取 PDF 失败"),
        write_artifact=lambda filename, content, content_type: server.write_artifact(
            filename,
            content,
            content_type,
            error_message="写入 PDF 预览失败",
        ),
    )
    return {
        "renderer": "document",
        "title": str(payload.get("title") or Path(path).name),
        "payload": payload,
    }


if __name__ == "__main__":
    server.run(render_view)
