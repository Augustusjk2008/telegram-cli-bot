from __future__ import annotations

import posixpath
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"p": P_NS, "a": A_NS, "r": R_NS, "rel": REL_NS}
R = f"{{{R_NS}}}"
EMU_PER_INCH = 914400
PX_PER_INCH = 96
DEFAULT_SLIDE_CX = 9144000
DEFAULT_SLIDE_CY = 5143500
MAX_CANVAS_WIDTH_PX = 960
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


def _normalize_target(base_dir: str, target: str) -> str:
    cleaned = str(target or "").strip().replace("\\", "/")
    if not cleaned or "://" in cleaned:
        return ""
    if cleaned.startswith("/"):
        normalized = posixpath.normpath(cleaned.lstrip("/"))
    else:
        normalized = posixpath.normpath(posixpath.join(base_dir, cleaned))
    if normalized.startswith("../"):
        return ""
    return normalized


def _relationships(root: ET.Element | None, base_dir: str) -> dict[str, dict[str, str]]:
    if root is None:
        return {}
    result: dict[str, dict[str, str]] = {}
    for rel in root.findall("rel:Relationship", NS):
        rel_id = str(rel.attrib.get("Id") or "").strip()
        rel_type = str(rel.attrib.get("Type") or "").strip()
        target_mode = str(rel.attrib.get("TargetMode") or "").strip().lower()
        if not rel_id or target_mode == "external":
            continue
        target = _normalize_target(base_dir, str(rel.attrib.get("Target") or ""))
        if not target:
            continue
        result[rel_id] = {"type": rel_type, "target": target}
    return result


def _theme_colors(theme_root: ET.Element | None) -> dict[str, str]:
    if theme_root is None:
        return {}
    scheme = theme_root.find(".//a:clrScheme", NS)
    if scheme is None:
        return {}
    result: dict[str, str] = {}
    for node in list(scheme):
        local = node.tag.split("}", 1)[-1]
        srgb = node.find("a:srgbClr", NS)
        if srgb is not None:
            value = str(srgb.attrib.get("val") or "").strip()
            if value:
                result[local] = f"#{value.upper()}"
                continue
        sys_clr = node.find("a:sysClr", NS)
        if sys_clr is not None:
            value = str(sys_clr.attrib.get("lastClr") or "").strip()
            if value:
                result[local] = f"#{value.upper()}"
    return result


def _hex_color(value: str) -> str:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        return f"#{text.upper()}"
    return ""


def _color(node: ET.Element | None, theme_colors: dict[str, str]) -> str:
    if node is None:
        return ""
    srgb = node.find("a:srgbClr", NS)
    if srgb is not None:
        return _hex_color(str(srgb.attrib.get("val") or ""))
    scheme = node.find("a:schemeClr", NS)
    if scheme is not None:
        return theme_colors.get(str(scheme.attrib.get("val") or "").strip(), "")
    return ""


def _frame(xfrm: ET.Element | None, scale: float) -> dict[str, int] | None:
    if xfrm is None:
        return None
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    if off is None or ext is None:
        return None
    try:
        x = round(int(off.attrib.get("x") or "0") * scale)
        y = round(int(off.attrib.get("y") or "0") * scale)
        width = max(1, round(int(ext.attrib.get("cx") or "0") * scale))
        height = max(1, round(int(ext.attrib.get("cy") or "0") * scale))
    except ValueError:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _paragraph_align(paragraph: ET.Element) -> str:
    current = paragraph.find("a:pPr", NS)
    if current is None:
        return ""
    mapping = {"ctr": "center", "r": "right", "just": "left", "l": "left"}
    return mapping.get(str(current.attrib.get("algn") or "").strip(), "")


def _paragraph_level(paragraph: ET.Element) -> int:
    current = paragraph.find("a:pPr", NS)
    if current is None:
        return 0
    try:
        return max(0, int(current.attrib.get("lvl") or "0"))
    except ValueError:
        return 0


