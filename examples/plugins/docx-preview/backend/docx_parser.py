from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from docx_formatting import Formatting, attr, child, integer, merge, on_off

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS = {"w": W_NS, "r": R_NS, "a": A_NS, "wp": WP_NS}
W = f"{{{W_NS}}}"
R = f"{{{R_NS}}}"
HEADING_PATTERN = re.compile(r"^heading[\s_-]*(\d+)$", re.IGNORECASE)
EMU_PER_PIXEL = 9525
MAX_GRID_COUNT = 1000
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_BLOCKS = 10_000
MAX_IMAGES = 100
MAX_IMAGE_BYTES = 32 * 1024 * 1024
DEFAULT_SECTION_BLOCKS = 200
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


class ParseBudget:
    def __init__(self, *, artifact_limits: dict[str, int] | None = None, reuse_images: bool = False):
        limits = artifact_limits or {}
        self.max_blocks = MAX_BLOCKS
        self.max_images = MAX_IMAGES
        self.max_image_bytes = min(MAX_IMAGE_BYTES, int(limits.get("artifactBytes", MAX_IMAGE_BYTES)))
        self.max_artifacts = min(MAX_IMAGES, int(limits.get("artifactCount", MAX_IMAGES)))
        self.max_total_image_bytes = min(MAX_UNCOMPRESSED_BYTES, int(limits.get("totalArtifactBytes", MAX_UNCOMPRESSED_BYTES)))
        self.reuse_images = reuse_images
        self.image_targets: set[str] = set()
        self.artifacts = 0
        self.total_image_bytes = 0
        self.blocks = 0
        self.images = 0

    def add_blocks(self, count: int) -> None:
        self.blocks += max(0, int(count))
        if self.blocks > self.max_blocks:
            raise RuntimeError("文档块数量超过预览限制")

    def add_image(self, target: str, size: int) -> None:
        self.images += 1
        if self.images > self.max_images:
            raise RuntimeError("图片数量超过预览限制")
        if size > self.max_image_bytes:
            raise RuntimeError("图片超过预览限制")
        if not self.reuse_images or target not in self.image_targets:
            self.image_targets.add(target)
            self.artifacts += 1
            self.total_image_bytes += size
            if self.artifacts > self.max_artifacts:
                raise RuntimeError("图片数量超过预览限制")
            if self.total_image_bytes > self.max_total_image_bytes:
                raise RuntimeError("DOCX 图片总大小超过预览限制")


def _open_archive(source: bytes | str | Path) -> ZipFile:
    if isinstance(source, (str, Path)):
        return ZipFile(str(source))
    return ZipFile(BytesIO(source))


def _check_archive_budget(archive: ZipFile) -> None:
    total_uncompressed = 0
    for info in archive.infolist():
        size = int(info.file_size)
        if size < 0:
            raise RuntimeError("DOCX ZIP 声明了无效的解压大小")
        total_uncompressed += size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise RuntimeError("DOCX 解压内容超过预览限制")


def _image_reference_targets(
    body: ET.Element | list[ET.Element],
    relationships: dict[str, str],
) -> list[str]:
    targets: list[str] = []
    roots = [body] if isinstance(body, ET.Element) else body
    for root in roots:
        for node in root.iter(f"{{{A_NS}}}blip"):
            target = relationships.get(str(node.attrib.get(f"{R}embed") or "").strip())
            if target:
                targets.append(target)
    return targets


def _check_image_budget(archive: ZipFile, body: ET.Element, relationships: dict[str, str], budget: ParseBudget) -> None:
    targets = _image_reference_targets(body, relationships)
    for target in targets:
        try:
            size = int(archive.getinfo(target).file_size)
        except KeyError:
            size = 0
        budget.add_image(target, size)


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(str(node.text or "") for node in paragraph.iter(f"{W}t"))


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
    level = integer(match.group(1), 1)
    return min(6, level) if level is not None else None


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


