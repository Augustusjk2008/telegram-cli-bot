from __future__ import annotations

import datetime as _dt
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .models import FlowchartIR, LayoutNode, LayoutResult

CORE_NS = "http://schemas.microsoft.com/office/visio/2011/1/core"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def write_vsdx(ir: FlowchartIR, layout: LayoutResult, output_path: Path) -> None:
    page_width = max(8.5, layout.width + 1.0)
    page_height = max(6.0, layout.height + 1.0)
    page_xml = _page_xml(ir, layout, page_width, page_height)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types())
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("docProps/core.xml", _core_props())
        archive.writestr("docProps/app.xml", _app_props())
        archive.writestr("visio/document.xml", _document_xml())
        archive.writestr("visio/_rels/document.xml.rels", _document_rels())
        archive.writestr("visio/pages/pages.xml", _pages_xml(page_width, page_height))
        archive.writestr("visio/pages/_rels/pages.xml.rels", _pages_rels())
        archive.writestr("visio/pages/page1.xml", page_xml)


def _page_xml(ir: FlowchartIR, layout: LayoutResult, page_width: float, page_height: float) -> str:
    shape_id = 1
    chunks: list[str] = []
    for group in ir.groups.values():
        group_nodes = [layout.nodes[node_id] for node_id in group.node_ids if node_id in layout.nodes]
        if not group_nodes:
            continue
        chunks.append(_group_shape_xml(shape_id, group.label, group_nodes))
        shape_id += 1
    for edge in ir.edges:
        layout_edge = layout.edges.get(edge.id)
        if layout_edge is None:
            continue
        chunks.append(_edge_shape_xml(shape_id, layout_edge.points, edge.kind))
        shape_id += 1
    for node_id, node in ir.nodes.items():
        layout_node = layout.nodes[node_id]
        chunks.append(_node_shape_xml(shape_id, node.label, node.kind, layout_node, node.style))
        shape_id += 1
    for edge in ir.edges:
        if not edge.label:
            continue
        layout_edge = layout.edges.get(edge.id)
        if layout_edge is None:
            continue
        x, y = layout_edge.label_pos or _midpoint(layout_edge.points)
        chunks.append(_text_shape_xml(shape_id, edge.label, x, y))
        shape_id += 1
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<PageContents xmlns="{CORE_NS}" xmlns:r="{OFFICE_REL_NS}" xml:space="preserve">\n'
        "  <Shapes>\n"
        + "\n".join(chunks)
        + "\n  </Shapes>\n"
        "</PageContents>\n"
    )


def _node_shape_xml(shape_id: int, label: str, kind: str, node: LayoutNode, style: dict[str, str]) -> str:
    fill = style.get("fill", "#ffffff")
    stroke = style.get("stroke", "#333333")
    return (
        f'    <Shape ID="{shape_id}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'      <Cell N="PinX" V="{_num(node.x)}"/>\n'
        f'      <Cell N="PinY" V="{_num(node.y)}"/>\n'
        f'      <Cell N="Width" V="{_num(node.width)}"/>\n'
        f'      <Cell N="Height" V="{_num(node.height)}"/>\n'
        f'      <Cell N="LocPinX" V="{_num(node.width / 2)}"/>\n'
        f'      <Cell N="LocPinY" V="{_num(node.height / 2)}"/>\n'
        f'      <Cell N="FillForegnd" V="{escape(fill)}"/>\n'
        f'      <Cell N="LineColor" V="{escape(stroke)}"/>\n'
        f'{_geometry_xml(_relative_points(kind))}\n'
        f'      <Text>{escape(label)}</Text>\n'
        "    </Shape>"
    )


def _edge_shape_xml(shape_id: int, points: list[tuple[float, float]], kind: str) -> str:
    if len(points) < 2:
        points = [(0.0, 0.0), (0.1, 0.1)]
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    width = max(0.05, max_x - min_x)
    height = max(0.05, max_y - min_y)
    pin_x = min_x + width / 2
    pin_y = min_y + height / 2
    rel_points = [((x - min_x) / width, (y - min_y) / height) for x, y in points]
    line_pattern = "2" if kind == "dotted" else "1"
    line_weight = "0.025" if kind == "thick" else "0.0125"
    return (
        f'    <Shape ID="{shape_id}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'      <Cell N="PinX" V="{_num(pin_x)}"/>\n'
        f'      <Cell N="PinY" V="{_num(pin_y)}"/>\n'
        f'      <Cell N="Width" V="{_num(width)}"/>\n'
        f'      <Cell N="Height" V="{_num(height)}"/>\n'
        f'      <Cell N="LocPinX" V="{_num(width / 2)}"/>\n'
        f'      <Cell N="LocPinY" V="{_num(height / 2)}"/>\n'
        f'      <Cell N="LinePattern" V="{line_pattern}"/>\n'
        f'      <Cell N="LineWeight" V="{line_weight}"/>\n'
        f'{_geometry_xml(rel_points, no_fill=True)}\n'
        "    </Shape>"
    )


def _group_shape_xml(shape_id: int, label: str, nodes: list[LayoutNode]) -> str:
    min_x = min(node.x - node.width / 2 for node in nodes) - 0.25
    max_x = max(node.x + node.width / 2 for node in nodes) + 0.25
    min_y = min(node.y - node.height / 2 for node in nodes) - 0.25
    max_y = max(node.y + node.height / 2 for node in nodes) + 0.45
    width = max_x - min_x
    height = max_y - min_y
    return (
        f'    <Shape ID="{shape_id}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'      <Cell N="PinX" V="{_num(min_x + width / 2)}"/>\n'
        f'      <Cell N="PinY" V="{_num(min_y + height / 2)}"/>\n'
        f'      <Cell N="Width" V="{_num(width)}"/>\n'
        f'      <Cell N="Height" V="{_num(height)}"/>\n'
        f'      <Cell N="LocPinX" V="{_num(width / 2)}"/>\n'
        f'      <Cell N="LocPinY" V="{_num(height / 2)}"/>\n'
        '      <Cell N="FillForegnd" V="#f8fafc"/>\n'
        '      <Cell N="LineColor" V="#94a3b8"/>\n'
        f'{_geometry_xml(_relative_points("process"))}\n'
        f'      <Text>{escape(label)}</Text>\n'
        "    </Shape>"
    )


