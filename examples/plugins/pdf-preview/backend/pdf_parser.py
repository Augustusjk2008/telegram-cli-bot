from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def parse_pdf_document(
    path: str,
    content: bytes,
    *,
    write_artifact: Callable[[str, bytes, str], dict[str, Any]],
) -> dict[str, object]:
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise RuntimeError("PDF 需要密码，请先解锁文件后再预览")
        page_count = len(reader.pages)
        title = str((reader.metadata or {}).get("/Title") or "").strip() or Path(path).name
    except PdfReadError as exc:
        raise RuntimeError("PDF 解析失败或文件损坏") from exc
    if not page_count:
        raise RuntimeError("PDF 没有可预览的页面")

    # Keep the original bytes: rebuilding text blocks loses fonts, images and layout.
    artifact = write_artifact(Path(path).name, content, "application/pdf")
    return {
        "path": path,
        "title": title,
        "statsText": f"{page_count} 页",
        "pdf": {"artifactId": artifact["artifactId"]},
        "blocks": [],
    }