class Numbering:
    def __init__(self, root: ET.Element | None, formatting: Formatting):
        self.abstracts = {attr(n, "abstractNumId"): n for n in root.findall("w:abstractNum", NS)} if root is not None else {}
        self.nums = {attr(n, "numId"): n for n in root.findall("w:num", NS)} if root is not None else {}
        self.formatting = formatting
        self.counters: dict[tuple[str, int], int] = {}

    def levels(self, num_id: str, visited: set[str] | None = None) -> dict[int, tuple[ET.Element, int | None]]:
        visited = set() if visited is None else visited
        if num_id in visited:
            return {}
        visited.add(num_id)
        num = self.nums.get(num_id)
        abstract = self.abstracts.get(attr(child(num, "abstractNumId")))
        result = {}
        linked = attr(child(abstract, "numStyleLink"))
        if linked:
            linked_id = ""
            for style in self.formatting.chain(linked, "numbering"):
                linked_id = attr(child(child(child(style, "pPr"), "numPr"), "numId")) or linked_id
            result.update(self.levels(linked_id, visited))
        for level in abstract.findall("w:lvl", NS) if abstract is not None else []:
            depth = integer(attr(level, "ilvl"), 0)
            if depth is not None and depth <= 8:
                result[depth] = (level, None)
        for override in num.findall("w:lvlOverride", NS) if num is not None else []:
            depth = integer(attr(override, "ilvl"), 0)
            if depth is None or depth > 8:
                continue
            level = child(override, "lvl")
            if level is None:
                level = result.get(depth, (None, None))[0]
            if level is not None:
                result[depth] = (level, integer(attr(child(override, "startOverride")), 0))
        return result

    @staticmethod
    def properties(layers: list[ET.Element | None]) -> tuple[str, int]:
        num_id, depth = "", 0
        for props in layers:
            numbering = child(props, "numPr")
            value = integer(attr(child(numbering, "numId")), 0)
            if value is not None:
                num_id = str(value)
            value = integer(attr(child(numbering, "ilvl")), 0)
            if value is not None and value <= 8:
                depth = value
        return num_id, depth

    @staticmethod
    def label(value: int, fmt: str) -> str:
        if fmt in {"lowerLetter", "upperLetter"} and value > 0:
            text = ""
            while value:
                value, digit = divmod(value - 1, 26)
                text = chr(65 + digit) + text
            return text.lower() if fmt == "lowerLetter" else text
        if fmt in {"lowerRoman", "upperRoman"} and 0 < value < 4000:
            text = ""
            for number, letters in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                                    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
                count, value = divmod(value, number)
                text += letters * count
            return text.lower() if fmt == "lowerRoman" else text
        return str(value).zfill(2) if fmt == "decimalZero" else str(value)

    def marker(self, num_id: str, depth: int, levels: dict) -> dict:
        level, override = levels.get(depth, (None, None))
        fmt = attr(child(level, "numFmt"), default="bullet")
        start = override if override is not None else integer(attr(child(level, "start")), 0)
        key = (num_id, depth)
        self.counters[key] = self.counters.get(key, (1 if start is None else start) - 1) + 1
        for later, (later_level, _) in levels.items():
            restart = integer(attr(child(later_level, "lvlRestart")), 0)
            if later > depth and (restart is None or (restart > 0 and depth < restart)):
                self.counters.pop((num_id, later), None)
        pattern = attr(child(level, "lvlText"), default="•" if fmt == "bullet" else f"%{depth + 1}.")

        def substitute(match: re.Match) -> str:
            position = int(match.group(1)) - 1
            referenced, initial = levels.get(position, (None, None))
            if initial is None:
                initial = integer(attr(child(referenced, "start")), 0)
            value = self.counters.get((num_id, position), 1 if initial is None else initial)
            return self.label(value, attr(child(referenced, "numFmt"), default="decimal"))

        return {"ordered": fmt not in {"bullet", "none"}, "depth": depth,
                "marker": "" if fmt == "none" else re.sub(r"%([1-9])", substitute, pattern)}