def _paragraph_bullet(paragraph: ET.Element) -> str:
    current = paragraph.find("a:pPr", NS)
    if current is None:
        return ""
    bullet = current.find("a:buChar", NS)
    if bullet is not None:
        return str(bullet.attrib.get("char") or "").strip()
    if current.find("a:buAutoNum", NS) is not None:
        return "1."
    return ""


def _text_runs(paragraph: ET.Element, theme_colors: dict[str, str]) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    for node in list(paragraph):
        if node.tag == f"{{{A_NS}}}r":
            text = "".join(child.text or "" for child in node.findall("a:t", NS))
            if not text:
                continue
            props = node.find("a:rPr", NS)
            payload: dict[str, object] = {"text": text}
            if props is not None:
                if str(props.attrib.get("b") or "") == "1":
                    payload["bold"] = True
                if str(props.attrib.get("i") or "") == "1":
                    payload["italic"] = True
                underline = str(props.attrib.get("u") or "").strip().lower()
                if underline and underline != "none":
                    payload["underline"] = True
                color = _color(props.find("a:solidFill", NS), theme_colors)
                if color:
                    payload["color"] = color
                size = str(props.attrib.get("sz") or "").strip()
                if size.isdigit():
                    payload["fontSizePx"] = max(1, round(int(size) / 100 * PX_PER_INCH / 72))
            runs.append(payload)
            continue
        if node.tag == f"{{{A_NS}}}br":
            runs.append({"text": "\n"})
            continue
        if node.tag == f"{{{A_NS}}}fld":
            text = "".join(child.text or "" for child in node.findall("a:t", NS))
            if text:
                runs.append({"text": text})
    if not runs:
        end_para = paragraph.find("a:endParaRPr", NS)
        if end_para is not None and paragraph.find("a:br", NS) is not None:
            runs.append({"text": "\n"})
    return runs


