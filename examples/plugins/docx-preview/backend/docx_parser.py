from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
W = f"{{{W_NS}}}"
HEADING_PATTERN = re.compile(r"^heading[\s_-]*(\d+)$", re.IGNORECASE)


def _xml(archive: ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        return None


def _heading_level(value: str, mapping: dict[str, int]) -> int | None:
    if value in mapping:
        return max(1, min(6, mapping[value]))
    match = HEADING_PATTERN.match(str(value or "").strip())
    if not match:
        return None
    return max(1, min(6, int(match.group(1))))


def _heading_styles(styles_root: ET.Element | None) -> dict[str, int]:
    mapping: dict[str, int] = {}
    if styles_root is None:
        return mapping
    for style in styles_root.findall("w:style", NS):
        style_id = str(style.attrib.get(f"{W}styleId") or "").strip()
        if not style_id:
            continue
        level = _heading_level(style_id, {})
        if level is None:
            name_node = style.find("w:name", NS)
            level = _heading_level(
                str(name_node.attrib.get(f"{W}val") or "").strip() if name_node is not None else "",
                {},
            )
        if level is not None:
            mapping[style_id] = level
    return mapping


def _numbering(numbering_root: ET.Element | None) -> dict[tuple[str, str], dict[str, object]]:
    if numbering_root is None:
        return {}
    abstract_formats: dict[tuple[str, str], str] = {}
    for abstract in numbering_root.findall("w:abstractNum", NS):
        abstract_id = str(abstract.attrib.get(f"{W}abstractNumId") or "")
        for level in abstract.findall("w:lvl", NS):
            ilvl = str(level.attrib.get(f"{W}ilvl") or "0")
            fmt = level.find("w:numFmt", NS)
            abstract_formats[(abstract_id, ilvl)] = str(fmt.attrib.get(f"{W}val") or "bullet") if fmt is not None else "bullet"

    num_to_abstract: dict[str, str] = {}
    for num in numbering_root.findall("w:num", NS):
        num_id = str(num.attrib.get(f"{W}numId") or "")
        abstract = num.find("w:abstractNumId", NS)
        num_to_abstract[num_id] = str(abstract.attrib.get(f"{W}val") or "") if abstract is not None else ""

    result: dict[tuple[str, str], dict[str, object]] = {}
    for (abstract_id, ilvl), fmt in abstract_formats.items():
        ordered = fmt not in {"bullet", "none"}
        marker = "1." if ordered else "•"
        for num_id, current_abstract in num_to_abstract.items():
            if current_abstract == abstract_id:
                result[(num_id, ilvl)] = {"ordered": ordered, "marker": marker}
    return result


def _runs(parent: ET.Element) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    for run in parent.findall("w:r", NS):
        parts: list[str] = []
        for node in list(run):
            if node.tag == f"{W}t":
                parts.append(node.text or "")
            elif node.tag == f"{W}tab":
                parts.append("\t")
            elif node.tag in {f"{W}br", f"{W}cr"}:
                parts.append("\n")
        text = "".join(parts)
        if not text:
            continue
        props = run.find("w:rPr", NS)
        payload: dict[str, object] = {"text": text}
        if props is not None and props.find("w:b", NS) is not None:
            payload["bold"] = True
        if props is not None and props.find("w:i", NS) is not None:
            payload["italic"] = True
        if props is not None and props.find("w:u", NS) is not None:
            payload["underline"] = True
        runs.append(payload)
    return runs


def _paragraph(
    paragraph: ET.Element,
    heading_styles: dict[str, int],
    numbering: dict[tuple[str, str], dict[str, object]],
) -> dict[str, object] | None:
    runs = _runs(paragraph)
    if not runs:
        return None

    props = paragraph.find("w:pPr", NS)
    style = props.find("w:pStyle", NS) if props is not None else None
    style_id = str(style.attrib.get(f"{W}val") or "").strip() if style is not None else ""
    heading_level = _heading_level(style_id, heading_styles)
    if heading_level is not None:
        return {"type": "heading", "level": heading_level, "runs": runs}

    num_props = props.find("w:numPr", NS) if props is not None else None
    if num_props is not None:
        ilvl_node = num_props.find("w:ilvl", NS)
        num_id_node = num_props.find("w:numId", NS)
        ilvl = str(ilvl_node.attrib.get(f"{W}val") or "0") if ilvl_node is not None else "0"
        num_id = str(num_id_node.attrib.get(f"{W}val") or "") if num_id_node is not None else ""
        info = numbering.get((num_id, ilvl), {"ordered": False, "marker": "•"})
        return {
            "type": "list_item",
            "ordered": bool(info.get("ordered")),
            "depth": max(0, int(ilvl)),
            "marker": str(info.get("marker") or "•"),
            "runs": runs,
        }

    return {"type": "paragraph", "runs": runs}


def _table(table: ET.Element) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for row in table.findall("w:tr", NS):
        cells: list[dict[str, object]] = []
        for cell in row.findall("w:tc", NS):
            cell_runs: list[dict[str, object]] = []
            for paragraph in cell.findall("w:p", NS):
                paragraph_runs = _runs(paragraph)
                if not paragraph_runs:
                    continue
                if cell_runs:
                    cell_runs.append({"text": "\n"})
                cell_runs.extend(paragraph_runs)
            cells.append({"runs": cell_runs or [{"text": ""}]})
        rows.append({"cells": cells})
    return {"type": "table", "rows": rows}


def parse_docx_document(path: str, content: bytes) -> dict[str, object]:
    try:
        with ZipFile(BytesIO(content)) as archive:
            document_root = _xml(archive, "word/document.xml")
            if document_root is None:
                raise RuntimeError("DOCX 缺少 word/document.xml")

            body = document_root.find("w:body", NS)
            if body is None:
                raise RuntimeError("DOCX body 为空")

            heading_styles = _heading_styles(_xml(archive, "word/styles.xml"))
            numbering = _numbering(_xml(archive, "word/numbering.xml"))

            blocks: list[dict[str, object]] = []
            paragraph_count = 0
            table_count = 0
            for child in list(body):
                if child.tag == f"{W}p":
                    block = _paragraph(child, heading_styles, numbering)
                    if block is None:
                        continue
                    paragraph_count += 1
                    blocks.append(block)
                    continue
                if child.tag == f"{W}tbl":
                    table_count += 1
                    blocks.append(_table(child))
    except BadZipFile as exc:
        raise RuntimeError("DOCX 文件损坏或格式不支持") from exc
    except ET.ParseError as exc:
        raise RuntimeError("DOCX XML 解析失败") from exc

    title = next(
        (
            "".join(str(run.get("text") or "") for run in block.get("runs", []))
            for block in blocks
            if block.get("type") == "heading"
        ),
        Path(path).name,
    )
    return {
        "path": path,
        "title": title,
        "statsText": f"{paragraph_count} 段 · {table_count} 表格",
        "blocks": blocks,
    }
