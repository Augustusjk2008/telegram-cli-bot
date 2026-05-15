from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS = {"w": W_NS, "r": R_NS, "a": A_NS, "wp": WP_NS}
W = f"{{{W_NS}}}"
R = f"{{{R_NS}}}"
HEADING_PATTERN = re.compile(r"^heading[\s_-]*(\d+)$", re.IGNORECASE)
EMU_PER_PIXEL = 9525
IMAGE_CONTENT_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}
ArtifactWriter = Callable[[str, bytes, str], dict[str, object]]


def _xml(archive: ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        return None


def _content_types(root: ET.Element | None) -> dict[str, str]:
    if root is None:
        return {}
    result: dict[str, str] = {}
    for node in list(root):
        if node.tag.endswith("Default"):
            ext = str(node.attrib.get("Extension") or "").strip().lower()
            content_type = str(node.attrib.get("ContentType") or "").strip()
            if ext and content_type:
                result[f".{ext}"] = content_type
    return result


def _document_relationships(root: ET.Element | None) -> dict[str, str]:
    if root is None:
        return {}
    result: dict[str, str] = {}
    for rel in list(root):
        rel_id = str(rel.attrib.get("Id") or "").strip()
        target = str(rel.attrib.get("Target") or "").strip()
        rel_type = str(rel.attrib.get("Type") or "")
        target_mode = str(rel.attrib.get("TargetMode") or "").lower()
        if not rel_id or not target or target_mode == "external":
            continue
        if not rel_type.endswith("/image"):
            continue
        normalized = posixpath.normpath(posixpath.join("word", target)).lstrip("/")
        if normalized.startswith("../"):
            continue
        result[rel_id] = normalized
    return result


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


def _image_size_px(inline: ET.Element | None) -> tuple[int | None, int | None]:
    extent = inline.find("wp:extent", NS) if inline is not None else None
    if extent is None:
        return None, None
    try:
        width = round(int(extent.attrib.get("cx") or "0") / EMU_PER_PIXEL)
        height = round(int(extent.attrib.get("cy") or "0") / EMU_PER_PIXEL)
    except ValueError:
        return None, None
    return (width or None), (height or None)


def _image_alt_title(inline: ET.Element | None) -> tuple[str, str]:
    doc_pr = inline.find("wp:docPr", NS) if inline is not None else None
    if doc_pr is None:
        return "", ""
    return str(doc_pr.attrib.get("descr") or "").strip(), str(doc_pr.attrib.get("name") or "").strip()


def _image_blocks(
    run: ET.Element,
    archive: ZipFile,
    relationships: dict[str, str],
    content_types: dict[str, str],
    write_artifact: ArtifactWriter | None,
) -> list[dict[str, object]]:
    if write_artifact is None:
        return []
    blocks: list[dict[str, object]] = []
    for drawing in run.findall("w:drawing", NS):
        inline = drawing.find("wp:inline", NS)
        if inline is None:
            inline = drawing.find("wp:anchor", NS)
        for blip in drawing.findall(".//a:blip", NS):
            rel_id = str(blip.attrib.get(f"{R}embed") or "").strip()
            target = relationships.get(rel_id)
            if not target:
                continue
            try:
                content = archive.read(target)
            except KeyError:
                continue
            filename = posixpath.basename(target)
            suffix = Path(filename).suffix.lower()
            content_type = content_types.get(suffix) or IMAGE_CONTENT_TYPES.get(suffix) or "application/octet-stream"
            artifact = write_artifact(filename, content, content_type)
            artifact_id = str(artifact.get("artifactId") or "")
            if not artifact_id:
                continue
            width, height = _image_size_px(inline)
            alt, title = _image_alt_title(inline)
            block: dict[str, object] = {
                "type": "image",
                "artifactId": artifact_id,
                "filename": str(artifact.get("filename") or filename),
                "contentType": str(artifact.get("contentType") or content_type),
            }
            if alt:
                block["alt"] = alt
            if title:
                block["title"] = title
            if width is not None:
                block["widthPx"] = width
            if height is not None:
                block["heightPx"] = height
            blocks.append(block)
    return blocks


def _paragraph(
    paragraph: ET.Element,
    heading_styles: dict[str, int],
    numbering: dict[tuple[str, str], dict[str, object]],
    archive: ZipFile,
    relationships: dict[str, str],
    content_types: dict[str, str],
    write_artifact: ArtifactWriter | None,
) -> list[dict[str, object]]:
    image_blocks: list[dict[str, object]] = []
    for run in paragraph.findall("w:r", NS):
        image_blocks.extend(_image_blocks(run, archive, relationships, content_types, write_artifact))

    runs = _runs(paragraph)
    if not runs:
        return image_blocks

    props = paragraph.find("w:pPr", NS)
    style = props.find("w:pStyle", NS) if props is not None else None
    style_id = str(style.attrib.get(f"{W}val") or "").strip() if style is not None else ""
    heading_level = _heading_level(style_id, heading_styles)
    if heading_level is not None:
        return [{"type": "heading", "level": heading_level, "runs": runs}, *image_blocks]

    num_props = props.find("w:numPr", NS) if props is not None else None
    if num_props is not None:
        ilvl_node = num_props.find("w:ilvl", NS)
        num_id_node = num_props.find("w:numId", NS)
        ilvl = str(ilvl_node.attrib.get(f"{W}val") or "0") if ilvl_node is not None else "0"
        num_id = str(num_id_node.attrib.get(f"{W}val") or "") if num_id_node is not None else ""
        info = numbering.get((num_id, ilvl), {"ordered": False, "marker": "•"})
        return [
            {
                "type": "list_item",
                "ordered": bool(info.get("ordered")),
                "depth": max(0, int(ilvl)),
                "marker": str(info.get("marker") or "•"),
                "runs": runs,
            },
            *image_blocks,
        ]

    return [{"type": "paragraph", "runs": runs}, *image_blocks]


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


def parse_docx_document(
    path: str,
    content: bytes,
    *,
    write_artifact: ArtifactWriter | None = None,
) -> dict[str, object]:
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
            content_types = _content_types(_xml(archive, "[Content_Types].xml"))
            relationships = _document_relationships(_xml(archive, "word/_rels/document.xml.rels"))

            blocks: list[dict[str, object]] = []
            paragraph_count = 0
            table_count = 0
            for child in list(body):
                if child.tag == f"{W}p":
                    paragraph_blocks = _paragraph(
                        child,
                        heading_styles,
                        numbering,
                        archive,
                        relationships,
                        content_types,
                        write_artifact,
                    )
                    if not paragraph_blocks:
                        continue
                    paragraph_count += 1
                    blocks.extend(paragraph_blocks)
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
    image_count = sum(1 for block in blocks if block.get("type") == "image")
    return {
        "path": path,
        "title": title,
        "statsText": f"{paragraph_count} 段 · {table_count} 表格 · {image_count} 图片",
        "blocks": blocks,
    }
