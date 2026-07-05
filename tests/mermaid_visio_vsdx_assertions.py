from __future__ import annotations

import math
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from xml.etree import ElementTree as ET

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
VISIO_NS = "http://schemas.microsoft.com/office/visio/2011/1/core"

NS = {
    "rel": REL_NS,
    "ct": CONTENT_TYPES_NS,
    "v": VISIO_NS,
}

REQUIRED_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "docProps/core.xml",
    "docProps/app.xml",
    "visio/document.xml",
    "visio/pages/pages.xml",
    "visio/pages/page1.xml",
}

REQUIRED_CONTENT_TYPE_OVERRIDES = {
    "/visio/document.xml",
    "/visio/pages/pages.xml",
    "/visio/pages/page1.xml",
}


@dataclass(frozen=True)
class VsdxPackage:
    parts: dict[str, bytes]
    xml_roots: dict[str, ET.Element]
    shapes: list[ET.Element]


def assert_vsdx_package(vsdx: bytes | str | Path | BinaryIO, *, min_shapes: int = 1) -> VsdxPackage:
    """Assert that a generated VSDX is a sane OPC ZIP package for regression tests."""
    with zipfile.ZipFile(_as_zip_source(vsdx)) as archive:
        bad_file = archive.testzip()
        assert bad_file is None, f"corrupt ZIP entry: {bad_file}"

        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert len(names) == len(set(names)), "VSDX ZIP contains duplicate entries"
        for name in names:
            _assert_safe_part_name(name)

        part_names = set(names)
        missing = REQUIRED_PARTS - part_names
        assert not missing, f"VSDX package is missing required parts: {sorted(missing)}"

        parts = {name: archive.read(name) for name in names if not name.endswith("/")}

    xml_roots = _parse_xml_parts(parts)
    _assert_content_type_overrides(xml_roots["[Content_Types].xml"])
    _assert_relationship_targets(xml_roots, set(parts))
    _assert_pages_xml(xml_roots["visio/pages/pages.xml"])
    shapes = _assert_page_shapes(xml_roots["visio/pages/page1.xml"], min_shapes=min_shapes)
    return VsdxPackage(parts=parts, xml_roots=xml_roots, shapes=shapes)


def _as_zip_source(vsdx: bytes | str | Path | BinaryIO):
    if isinstance(vsdx, bytes):
        from io import BytesIO

        return BytesIO(vsdx)
    return vsdx


def _assert_safe_part_name(name: str) -> None:
    assert name, "VSDX ZIP contains an empty entry name"
    assert not name.startswith(("/", "\\")), f"VSDX part must not be absolute: {name}"
    assert not re.match(r"^[A-Za-z]:", name), f"VSDX part must not include a drive prefix: {name}"
    assert "\\" not in name, f"VSDX part must use POSIX separators: {name}"
    parts = PurePosixPath(name).parts
    assert ".." not in parts, f"VSDX part must not traverse directories: {name}"


def _parse_xml_parts(parts: dict[str, bytes]) -> dict[str, ET.Element]:
    roots: dict[str, ET.Element] = {}
    for name, content in parts.items():
        if name.endswith((".xml", ".rels")):
            try:
                roots[name] = ET.fromstring(content)
            except ET.ParseError as exc:
                raise AssertionError(f"XML part is not well-formed: {name}: {exc}") from exc
    return roots


def _assert_content_type_overrides(root: ET.Element) -> None:
    overrides = {
        override.attrib.get("PartName", "")
        for override in root.findall("ct:Override", NS)
    }
    missing = REQUIRED_CONTENT_TYPE_OVERRIDES - overrides
    assert not missing, f"content type overrides missing: {sorted(missing)}"