def _iter_runs(parent: ET.Element):
    for node in parent:
        if node.tag == W + "r":
            yield node
        elif node.tag in {W + name for name in ("hyperlink", "sdt", "sdtContent", "smartTag", "customXml", "ins", "moveTo", "fldSimple")}:
            yield from _iter_runs(node)


def _image_size_px(inline: ET.Element | None) -> tuple[int | None, int | None]:
    extent = inline.find("wp:extent", NS) if inline is not None else None
    if extent is None:
        return None, None
    width_emu = integer(extent.get("cx", ""), 0)
    height_emu = integer(extent.get("cy", ""), 0)
    if width_emu is None or height_emu is None:
        return None, None
    width = round(width_emu / EMU_PER_PIXEL)
    height = round(height_emu / EMU_PER_PIXEL)
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
    budget: ParseBudget | None = None,
    include_placeholders: bool = False,
    artifact_cache: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    if write_artifact is None and not include_placeholders:
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
            if budget is not None:
                try:
                    image_size = int(archive.getinfo(target).file_size)
                except KeyError:
                    image_size = 0
                budget.add_image(target, image_size)
            filename = posixpath.basename(target)
            suffix = Path(filename).suffix.lower()
            content_type = content_types.get(suffix) or IMAGE_CONTENT_TYPES.get(suffix) or "application/octet-stream"
            width, height = _image_size_px(inline)
            alt, title = _image_alt_title(inline)
            if write_artifact is None:
                block: dict[str, object] = {
                    "type": "image",
                    "artifactId": "",
                    "filename": filename,
                    "contentType": content_type,
                }
            else:
                artifact = artifact_cache.get(target) if artifact_cache is not None else None
                if artifact is None:
                    try:
                        content = archive.read(target)
                    except KeyError:
                        continue
                    artifact = write_artifact(filename, content, content_type)
                    if artifact_cache is not None:
                        artifact_cache[target] = artifact
                artifact_id = str(artifact.get("artifactId") or "")
                if not artifact_id:
                    continue
                block = {
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


class DocumentParser:
    def __init__(
        self,
        archive: ZipFile,
        write_artifact: ArtifactWriter | None,
        *,
        budget: ParseBudget | None = None,
        include_image_placeholders: bool = False,
        artifact_cache: dict[str, dict[str, object]] | None = None,
    ):
        self.archive = archive
        self.write_artifact = write_artifact
        self.budget = budget
        self.include_image_placeholders = include_image_placeholders
        self.artifact_cache = artifact_cache
        styles = _xml(archive, "word/styles.xml")
        relationships = _xml(archive, "word/_rels/document.xml.rels")
        theme_path = "word/theme/theme1.xml"
        for rel in relationships if relationships is not None else []:
            if rel.get("Type", "").endswith("/theme") and rel.get("TargetMode", "").lower() != "external":
                theme_path = posixpath.normpath(posixpath.join("word", rel.get("Target", ""))).lstrip("/")
        self.formatting = Formatting(styles, _xml(archive, theme_path), _xml(archive, "word/settings.xml"))
        self.heading_styles = _heading_styles(styles)
        self.numbering = Numbering(_xml(archive, "word/numbering.xml"), self.formatting)
        self.content_types = _content_types(_xml(archive, "[Content_Types].xml"))
        self.relationships = _document_relationships(relationships)

    def paragraph(self, paragraph: ET.Element, table_layers: list[ET.Element] | None = None) -> list[dict]:
        formatting = self.formatting
        table_layers = table_layers or []
        props = child(paragraph, "pPr")
        style_id = attr(child(props, "pStyle")) or formatting.defaults.get("paragraph", "")
        styles = formatting.chain(style_id, "paragraph")
        base_props = [formatting.default_paragraph, *[child(s, "pPr") for s in table_layers]]
        style_props = [child(s, "pPr") for s in styles]
        num_id, depth = self.numbering.properties([*base_props, *style_props, props])
        levels = self.numbering.levels(num_id)
        if child(child(props, "numPr"), "ilvl") is None:
            for style in styles:
                for candidate, (level, _) in levels.items():
                    if attr(child(level, "pStyle")) == attr(style, "styleId"):
                        depth = candidate
        # Numbering's pPr supplies list geometry; its rPr styles the marker, not the text.
        level_props = child(levels.get(depth, (None, None))[0], "pPr")
        # Word applies paragraph styles before numbering properties (MS-OI29500 2.1.229).
        paragraph_layers = [*base_props, *style_props, level_props, props]
        # Word table styles set toggle properties rather than toggling them (MS-OI29500 2.1.246).
        run_layers = [(formatting.default_run, False),
                      *[(child(s, "rPr"), False) for s in table_layers],
                      *[(child(s, "rPr"), True) for s in styles]]
        text_style = formatting.run_style(run_layers)
        paragraph_format = formatting.paragraph_format(paragraph_layers)
        if text_style:
            paragraph_format["textStyle"] = text_style
        block = {"type": "paragraph"}
        heading = None
        for style in styles:
            heading = _heading_level(attr(style, "styleId"), self.heading_styles) or heading
        heading = _heading_level(style_id, self.heading_styles) or heading
        for layer in paragraph_layers:
            outline = integer(attr(child(layer, "outlineLvl")), 0)
            if outline is not None:
                heading = min(6, outline + 1) if outline < 9 else None
        if heading is not None:
            block.update(type="heading", level=heading)
        elif num_id and num_id != "0":
            block.update(type="list_item", **self.numbering.marker(num_id, depth, levels))
            marker_style = formatting.run_style([
                *run_layers,
                (child(levels.get(depth, (None, None))[0], "rPr"), False),
                (child(props, "rPr"), False),
            ])
            if marker_style:
                block["markerStyle"] = marker_style
        if paragraph_format:
            block["format"] = paragraph_format
        blocks, runs = [], []

        def flush() -> None:
            if runs:
                blocks.append({**block, "runs": list(runs)})
                runs.clear()

        for run in _iter_runs(paragraph):
            run_props = child(run, "rPr")
            character_id = attr(child(run_props, "rStyle")) or formatting.defaults.get("character", "")
            character_layers = [(child(s, "rPr"), True) for s in formatting.chain(character_id, "character")]
            style = formatting.run_style([*run_layers, *character_layers, (run_props, False)])
            parts = []

            def flush_text() -> None:
                if parts:
                    text = "".join(parts)
                    if text:
                        runs.append({"text": text, **style})
                    parts.clear()

            for node in run:
                if node.tag == W + "t":
                    parts.append(node.text or "")
                elif node.tag == W + "tab":
                    parts.append("\t")
                elif node.tag in {W + "br", W + "cr"}:
                    parts.append("\n")
                elif node.tag == W + "noBreakHyphen":
                    parts.append("\u2011")
                elif node.tag == W + "softHyphen":
                    parts.append("\u00ad")
                elif node.tag == W + "drawing":
                    wrapper = ET.Element(W + "r")
                    wrapper.append(node)
                    images = _image_blocks(
                        wrapper,
                        self.archive,
                        self.relationships,
                        self.content_types,
                        self.write_artifact,
                        self.budget,
                        self.include_image_placeholders,
                        self.artifact_cache,
                    )
                    if images:
                        flush_text()
                        flush()
                        blocks.extend(images)
            flush_text()
        flush()
        if not blocks:
            # Paragraph-mark formatting controls the line box of an empty paragraph.
            baseline = formatting.run_style([*run_layers, (child(props, "rPr"), False)])
            blank_format = {**paragraph_format, **({"textStyle": baseline} if baseline else {})}
            blocks.append({**block, **({"format": blank_format} if blank_format else {}), "runs": [{"text": ""}]})
        if self.budget is not None:
            self.budget.add_blocks(len(blocks))
        return blocks

    @staticmethod
    def table_conditions(layers: list[ET.Element | None], row: int, col: int, row_count: int, col_count: int, span: int,
                         row_props: ET.Element | None, cell_props: ET.Element | None) -> list[str]:
        bits = {"firstRow": 0x20, "lastRow": 0x40, "firstColumn": 0x80, "lastColumn": 0x100,
                "noHBand": 0x200, "noVBand": 0x400}
        look = dict.fromkeys(bits, False)
        row_band = col_band = 1
        for props in layers:
            node = child(props, "tblLook")
            value = attr(node)
            if re.fullmatch(r"[0-9a-fA-F]{1,4}", value):
                look.update({key: bool(int(value, 16) & bit) for key, bit in bits.items()})
            for key in bits:
                enabled = on_off(attr(node, key))
                if enabled is not None:
                    look[key] = enabled
            row_band = integer(attr(child(props, "tblStyleRowBandSize")), 1) or row_band
            col_band = integer(attr(child(props, "tblStyleColBandSize")), 1) or col_band
        first_row, last_row = row == 0 and look["firstRow"], row == row_count - 1 and look["lastRow"]
        first_col, last_col = col == 0 and look["firstColumn"], col + span == col_count and look["lastColumn"]
        active = {"firstRow": first_row, "lastRow": last_row, "firstCol": first_col, "lastCol": last_col}
        for axis, index, band, excluded, disabled in (
            ("Horz", row - int(look["firstRow"]), row_band, first_row or last_row, look["noHBand"]),
            ("Vert", col - int(look["firstColumn"]), col_band, first_col or last_col, look["noVBand"]),
        ):
            if not disabled and not excluded:
                active[f"band{(max(0, index) // band) % 2 + 1}{axis}"] = True
        active.update(nwCell=first_row and first_col, neCell=first_row and last_col,
                      swCell=last_row and first_col, seCell=last_row and last_col)
        names = ("firstRow", "lastRow", "firstColumn", "lastColumn", "oddVBand", "evenVBand", "oddHBand", "evenHBand",
                 "firstRowFirstColumn", "firstRowLastColumn", "lastRowFirstColumn", "lastRowLastColumn")
        keys = ("firstRow", "lastRow", "firstCol", "lastCol", "band1Vert", "band2Vert", "band1Horz", "band2Horz",
                "nwCell", "neCell", "swCell", "seCell")
        for props in (row_props, cell_props):
            node = child(props, "cnfStyle")
            value = attr(node)
            if re.fullmatch(r"[01]{12}", value):
                active.update({key: digit == "1" for key, digit in zip(keys, value)})
            for name, key in zip(names, keys):
                enabled = on_off(attr(node, name))
                if enabled is not None:
                    active[key] = enabled
        # Word's conditional-style order: bands, columns, rows, then corners.
        return ["wholeTable", *[key for key in ("band1Horz", "band2Horz", "band1Vert", "band2Vert", "firstCol", "lastCol",
                                               "firstRow", "lastRow", "nwCell", "neCell", "swCell", "seCell") if active.get(key)]]

    def table(self, table: ET.Element) -> dict:
        formatting = self.formatting
        props = child(table, "tblPr")
        style_id = attr(child(props, "tblStyle")) or formatting.defaults.get("table", "")
        styles = formatting.chain(style_id, "table")
        table_layers = [child(s, "tblPr") for s in styles]
        whole_layers = [n for s in styles for n in s.findall("w:tblStylePr", NS) if attr(n, "type") == "wholeTable"]
        table_defaults = {}
        for layer in [*table_layers, *[child(n, "tblPr") for n in whole_layers], props]:
            merge(table_defaults, formatting.table_properties(layer))
        widths = []
        grid = child(table, "tblGrid")
        for column in grid if grid is not None else []:
            value = integer(attr(column, "w"), 0)
            widths.append(value / 15 if value is not None else 0)
        result = {"type": "table", **table_defaults, "rows": []}
        if widths:
            result["columnWidthsPx"] = widths
        source_rows = table.findall("w:tr", NS)
        records = []
        column_count = len(widths)
        for row in source_rows:
            row_props = child(row, "trPr")
            col = min(integer(attr(child(row_props, "gridBefore")), 0) or 0, MAX_GRID_COUNT)
            cells = []
            for cell in row.findall("w:tc", NS):
                cell_props = child(cell, "tcPr")
                span = integer(attr(child(cell_props, "gridSpan")), 1) or 1
                # Grid spans are structural counts; avoid huge allocations for damaged documents.
                span = min(span, MAX_GRID_COUNT)
                horizontal = child(cell_props, "hMerge")
                if horizontal is not None and attr(horizontal, default="continue") == "continue" and cells and cells[-1]["horizontal"]:
                    merged_span = min(cells[-1]["span"] + span, MAX_GRID_COUNT)
                    col += merged_span - cells[-1]["span"]
                    cells[-1]["span"] = merged_span
                    cells[-1]["nodes"].append(cell)
                else:
                    cells.append({"col": col, "span": span, "nodes": [cell],
                                  "horizontal": horizontal is not None and attr(horizontal) == "restart"})
                    col += span
            after = min(integer(attr(child(row_props, "gridAfter")), 0) or 0, MAX_GRID_COUNT)
            column_count = max(column_count, col + after)
            records.append(cells)
        active_merges = {}
        for row_index, (row, cells) in enumerate(zip(source_rows, records)):
            rendered_cells, next_merges = [], {}
            row_props = child(row, "trPr")
            before = cells[0]["col"] if cells else 0
            if before:
                rendered_cells.append({"runs": [{"text": ""}], "colSpan": before})
            for record in cells:
                cell_node = record["nodes"][0]
                cell_props = child(cell_node, "tcPr")
                col, span = record["col"], record["span"]
                conditions = self.table_conditions([*table_layers, props], row_index, col, len(source_rows), column_count, span,
                                                   row_props, cell_props)
                conditional = [node for condition in conditions for style in styles
                               for node in style.findall("w:tblStylePr", NS) if attr(node, "type") == condition]
                cell = {}

                def apply_table_defaults(layer: ET.Element | None) -> None:
                    table_values = formatting.table_properties(layer)
                    if "cellPadding" in table_values:
                        merge(cell.setdefault("padding", {}), table_values["cellPadding"])
                    if "shadingColor" in table_values:
                        cell["shadingColor"] = table_values["shadingColor"]
                    edges = table_values.get("borders", {})
                    for edge, source in (("top", "top" if row_index == 0 else "insideHorizontal"),
                                         ("bottom", "bottom" if row_index == len(source_rows) - 1 else "insideHorizontal"),
                                         ("left", "left" if col == 0 else "insideVertical"),
                                         ("right", "right" if col + span == column_count else "insideVertical")):
                        if source in edges:
                            cell.setdefault("borders", {})[edge] = dict(edges[source])

                for layer in [*styles, *conditional]:
                    apply_table_defaults(child(layer, "tblPr"))
                    merge(cell, formatting.table_properties(child(layer, "tcPr"), cell=True))
                apply_table_defaults(props)
                apply_table_defaults(child(row, "tblPrEx"))
                merge(cell, formatting.table_properties(cell_props, cell=True))
                if "width" not in cell and widths and col + span <= len(widths):
                    cell["width"] = {"unit": "px", "value": sum(widths[col:col + span])}
                if span > 1:
                    cell["colSpan"] = span
                vertical = child(cell_props, "vMerge")
                previous = active_merges.get(col)
                if vertical is not None and attr(vertical, default="continue") == "continue" and previous and previous[0] == span:
                    origin = previous[1]
                    origin["rowSpan"] = origin.get("rowSpan", 1) + 1
                    if "bottom" in cell.get("borders", {}):
                        origin.setdefault("borders", {})["bottom"] = cell["borders"]["bottom"]
                    next_merges[col] = previous
                    continue
                paragraphs = []
                for source_index, source_cell in enumerate(record["nodes"]):
                    for paragraph in source_cell.findall("w:p", NS):
                        content = self.paragraph(paragraph, [*styles, *conditional])
                        # Legacy hMerge continuation cells commonly contain a required empty p.
                        if source_index and all(p["type"] != "image" and not any(r["text"] for r in p["runs"]) for p in content):
                            continue
                        paragraphs.extend(content)
                cell["paragraphs"] = paragraphs
                fallback = []
                for paragraph in paragraphs:
                    if paragraph["type"] != "image":
                        if fallback:
                            fallback.append({"text": "\n"})
                        fallback.extend(paragraph["runs"])
                cell["runs"] = fallback or [{"text": ""}]
                rendered_cells.append(cell)
                if vertical is not None and attr(vertical) == "restart":
                    next_merges[col] = (span, cell)
            active_merges = next_merges
            result["rows"].append({"cells": rendered_cells})
        if self.budget is not None:
            self.budget.add_blocks(1)
        return result


def _document_root(archive: ZipFile) -> tuple[ET.Element, ET.Element]:
    document_root = _xml(archive, "word/document.xml")
    if document_root is None:
        raise RuntimeError("DOCX 缺少 word/document.xml")
    body = document_root.find("w:body", NS)
    if body is None:
        raise RuntimeError("DOCX body 为空")
    return document_root, body


def _prepare_archive(archive: ZipFile) -> None:
    # Read only the ZIP central directory first. No image data is read before
    # these checks complete.
    _check_archive_budget(archive)


def _parse_body(
    archive: ZipFile,
    children: list[ET.Element],
    write_artifact: ArtifactWriter | None,
    *,
    budget: ParseBudget,
    include_image_placeholders: bool,
) -> tuple[list[dict[str, object]], int, int]:
    parser = DocumentParser(
        archive,
        write_artifact,
        budget=budget,
        include_image_placeholders=include_image_placeholders,
    )
    blocks: list[dict[str, object]] = []
    paragraph_count = 0
    table_count = 0
    for node in children:
        if node.tag == f"{W}p":
            paragraph_blocks = parser.paragraph(node)
            if paragraph_blocks:
                paragraph_count += 1
                blocks.extend(paragraph_blocks)
        elif node.tag == f"{W}tbl":
            table_count += 1
            blocks.append(parser.table(node))
    return blocks, paragraph_count, table_count


def _payload(
    path: str,
    blocks: list[dict[str, object]],
    paragraph_count: int,
    table_count: int,
    image_count: int,
    *,
    title: str | None = None,
) -> dict[str, object]:
    resolved_title = title or next(
        (
            "".join(str(run.get("text") or "") for run in block.get("runs", []))
            for block in blocks
            if block.get("type") == "heading"
        ),
        Path(path).name,
    )
    return {
        "path": path,
        "formatting": "document",
        "title": resolved_title,
        "statsText": f"{paragraph_count} 段 · {table_count} 表格 · {image_count} 图片",
        "blocks": blocks,
    }


def _parse_source(
    path: str,
    source: bytes | str | Path,
    *,
    write_artifact: ArtifactWriter | None,
    children_slice: tuple[int, int] | None = None,
    artifact_limits: dict[str, int] | None = None,
) -> dict[str, object]:
    try:
        with _open_archive(source) as archive:
            _prepare_archive(archive)
            _document, body = _document_root(archive)
            children = list(body)
            if children_slice is not None:
                start, end = children_slice
                children = children[max(0, start):max(start, end)]
            # The first pass only parses XML and emits image placeholders. It
            # ensures the block budget is exhausted before any artifact write.
            preflight_budget = ParseBudget(artifact_limits=artifact_limits)
            _parse_body(
                archive,
                children,
                None,
                budget=preflight_budget,
                include_image_placeholders=True,
            )

            actual_budget = ParseBudget(artifact_limits=artifact_limits)
            blocks, paragraph_count, table_count = _parse_body(
                archive,
                children,
                write_artifact,
                budget=actual_budget,
                include_image_placeholders=False,
            )
            return _payload(path, blocks, paragraph_count, table_count, preflight_budget.images)
    except BadZipFile as exc:
        raise RuntimeError("DOCX 文件损坏或格式不支持") from exc
    except ET.ParseError as exc:
        raise RuntimeError("DOCX XML 解析失败") from exc


def parse_docx_document(
    path: str,
    content: bytes,
    *,
    write_artifact: ArtifactWriter | None = None,
    artifact_limits: dict[str, int] | None = None,
) -> dict[str, object]:
    return _parse_source(path, content, write_artifact=write_artifact, artifact_limits=artifact_limits)


def _section_heading(paragraph: ET.Element, heading_styles: dict[str, int]) -> tuple[int | None, str]:
    props = child(paragraph, "pPr")
    style_id = attr(child(props, "pStyle"))
    level = _heading_level(style_id, heading_styles)
    outline = integer(attr(child(props, "outlineLvl")), 0)
    if outline is not None and outline < 9:
        level = min(6, outline + 1)
    return level, _paragraph_text(paragraph).strip()


def inspect_docx_document(
    path: str,
    source: bytes | str | Path,
    *,
    artifact_limits: dict[str, int] | None = None,
) -> dict[str, object]:
    try:
        with _open_archive(source) as archive:
            _prepare_archive(archive)
            _document, body = _document_root(archive)
            children = list(body)
            relationships = _document_relationships(_xml(archive, "word/_rels/document.xml.rels"))
            image_budget = ParseBudget(artifact_limits=artifact_limits)
            _check_image_budget(archive, children, relationships, image_budget)
            heading_styles = _heading_styles(_xml(archive, "word/styles.xml"))
            headings: list[tuple[int, int, str]] = []
            for index, node in enumerate(children):
                if node.tag != f"{W}p":
                    continue
                level, title = _section_heading(node, heading_styles)
                if level is not None:
                    headings.append((index, level, title))

            starts: list[tuple[int, int | None, str]] = []
            if headings:
                if headings[0][0] > 0:
                    starts.append((0, None, "引言"))
                starts.extend(headings)
            else:
                starts = [
                    (index, None, f"第 {number + 1} 节")
                    for number, index in enumerate(range(0, max(1, len(children)), DEFAULT_SECTION_BLOCKS))
                ]
            sections: list[dict[str, object]] = []
            for number, (start, level, title) in enumerate(starts):
                end = starts[number + 1][0] if number + 1 < len(starts) else len(children)
                if start >= end:
                    continue
                section_id = f"section-{len(sections) + 1}"
                sections.append({
                    "id": section_id,
                    "title": title or f"第 {len(sections) + 1} 节",
                    "index": len(sections),
                    "headingLevel": level,
                    "_start": start,
                    "_end": end,
                })
            if not sections:
                sections.append({"id": "section-1", "title": Path(path).name, "index": 0, "headingLevel": None, "_start": 0, "_end": len(children)})
            title = next((str(section["title"]) for section in sections if section.get("headingLevel") is not None), Path(path).name)
            paragraph_count = sum(1 for node in children if node.tag == f"{W}p")
            table_count = sum(1 for node in children if node.tag == f"{W}tbl")
            return {
                "path": path,
                "title": title,
                "statsText": f"{paragraph_count} 段 · {table_count} 表格 · {image_budget.images} 图片",
                "sections": [
                    {key: value for key, value in section.items() if not key.startswith("_")}
                    for section in sections
                ],
                "_sections": sections,
            }
    except BadZipFile as exc:
        raise RuntimeError("DOCX 文件损坏或格式不支持") from exc
    except ET.ParseError as exc:
        raise RuntimeError("DOCX XML 解析失败") from exc


def parse_docx_section(
    path: str,
    source: bytes | str | Path,
    section: dict[str, object],
    *,
    write_artifact: ArtifactWriter | None = None,
    artifact_limits: dict[str, int] | None = None,
) -> dict[str, object]:
    start = int(section.get("_start") or 0)
    end = int(section.get("_end") or start)
    payload = _parse_source(
        path,
        source,
        write_artifact=write_artifact,
        children_slice=(start, end),
        artifact_limits=artifact_limits,
    )
    if section.get("title"):
        payload["title"] = str(section["title"])
    payload["sectionId"] = str(section.get("id") or "")
    return payload