def _plain_text_from_paragraphs(paragraphs: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for paragraph in paragraphs:
        runs = paragraph.get("runs") or []
        text = "".join(str(run.get("text") or "") for run in runs if isinstance(run, dict)).strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _artifact_payload(artifact: dict[str, object], filename: str, content_type: str) -> dict[str, object] | None:
    artifact_id = str(artifact.get("artifactId") or "")
    if not artifact_id:
        return None
    return {
        "artifactId": artifact_id,
        "filename": str(artifact.get("filename") or filename),
        "contentType": str(artifact.get("contentType") or content_type),
    }


def _image_payload(
    archive: ZipFile,
    target: str,
    content_types: dict[str, str],
    write_artifact: ArtifactWriter | None,
) -> dict[str, object] | None:
    if write_artifact is None:
        return None
    try:
        content = archive.read(target)
    except KeyError:
        return None
    filename = posixpath.basename(target)
    suffix = Path(filename).suffix.lower()
    content_type = content_types.get(suffix) or IMAGE_CONTENT_TYPES.get(suffix) or "application/octet-stream"
    artifact = write_artifact(filename, content, content_type)
    return _artifact_payload(artifact, filename, content_type)


def _slide_background_from_root(
    root: ET.Element | None,
    theme_colors: dict[str, str],
    rels: dict[str, dict[str, str]],
    archive: ZipFile,
    content_types: dict[str, str],
    write_artifact: ArtifactWriter | None,
) -> dict[str, object] | None:
    if root is None:
        return None
    background = root.find("p:cSld/p:bg", NS)
    if background is None:
        return None
    payload: dict[str, object] = {}
    bg_pr = background.find("p:bgPr", NS)
    if bg_pr is not None:
        fill = bg_pr.find("a:solidFill", NS)
        color = _color(fill, theme_colors)
        if color:
            payload["color"] = color
        blip = bg_pr.find("a:blipFill/a:blip", NS)
        if blip is not None:
            rel_id = str(blip.attrib.get(R + "embed") or "").strip()
            target = str((rels.get(rel_id) or {}).get("target") or "")
            image = _image_payload(archive, target, content_types, write_artifact) if target else None
            if image is not None:
                payload["image"] = image
    if "color" not in payload:
        bg_ref = background.find("p:bgRef", NS)
        if bg_ref is not None:
            color = _color(bg_ref, theme_colors)
            if color:
                payload["color"] = color
    return payload or None


def _slide_background(
    slide_root: ET.Element | None,
    slide_rels: dict[str, dict[str, str]],
    archive: ZipFile,
    content_types: dict[str, str],
    theme_colors: dict[str, str],
    write_artifact: ArtifactWriter | None,
) -> dict[str, object]:
    for current_root, current_rels in ((slide_root, slide_rels),):
        payload = _slide_background_from_root(
            current_root,
            theme_colors,
            current_rels,
            archive,
            content_types,
            write_artifact,
        )
        if payload:
            if "color" not in payload:
                payload["color"] = "#FFFFFF"
            return payload

    layout_target = next(
        (
            rel["target"]
            for rel in slide_rels.values()
            if rel.get("type", "").endswith("/slideLayout")
        ),
        "",
    )
    if layout_target:
        layout_root = _xml(archive, layout_target)
        layout_rels = _relationships(
            _xml(archive, f"{posixpath.dirname(layout_target)}/_rels/{posixpath.basename(layout_target)}.rels"),
            posixpath.dirname(layout_target),
        )
        payload = _slide_background_from_root(
            layout_root,
            theme_colors,
            layout_rels,
            archive,
            content_types,
            write_artifact,
        )
        if payload:
            if "color" not in payload:
                payload["color"] = "#FFFFFF"
            return payload

        master_target = next(
            (
                rel["target"]
                for rel in layout_rels.values()
                if rel.get("type", "").endswith("/slideMaster")
            ),
            "",
        )
        if master_target:
            master_root = _xml(archive, master_target)
            master_rels = _relationships(
                _xml(archive, f"{posixpath.dirname(master_target)}/_rels/{posixpath.basename(master_target)}.rels"),
                posixpath.dirname(master_target),
            )
            payload = _slide_background_from_root(
                master_root,
                theme_colors,
                master_rels,
                archive,
                content_types,
                write_artifact,
            )
            if payload:
                if "color" not in payload:
                    payload["color"] = "#FFFFFF"
                return payload
            _ = master_rels
    return {"color": "#FFFFFF"}


def _text_item(
    shape: ET.Element,
    scale: float,
    width_px: int,
    fallback_index: int,
    theme_colors: dict[str, str],
    z_index: int,
) -> tuple[dict[str, object] | None, str]:
    text_body = shape.find("p:txBody", NS)
    if text_body is None:
        return None, ""
    paragraphs: list[dict[str, object]] = []
    for paragraph in text_body.findall("a:p", NS):
        runs = _text_runs(paragraph, theme_colors)
        if not runs:
            continue
        payload: dict[str, object] = {"runs": runs}
        bullet = _paragraph_bullet(paragraph)
        level = _paragraph_level(paragraph)
        align = _paragraph_align(paragraph)
        if bullet:
            payload["bullet"] = bullet
        if level:
            payload["level"] = level
        if align:
            payload["align"] = align
        paragraphs.append(payload)
    if not paragraphs:
        return None, ""
    frame = _frame(shape.find("p:spPr/a:xfrm", NS), scale)
    if frame is None:
        frame = {"x": 32, "y": 32 + fallback_index * 48, "width": max(1, width_px - 64), "height": 44}
    return {
        "type": "text",
        "frame": frame,
        "paragraphs": paragraphs,
        "zIndex": z_index,
    }, _plain_text_from_paragraphs(paragraphs)


def _image_item(
    picture: ET.Element,
    slide_rels: dict[str, dict[str, str]],
    archive: ZipFile,
    content_types: dict[str, str],
    write_artifact: ArtifactWriter | None,
    scale: float,
    z_index: int,
) -> dict[str, object] | None:
    blip = picture.find("p:blipFill/a:blip", NS)
    rel_id = str(blip.attrib.get(R + "embed") or "").strip() if blip is not None else ""
    target = str((slide_rels.get(rel_id) or {}).get("target") or "")
    image = _image_payload(archive, target, content_types, write_artifact) if target else None
    frame = _frame(picture.find("p:spPr/a:xfrm", NS), scale)
    if image is None or frame is None:
        return None
    c_nv_pr = picture.find("p:nvPicPr/p:cNvPr", NS)
    payload = {
        **image,
        "alt": str(c_nv_pr.attrib.get("descr") or "").strip() if c_nv_pr is not None else "",
        "title": str(c_nv_pr.attrib.get("name") or "").strip() if c_nv_pr is not None else "",
        "widthPx": frame["width"],
        "heightPx": frame["height"],
    }
    return {
        "type": "image",
        "frame": frame,
        "image": payload,
        "zIndex": z_index,
    }


def _table_runs(container: ET.Element, theme_colors: dict[str, str]) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    for index, paragraph in enumerate(container.findall("a:p", NS)):
        paragraph_runs = _text_runs(paragraph, theme_colors)
        if not paragraph_runs:
            continue
        if runs and index > 0:
            runs.append({"text": "\n"})
        runs.extend(paragraph_runs)
    return runs or [{"text": ""}]


def _table_item(
    frame_node: ET.Element,
    scale: float,
    theme_colors: dict[str, str],
    z_index: int,
) -> dict[str, object] | None:
    table = frame_node.find("a:graphic/a:graphicData/a:tbl", NS)
    if table is None:
        return None
    frame = _frame(frame_node.find("p:xfrm", NS), scale)
    if frame is None:
        return None
    rows: list[dict[str, object]] = []
    for row in table.findall("a:tr", NS):
        cells: list[dict[str, object]] = []
        for cell in row.findall("a:tc", NS):
            text_body = cell.find("a:txBody", NS)
            cells.append({"runs": _table_runs(text_body, theme_colors) if text_body is not None else [{"text": ""}]})
        rows.append({"cells": cells})
    return {
        "type": "table",
        "frame": frame,
        "rows": rows,
        "zIndex": z_index,
    }


def _unsupported_item(frame_node: ET.Element, scale: float, z_index: int) -> dict[str, object] | None:
    frame = _frame(frame_node.find("p:xfrm", NS), scale)
    if frame is None:
        return None
    return {
        "type": "unsupported",
        "frame": frame,
        "label": "暂不支持的图表或 SmartArt",
        "zIndex": z_index,
    }


def _office_document_path(archive: ZipFile) -> str:
    root_rels = _relationships(_xml(archive, "_rels/.rels"), "")
    for rel in root_rels.values():
        if rel.get("type", "").endswith("/officeDocument"):
            return rel.get("target", "")
    return "ppt/presentation.xml"


def parse_pptx_document(
    path: str,
    content: bytes,
    *,
    write_artifact: ArtifactWriter | None = None,
    limits: dict[str, int] | None = None,
) -> dict[str, object]:
    current_limits = limits or {}
    max_slides = max(1, int(current_limits.get("max_slides", 80) or 80))
    max_items_per_slide = max(20, int(current_limits.get("max_items_per_slide", 240) or 240))
    try:
        with ZipFile(BytesIO(content)) as archive:
            presentation_path = _office_document_path(archive) or "ppt/presentation.xml"
            presentation_root = _xml(archive, presentation_path)
            if presentation_root is None:
                raise RuntimeError("PPTX 缺少 ppt/presentation.xml")

            theme_colors = _theme_colors(_xml(archive, "ppt/theme/theme1.xml"))
            content_types = _content_types(_xml(archive, "[Content_Types].xml"))
            size_node = presentation_root.find("p:sldSz", NS)
            try:
                slide_cx = int(size_node.attrib.get("cx") or str(DEFAULT_SLIDE_CX)) if size_node is not None else DEFAULT_SLIDE_CX
                slide_cy = int(size_node.attrib.get("cy") or str(DEFAULT_SLIDE_CY)) if size_node is not None else DEFAULT_SLIDE_CY
            except ValueError:
                slide_cx = DEFAULT_SLIDE_CX
                slide_cy = DEFAULT_SLIDE_CY
            scale = MAX_CANVAS_WIDTH_PX / max(1, slide_cx)
            width_px = MAX_CANVAS_WIDTH_PX
            height_px = max(1, round(slide_cy * scale))

            presentation_dir = posixpath.dirname(presentation_path)
            rels_path = f"{presentation_dir}/_rels/{posixpath.basename(presentation_path)}.rels"
            presentation_rels = _relationships(_xml(archive, rels_path), presentation_dir)
            slide_targets: list[str] = []
            for slide_id in presentation_root.findall("p:sldIdLst/p:sldId", NS):
                rel_id = str(slide_id.attrib.get(R + "id") or "").strip()
                target = str((presentation_rels.get(rel_id) or {}).get("target") or "")
                if target:
                    slide_targets.append(target)
            if not slide_targets:
                raise RuntimeError("PPTX 未找到幻灯片")

            slide_count = min(len(slide_targets), max_slides)
            text_count = 0
            image_count = 0
            table_count = 0
            blocks: list[dict[str, object]] = []

            for slide_number, slide_target in enumerate(slide_targets[:max_slides], start=1):
                slide_root = _xml(archive, slide_target)
                if slide_root is None:
                    continue
                slide_dir = posixpath.dirname(slide_target)
                slide_rels = _relationships(
                    _xml(archive, f"{slide_dir}/_rels/{posixpath.basename(slide_target)}.rels"),
                    slide_dir,
                )
                background = _slide_background(
                    slide_root,
                    slide_rels,
                    archive,
                    content_types,
                    theme_colors,
                    write_artifact,
                )
                shape_tree = slide_root.find("p:cSld/p:spTree", NS)
                items: list[dict[str, object]] = []
                slide_title = ""
                fallback_index = 0
                if shape_tree is not None:
                    for z_index, child in enumerate(list(shape_tree)):
                        if len(items) >= max_items_per_slide:
                            break
                        if child.tag == f"{{{P_NS}}}sp":
                            item, plain_text = _text_item(
                                child,
                                scale,
                                width_px,
                                fallback_index,
                                theme_colors,
                                z_index,
                            )
                            if item is None:
                                continue
                            fallback_index += 1
                            text_count += 1
                            if not slide_title:
                                slide_title = plain_text
                            items.append(item)
                            continue
                        if child.tag == f"{{{P_NS}}}pic":
                            item = _image_item(
                                child,
                                slide_rels,
                                archive,
                                content_types,
                                write_artifact,
                                scale,
                                z_index,
                            )
                            if item is None:
                                continue
                            image_count += 1
                            items.append(item)
                            continue
                        if child.tag == f"{{{P_NS}}}graphicFrame":
                            table_item = _table_item(child, scale, theme_colors, z_index)
                            if table_item is not None:
                                table_count += 1
                                items.append(table_item)
                                continue
                            if len(items) < max_items_per_slide:
                                unsupported = _unsupported_item(child, scale, z_index)
                                if unsupported is not None:
                                    items.append(unsupported)

                blocks.append(
                    {
                        "type": "slide",
                        "slideNumber": slide_number,
                        "title": slide_title,
                        "widthPx": width_px,
                        "heightPx": height_px,
                        "background": background,
                        "items": items,
                    }
                )

            truncated = len(slide_targets) - slide_count
            if truncated > 0:
                blocks.append(
                    {
                        "type": "paragraph",
                        "runs": [{"text": f"仅预览前 {slide_count} 页，剩余 {truncated} 页未展示。"}],
                    }
                )
    except BadZipFile as exc:
        raise RuntimeError("PPTX 文件损坏或格式不支持") from exc
    except ET.ParseError as exc:
        raise RuntimeError("PPTX XML 解析失败") from exc

    return {
        "path": path,
        "title": Path(path).name,
        "statsText": f"{slide_count} 页 · {text_count} 文本 · {image_count} 图片 · {table_count} 表格",
        "blocks": blocks,
    }
