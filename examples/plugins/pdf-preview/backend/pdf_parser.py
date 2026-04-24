from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MULTI_SPACE_RE = re.compile(r"[ \t]+")


def _normalize_line(value: str) -> str:
    return MULTI_SPACE_RE.sub(" ", str(value or "")).strip()


def _paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "runs": [{"text": text}]}


def _heading(text: str, level: int = 1) -> dict[str, Any]:
    return {"type": "heading", "level": level, "runs": [{"text": text}]}


def _paragraphs_from_text(text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = _normalize_line(raw_line)
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _metadata_title(reader: PdfReader) -> str:
    metadata = reader.metadata
    if metadata is None:
        return ""
    title = getattr(metadata, "title", None)
    if not title and isinstance(metadata, dict):
        title = metadata.get("/Title")
    return str(title or "").strip()


def _extract_page_text(page: Any) -> str:
    try:
        return str(page.extract_text(extraction_mode="layout") or "")
    except TypeError:
        return str(page.extract_text() or "")


def parse_pdf_document(path: str, content: bytes) -> dict[str, object]:
    try:
        reader = PdfReader(BytesIO(content))
    except PdfReadError as exc:
        raise RuntimeError("PDF 解析失败或文件损坏") from exc

    raw_paragraphs: list[str] = []
    for page in reader.pages:
        extracted = _extract_page_text(page)
        raw_paragraphs.extend(_paragraphs_from_text(extracted))

    title = _metadata_title(reader) or (raw_paragraphs[0] if raw_paragraphs else Path(path).name)
    blocks: list[dict[str, Any]] = []

    if raw_paragraphs:
        if raw_paragraphs[0] == title:
            blocks.append(_heading(title))
            raw_paragraphs = raw_paragraphs[1:]
        else:
            blocks.append(_heading(title))
        blocks.extend(_paragraph(paragraph) for paragraph in raw_paragraphs)
    else:
        blocks.append(_paragraph("未检测到可提取文字层，可能是扫描版 PDF。"))

    return {
        "path": path,
        "title": title,
        "statsText": f"{len(reader.pages)} 页 · {len(raw_paragraphs)} 段",
        "blocks": blocks,
    }