def _text_shape_xml(shape_id: int, label: str, x: float, y: float) -> str:
    width = max(0.6, min(3.0, len(label) * 0.16))
    return (
        f'    <Shape ID="{shape_id}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'      <Cell N="PinX" V="{_num(x)}"/>\n'
        f'      <Cell N="PinY" V="{_num(y)}"/>\n'
        f'      <Cell N="Width" V="{_num(width)}"/>\n'
        '      <Cell N="Height" V="0.25"/>\n'
        f'      <Cell N="LocPinX" V="{_num(width / 2)}"/>\n'
        '      <Cell N="LocPinY" V="0.125"/>\n'
        '      <Cell N="FillPattern" V="0"/>\n'
        '      <Cell N="LinePattern" V="0"/>\n'
        f'{_geometry_xml(_relative_points("process"), no_fill=True, no_line=True)}\n'
        f'      <Text>{escape(label)}</Text>\n'
        "    </Shape>"
    )


def _geometry_xml(points: list[tuple[float, float]], *, no_fill: bool = False, no_line: bool = False) -> str:
    rows = [
        '      <Section N="Geometry" IX="0">',
        f'        <Cell N="NoFill" V="{1 if no_fill else 0}"/>',
        f'        <Cell N="NoLine" V="{1 if no_line else 0}"/>',
        '        <Cell N="NoShow" V="0"/>',
    ]
    for index, (x, y) in enumerate(points, start=1):
        row_type = "RelMoveTo" if index == 1 else "RelLineTo"
        rows.append(f'        <Row T="{row_type}" IX="{index}">')
        rows.append(f'          <Cell N="X" V="{_num(x)}"/>')
        rows.append(f'          <Cell N="Y" V="{_num(y)}"/>')
        rows.append("        </Row>")
    rows.append("      </Section>")
    return "\n".join(rows)


def _relative_points(kind: str) -> list[tuple[float, float]]:
    if kind == "decision":
        return [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5), (0.5, 0)]
    if kind == "circle":
        return [(0.5, 0), (0.85, 0.15), (1, 0.5), (0.85, 0.85), (0.5, 1), (0.15, 0.85), (0, 0.5), (0.15, 0.15), (0.5, 0)]
    return [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]


def _midpoint(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)


def _content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>
  <Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>
  <Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/>
</Types>
"""


def _root_rels() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}">
  <Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def _document_rels() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}">
  <Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/>
</Relationships>
"""


def _pages_rels() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{REL_NS}">
  <Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page1.xml"/>
</Relationships>
"""


def _document_xml() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<VisioDocument xmlns="{CORE_NS}" xmlns:r="{OFFICE_REL_NS}" xml:space="preserve">
  <FaceNames>
    <FaceName NameU="Microsoft YaHei"/>
    <FaceName NameU="Calibri"/>
  </FaceNames>
  <StyleSheets>
    <StyleSheet ID="0" NameU="No Style" Name="No Style">
      <Cell N="EnableLineProps" V="1"/>
      <Cell N="EnableFillProps" V="1"/>
      <Cell N="EnableTextProps" V="1"/>
      <Cell N="LineWeight" V="0.01041666666666667"/>
      <Cell N="LineColor" V="0"/>
      <Cell N="LinePattern" V="1"/>
      <Cell N="FillForegnd" V="1"/>
      <Cell N="FillPattern" V="1"/>
      <Cell N="VerticalAlign" V="1"/>
      <Section N="Character">
        <Row IX="0">
          <Cell N="Font" V="Microsoft YaHei"/>
          <Cell N="Color" V="0"/>
          <Cell N="Size" V="0.1666666666666667"/>
        </Row>
      </Section>
      <Section N="Paragraph">
        <Row IX="0">
          <Cell N="HorzAlign" V="1"/>
          <Cell N="Bullet" V="0"/>
        </Row>
      </Section>
    </StyleSheet>
  </StyleSheets>
  <DocumentSheet NameU="TheDoc" Name="TheDoc" LineStyle="0" FillStyle="0" TextStyle="0">
    <Cell N="DocLangID" V="zh-CN"/>
  </DocumentSheet>
</VisioDocument>
"""


def _pages_xml(width: float, height: float) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Pages xmlns="{CORE_NS}" xmlns:r="{OFFICE_REL_NS}" xml:space="preserve">
  <Page ID="0" NameU="Page-1" Name="Page-1">
    <PageSheet LineStyle="0" FillStyle="0" TextStyle="0">
      <Cell N="PageWidth" V="{_num(width)}"/>
      <Cell N="PageHeight" V="{_num(height)}"/>
      <Cell N="PageScale" V="1"/>
      <Cell N="DrawingScale" V="1"/>
    </PageSheet>
    <Rel r:id="rId1"/>
  </Page>
</Pages>
"""


def _core_props() -> str:
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Mermaid Visio Export</dc:title>
  <dc:creator>Orbit Safe Claw</dc:creator>
  <cp:lastModifiedBy>Orbit Safe Claw</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>
"""


def _app_props() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Orbit Safe Claw</Application>
</Properties>
"""


def _num(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"
