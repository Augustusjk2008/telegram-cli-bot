from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from mermaid_visio.flowchart_parser import parse_flowchart
from mermaid_visio.models import PluginConfig
from mermaid_visio.normalizer import normalize_ir
from mermaid_visio.simple_layout import simple_layout
from mermaid_visio.vsdx_writer import write_vsdx
from vsdx_assertions import NS, VsdxPackage, assert_vsdx_package


def _render_vsdx(tmp_path: Path, code: str, *, filename: str = "diagram.vsdx") -> VsdxPackage:
    output = tmp_path / filename
    ir = normalize_ir(parse_flowchart(code), PluginConfig(layout_engine="simple"))
    layout = simple_layout(ir)
    write_vsdx(ir, layout, output)
    return assert_vsdx_package(output, min_shapes=max(1, len(ir.nodes) + len(ir.edges)))


def _shape_text(shape: ET.Element) -> str:
    text = shape.find("v:Text", NS)
    return "".join(text.itertext()) if text is not None else ""


def _shape_by_text(package: VsdxPackage, text: str) -> ET.Element:
    for shape in package.shapes:
        if _shape_text(shape) == text:
            return shape
    raise AssertionError(f"shape text not found: {text}")


def _direct_cells(shape: ET.Element) -> dict[str, str]:
    return {
        cell.attrib["N"]: cell.attrib.get("V", "")
        for cell in shape.findall("v:Cell", NS)
        if "N" in cell.attrib
    }


def _all_cells(shape: ET.Element) -> dict[str, list[str]]:
    cells: dict[str, list[str]] = {}
    for cell in shape.findall(".//v:Cell", NS):
        if "N" in cell.attrib:
            cells.setdefault(cell.attrib["N"], []).append(cell.attrib.get("V", ""))
    return cells


def _edge_shapes(package: VsdxPackage) -> list[ET.Element]:
    return [
        shape
        for shape in package.shapes
        if "BeginArrow" in _direct_cells(shape)
    ]


def test_minimal_flowchart_vsdx_package_is_structurally_valid(tmp_path: Path) -> None:
    package = _render_vsdx(tmp_path, "flowchart TD\nA[Start] --> B[End]\n")

    assert "[Content_Types].xml" in package.parts
    assert _shape_text(_shape_by_text(package, "Start")) == "Start"
    assert _shape_text(_shape_by_text(package, "End")) == "End"


def test_node_and_edge_labels_preserve_unicode_and_xml_characters(tmp_path: Path) -> None:
    special = "中文 & < > \" '"
    package = _render_vsdx(
        tmp_path,
        f"flowchart TD\nA[{special}] -->|边 {special}| B[结束 {special}]\n",
    )

    texts = {_shape_text(shape) for shape in package.shapes}
    assert special in texts
    assert f"边 {special}" in texts
    assert f"结束 {special}" in texts


def test_style_colors_are_normalized_and_invalid_text_color_falls_back(tmp_path: Path) -> None:
    package = _render_vsdx(
        tmp_path,
        "flowchart TD\nA[Styled] --> B[Plain]\nstyle A fill:#abc,stroke:#123456,color:not-a-color\n",
    )

    styled = _shape_by_text(package, "Styled")
    direct = _direct_cells(styled)
    all_cells = _all_cells(styled)
    assert direct["FillForegnd"] == "#aabbcc"
    assert direct["LineColor"] == "#123456"
    assert "#111827" in all_cells["Color"]


def test_edge_variants_write_line_pattern_weight_and_arrow_cells(tmp_path: Path) -> None:
    package = _render_vsdx(
        tmp_path,
        "flowchart TD\nA[One] -.-> B[Two]\nB ==> C[Three]\nC --- D[Four]\n",
    )

    edge_cells = [_direct_cells(shape) for shape in _edge_shapes(package)]
    assert any(cells.get("LinePattern") == "2" and cells.get("EndArrow") == "4" for cells in edge_cells)
    assert any(cells.get("LineWeight") == "0.025" and cells.get("EndArrow") == "4" for cells in edge_cells)
    assert any(cells.get("EndArrow") == "0" for cells in edge_cells)


def test_supported_node_geometries_render_without_breaking_package(tmp_path: Path) -> None:
    package = _render_vsdx(
        tmp_path,
        "\n".join(
            [
                "flowchart LR",
                "A{Decision} --> B((Circle))",
                "B --> C[(Database)]",
                "C --> D(Terminator)",
            ]
        ),
    )

    for label in ("Decision", "Circle", "Database", "Terminator"):
        shape = _shape_by_text(package, label)
        assert shape.find("v:Section[@N='Geometry']", NS) is not None


def test_subgraph_writes_group_boundary_with_reasonable_dimensions(tmp_path: Path) -> None:
    package = _render_vsdx(
        tmp_path,
        "\n".join(
            [
                "flowchart TD",
                "subgraph Outer[Outer Group]",
                "A[Alpha] --> B[Beta]",
                "end",
            ]
        ),
    )

    group_shape = _shape_by_text(package, "Outer Group")
    cells = _direct_cells(group_shape)
    assert float(cells["Width"]) > 1.5
    assert float(cells["Height"]) > 0.8
