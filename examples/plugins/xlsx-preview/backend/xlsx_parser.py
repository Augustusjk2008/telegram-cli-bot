from __future__ import annotations

import posixpath
import re
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

SS_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"x": SS_NS, "rel": PKG_REL_NS}
ROW_LIMIT = 40
COL_LIMIT = 12
CELL_REF_RE = re.compile(r"([A-Z]+)")


def _xml(archive: ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        return None


def _normalize_target(target: str) -> str:
    cleaned = str(target or "").strip().replace("\\", "/")
    if not cleaned:
        return ""
    if cleaned.startswith("/"):
        return cleaned.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", cleaned))


def _column_index(cell_ref: str) -> int:
    match = CELL_REF_RE.match(str(cell_ref or "").upper())
    if not match:
        return 0
    result = 0
    for char in match.group(1):
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def _shared_strings(archive: ZipFile) -> list[str]:
    root = _xml(archive, "xl/sharedStrings.xml")
    if root is None:
        return []
    values: list[str] = []
    for item in root.findall("x:si", NS):
        values.append("".join(node.text or "" for node in item.findall(".//x:t", NS)))
    return values


def _sheet_targets(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = _xml(archive, "xl/workbook.xml")
    rels = _xml(archive, "xl/_rels/workbook.xml.rels")
    if workbook is None or rels is None:
        raise RuntimeError("XLSX 缺少工作簿元数据")

    rel_map: dict[str, str] = {}
    for rel in rels.findall("rel:Relationship", NS):
        rel_id = str(rel.attrib.get("Id") or "").strip()
        target = _normalize_target(str(rel.attrib.get("Target") or ""))
        if rel_id and target:
            rel_map[rel_id] = target

    rel_attr = f"{{{DOC_REL_NS}}}id"
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("x:sheets/x:sheet", NS):
        name = str(sheet.attrib.get("name") or "").strip() or "Sheet"
        rel_id = str(sheet.attrib.get(rel_attr) or "").strip()
        target = rel_map.get(rel_id)
        if target:
            sheets.append((name, target))
    return sheets


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = str(cell.attrib.get("t") or "").strip()
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//x:t", NS)).strip()

    value = str(cell.findtext("x:v", default="", namespaces=NS) or "").strip()
    if cell_type == "s" and value.isdigit():
        index = int(value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell_type == "b":
        return "TRUE" if value == "1" else "FALSE"
    return value


def _table_block(row_maps: list[dict[int, str]], width: int) -> dict[str, object]:
    return {
        "type": "table",
        "rows": [
            {
                "cells": [
                    {"runs": [{"text": row_map.get(col, "")}]}
                    for col in range(1, width + 1)
                ],
            }
            for row_map in row_maps
        ],
    }


def parse_xlsx_document(path: str, content: bytes) -> dict[str, object]:
    try:
        with ZipFile(BytesIO(content)) as archive:
            shared_strings = _shared_strings(archive)
            sheets = _sheet_targets(archive)
            blocks: list[dict[str, object]] = []
            previewed_rows = 0

            for sheet_name, target in sheets:
                blocks.append({"type": "heading", "level": 2, "runs": [{"text": sheet_name}]})
                sheet_root = _xml(archive, target)
                row_maps: list[dict[int, str]] = []
                max_width = 0

                if sheet_root is not None:
                    for row in sheet_root.findall("x:sheetData/x:row", NS):
                        row_map: dict[int, str] = {}
                        for cell in row.findall("x:c", NS):
                            col = _column_index(str(cell.attrib.get("r") or ""))
                            if col <= 0:
                                continue
                            row_map[col] = _cell_text(cell, shared_strings)
                            max_width = max(max_width, col)
                        if row_map:
                            row_maps.append(row_map)

                if not row_maps:
                    blocks.append({"type": "paragraph", "runs": [{"text": "工作表为空。"}]})
                    continue

                preview_rows = row_maps[:ROW_LIMIT]
                preview_width = min(max_width or 1, COL_LIMIT)
                previewed_rows += len(preview_rows)
                blocks.append(_table_block(preview_rows, preview_width))

                if len(row_maps) > ROW_LIMIT or max_width > COL_LIMIT:
                    blocks.append({
                        "type": "paragraph",
                        "runs": [{"text": f"仅预览前 {ROW_LIMIT} 行、前 {COL_LIMIT} 列。"}],
                    })

            if not sheets:
                blocks.append({"type": "paragraph", "runs": [{"text": "工作簿为空。"}]})
    except BadZipFile as exc:
        raise RuntimeError("XLSX 文件损坏或格式不支持") from exc
    except ET.ParseError as exc:
        raise RuntimeError("XLSX XML 解析失败") from exc

    return {
        "path": path,
        "title": Path(path).name,
        "statsText": f"{len(sheets)} 工作表 · {previewed_rows} 行预览",
        "blocks": blocks,
    }