def _assert_relationship_targets(xml_roots: dict[str, ET.Element], part_names: set[str]) -> None:
    for rels_name, root in xml_roots.items():
        if not rels_name.endswith(".rels"):
            continue
        source_base = _relationship_source_base(rels_name, part_names)
        for relationship in root.findall("rel:Relationship", NS):
            target_mode = relationship.attrib.get("TargetMode", "")
            assert target_mode.lower() != "external", f"external relationship is not allowed: {rels_name}"
            target = relationship.attrib.get("Target", "")
            assert target, f"relationship target is empty: {rels_name}"
            assert not _looks_like_external_target(target), f"external relationship target is not allowed: {target}"
            resolved = _resolve_relationship_target(source_base, target)
            assert resolved in part_names, f"relationship target does not exist: {rels_name} -> {target} ({resolved})"


def _relationship_source_base(rels_name: str, part_names: set[str]) -> str:
    if rels_name == "_rels/.rels":
        return ""
    rels_path = PurePosixPath(rels_name)
    assert rels_path.parent.name == "_rels", f"unexpected relationships part path: {rels_name}"
    source_part = rels_path.parent.parent / rels_path.name.removesuffix(".rels")
    assert source_part.as_posix() in part_names, f"relationships source part does not exist: {rels_name}"
    return source_part.parent.as_posix()


def _looks_like_external_target(target: str) -> bool:
    lowered = target.lower()
    return "://" in lowered or lowered.startswith(("mailto:", "urn:"))


def _resolve_relationship_target(source_base: str, target: str) -> str:
    target_without_fragment = target.split("#", 1)[0]
    if target_without_fragment.startswith("/"):
        resolved = posixpath.normpath(target_without_fragment.lstrip("/"))
    elif source_base:
        resolved = posixpath.normpath(posixpath.join(source_base, target_without_fragment))
    else:
        resolved = posixpath.normpath(target_without_fragment)
    assert resolved and not resolved.startswith("../") and resolved != "..", f"relationship target traverses package: {target}"
    return resolved


def _assert_pages_xml(root: ET.Element) -> None:
    page_sheet = root.find(".//v:PageSheet", NS)
    assert page_sheet is not None, "pages.xml must contain a PageSheet"
    cells = _direct_cell_values(page_sheet)
    page_width = _positive_float(cells, "PageWidth")
    page_height = _positive_float(cells, "PageHeight")
    assert page_width >= 1.0
    assert page_height >= 1.0


def _assert_page_shapes(root: ET.Element, *, min_shapes: int) -> list[ET.Element]:
    shapes = root.findall(".//v:Shapes/v:Shape", NS)
    assert len(shapes) >= min_shapes, f"expected at least {min_shapes} shapes, found {len(shapes)}"

    seen_ids: set[int] = set()
    for shape in shapes:
        raw_id = shape.attrib.get("ID", "")
        assert raw_id.isdigit(), f"shape ID must be a positive integer: {raw_id!r}"
        shape_id = int(raw_id)
        assert shape_id > 0, f"shape ID must be positive: {shape_id}"
        assert shape_id not in seen_ids, f"shape ID must be unique: {shape_id}"
        seen_ids.add(shape_id)

        cells = _direct_cell_values(shape)
        _finite_float(cells, "PinX")
        _finite_float(cells, "PinY")
        _positive_float(cells, "Width")
        _positive_float(cells, "Height")
        assert shape.find("v:Section[@N='Geometry']", NS) is not None, f"shape {shape_id} must contain Geometry"
    return shapes


def _direct_cell_values(element: ET.Element) -> dict[str, str]:
    return {
        cell.attrib["N"]: cell.attrib.get("V", "")
        for cell in element.findall("v:Cell", NS)
        if "N" in cell.attrib
    }


def _finite_float(cells: dict[str, str], name: str) -> float:
    assert name in cells, f"missing required cell: {name}"
    try:
        value = float(cells[name])
    except ValueError as exc:
        raise AssertionError(f"cell {name} must be numeric: {cells[name]!r}") from exc
    assert math.isfinite(value), f"cell {name} must be finite"
    return value


def _positive_float(cells: dict[str, str], name: str) -> float:
    value = _finite_float(cells, name)
    assert value > 0, f"cell {name} must be positive"
    return value
