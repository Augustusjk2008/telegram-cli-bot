from __future__ import annotations

import importlib.util
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest


BACKEND = Path(__file__).resolve().parents[1] / "examples/plugins/docx-preview/backend"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def paragraph(text: str = "", props: str = "", run_props: str = "") -> str:
    return f'<w:p><w:pPr>{props}</w:pPr><w:r><w:rPr>{run_props}</w:rPr><w:t>{text}</w:t></w:r></w:p>'


def cell(text: str = "", props: str = "", content: str | None = None) -> str:
    return f'<w:tc><w:tcPr>{props}</w:tcPr>{paragraph(text) if content is None else content}</w:tc>'


@pytest.fixture
def parse(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    spec = importlib.util.spec_from_file_location("tested_docx_parser", BACKEND / "docx_parser.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def render(body: str, *, styles: str = "", numbering: str = "", theme: str = "", settings: str = "",
               extra_parts: dict | None = None, write_artifact=None):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:a="{A}" xmlns:wp="{WP}"><w:body>{body}</w:body></w:document>')
            for path, root, content in (("word/styles.xml", "styles", styles), ("word/numbering.xml", "numbering", numbering),
                                        ("word/settings.xml", "settings", settings)):
                if content:
                    archive.writestr(path, f'<w:{root} xmlns:w="{W}">{content}</w:{root}>')
            if theme:
                archive.writestr("word/theme/theme1.xml", f'<a:theme xmlns:a="{A}"><a:themeElements>{theme}</a:themeElements></a:theme>')
            for path, content in (extra_parts or {}).items():
                archive.writestr(path, content)
        payload = module.parse_docx_document("sample.docx", buffer.getvalue(), write_artifact=write_artifact)
        json.dumps(payload, allow_nan=False)
        return payload

    return render


def test_defaults_style_chains_toggle_semantics_and_direct_overrides(parse):
    styles = '''
    <w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="24"/><w:color w:val="123456"/></w:rPr></w:rPrDefault>
      <w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault></w:docDefaults>
    <w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:rPr><w:rFonts w:ascii="Calibri"/></w:rPr></w:style>
    <w:style w:type="paragraph" w:styleId="Base"><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:i/><w:u w:val="single"/></w:rPr></w:style>
    <w:style w:type="paragraph" w:styleId="Custom"><w:basedOn w:val="Base"/><w:rPr><w:b/><w:i w:val="0"/></w:rPr></w:style>
    <w:style w:type="character" w:styleId="Accent"><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr></w:style>
    <w:style w:type="character" w:styleId="DerivedAccent"><w:basedOn w:val="Accent"/><w:rPr><w:sz w:val="30"/></w:rPr></w:style>
    '''
    body = paragraph("default") + '''<w:p><w:pPr><w:pStyle w:val="Custom"/></w:pPr>
      <w:r><w:t>inherited</w:t></w:r>
      <w:r><w:rPr><w:rStyle w:val="DerivedAccent"/></w:rPr><w:t>character</w:t></w:r>
      <w:r><w:rPr><w:rStyle w:val="DerivedAccent"/><w:b w:val="false"/><w:i w:val="off"/><w:u w:val="none"/><w:sz w:val="0"/></w:rPr><w:t>off</w:t></w:r>
    </w:p>'''
    payload = parse(body, styles=styles)
    assert payload["formatting"] == "document"
    assert payload["blocks"][0]["runs"][0]["fontFamily"] == "Calibri"
    inherited, character, direct = payload["blocks"][1]["runs"]
    assert inherited == {"text": "inherited", "fontSizePx": 16, "color": "#123456", "fontFamily": "Calibri", "bold": False, "italic": True, "underline": True}
    assert character["bold"] is True and character["fontSizePx"] == 20 and character["color"] == "#FF0000"
    assert {key: direct[key] for key in ("bold", "italic", "underline", "fontSizePx")} == {"bold": False, "italic": False, "underline": False, "fontSizePx": 0}
    assert payload["blocks"][1]["format"]["spaceAfterPx"] == 8


def test_theme_colors_fonts_mixed_text_and_background_resets(parse):
    theme = '''<a:clrScheme name="test"><a:dk1><a:sysClr val="windowText" lastClr="102030"/></a:dk1>
      <a:accent1><a:srgbClr val="808080"/></a:accent1></a:clrScheme>
      <a:fontScheme name="test"><a:majorFont><a:latin typeface="Cambria"/><a:ea/><a:font script="Hans" typeface="宋体"/></a:majorFont>
      <a:minorFont><a:latin typeface="Calibri"/><a:ea/><a:font script="Hans" typeface="微软雅黑"/><a:font script="Jpan" typeface="游ゴシック"/></a:minorFont></a:fontScheme>'''
    styles = '''<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Ignored" w:asciiTheme="minorHAnsi" w:eastAsiaTheme="minorEastAsia"/>
      <w:color w:val="FFFFFF" w:themeColor="text1"/><w:highlight w:val="yellow"/><w:shd w:fill="EEEEEE"/>
      </w:rPr></w:rPrDefault></w:docDefaults>'''
    body = paragraph("中文 English") + paragraph("日本語", run_props='<w:lang w:eastAsia="ja-JP"/><w:color w:themeColor="accent1" w:themeTint="80"/>')
    body += paragraph("override", run_props='<w:rFonts w:ascii="Arial" w:eastAsia="楷体"/><w:color w:themeColor="accent1" w:themeShade="80"/><w:highlight w:val="none"/><w:shd w:val="nil"/>')
    payload = parse(body, styles=styles, theme=theme, settings='<w:themeFontLang w:eastAsia="zh-CN"/>')
    first, japanese, direct = [b["runs"][0] for b in payload["blocks"]]
    assert (first["fontFamily"], first["fontFamilyEastAsia"], first["color"]) == ("Calibri", "微软雅黑", "#102030")
    assert first["highlightColor"] == "#FFFF00" and first["shadingColor"] == "#EEEEEE"
    assert japanese["fontFamilyEastAsia"] == "游ゴシック" and japanese["color"] == "#BFBFBF"
    assert (direct["fontFamily"], direct["fontFamilyEastAsia"], direct["color"]) == ("Arial", "楷体", "#404040")
    assert direct["highlightColor"] == direct["shadingColor"] == "transparent"


@pytest.mark.parametrize(("rule", "line", "expected"), [("auto", "360", {"mode": "multiple", "value": 1.5}),
    ("exact", "300", {"mode": "exact", "value": 20}), ("atLeast", "240", {"mode": "atLeast", "value": 16}),
    ("exact", "0", {"mode": "exact", "value": 0})])
def test_paragraph_geometry_spacing_inheritance_and_blank_baseline(parse, rule, line, expected):
    styles = '''<w:style w:type="paragraph" w:styleId="Body" w:default="true"><w:pPr><w:jc w:val="both"/>
      <w:ind w:left="720" w:right="360" w:firstLine="240"/><w:spacing w:before="120" w:after="240"/></w:pPr>
      <w:rPr><w:sz w:val="22"/></w:rPr></w:style>'''
    props = f'<w:jc w:val="center"/><w:ind w:left="0" w:hanging="180"/><w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="{rule}"/><w:rPr><w:sz w:val="36"/><w:i/></w:rPr>'
    blank = paragraph(props=props)
    payload = parse(paragraph("body") + blank, styles=styles)
    assert payload["blocks"][0]["format"]["align"] == "justify"
    assert payload["blocks"][1]["runs"] == [{"text": ""}]
    assert payload["blocks"][1]["format"] == {"align": "center", "indentLeftPx": 0, "indentRightPx": 24,
        "firstLineIndentPx": -12, "spaceBeforePx": 0, "spaceAfterPx": 0, "lineSpacing": expected,
        "textStyle": {"fontSizePx": 24, "italic": True}}


def test_inherited_headings_numbering_indents_counters_and_num_id_zero(parse):
    styles = '''<w:style w:type="paragraph" w:styleId="Heading2"><w:rPr><w:sz w:val="36"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="Chapter"><w:basedOn w:val="Heading2"/></w:style>
      <w:style w:type="paragraph" w:styleId="Items"><w:pPr><w:numPr><w:numId w:val="7"/></w:numPr><w:ind w:right="90"/></w:pPr></w:style>'''
    numbering = '''<w:abstractNum w:abstractNumId="3"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1)"/>
      <w:pPr><w:ind w:left="720" w:hanging="360"/><w:spacing w:after="60"/></w:pPr><w:rPr><w:color w:val="FF0000"/><w:rFonts w:ascii="Symbol"/></w:rPr></w:lvl>
      <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%1.%2"/><w:pPr><w:ind w:left="1440"/></w:pPr></w:lvl></w:abstractNum>
      <w:num w:numId="7"><w:abstractNumId w:val="3"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="3"/></w:lvlOverride></w:num>'''
    list_props = '<w:pStyle w:val="Items"/>'
    body = paragraph("Chapter", '<w:pStyle w:val="Chapter"/>') + paragraph("first", list_props)
    body += paragraph("nested", list_props + '<w:numPr><w:ilvl w:val="1"/></w:numPr>')
    body += paragraph("next", list_props + '<w:ind w:left="0"/>')
    body += paragraph("reset", list_props + '<w:numPr><w:ilvl w:val="1"/></w:numPr>')
    body += paragraph("ordinary", list_props + '<w:numPr><w:numId w:val="0"/></w:numPr>')
    blocks = parse(body, styles=styles, numbering=numbering)["blocks"]
    assert blocks[0]["type"] == "heading" and blocks[0]["level"] == 2 and blocks[0]["runs"][0]["fontSizePx"] == 24
    assert [b["marker"] for b in blocks[1:5]] == ["3)", "3.a", "4)", "4.a"]
    assert blocks[1]["format"] == {"indentLeftPx": 48, "indentRightPx": 6, "firstLineIndentPx": -24, "spaceAfterPx": 4}
    assert "color" not in blocks[1]["runs"][0]  # Numbering rPr applies only to the marker.
    assert blocks[1]["markerStyle"] == {"color": "#FF0000", "fontFamily": "Symbol"}
    assert blocks[3]["format"]["indentLeftPx"] == 0
    assert blocks[5]["type"] == "paragraph" and "indentLeftPx" not in blocks[5]["format"]


def test_hyperlinks_breaks_images_and_cell_paragraph_order(parse):
    drawing = '<w:drawing><wp:inline><wp:extent cx="952500" cy="476250"/><wp:docPr name="Picture" descr="diagram"/><a:graphic><a:blip r:embed="rId1"/></a:graphic></wp:inline></w:drawing>'
    body = f'<w:p><w:r><w:t>before</w:t></w:r><w:hyperlink r:id="link"><w:r><w:rPr><w:u w:val="single"/><w:color w:val="0000FF"/></w:rPr><w:t>link</w:t><w:tab/><w:br/>{drawing}<w:t>after</w:t></w:r></w:hyperlink></w:p>'
    body += '<w:tbl><w:tr>' + cell(content=paragraph("first") + f'<w:p><w:r>{drawing}</w:r></w:p>' + paragraph("last")) + '</w:tr></w:tbl>'
    written = []

    def artifact(filename, content, content_type):
        written.append((filename, content, content_type))
        return {"artifactId": f"image-{len(written)}"}

    payload = parse(body, extra_parts={"word/_rels/document.xml.rels": f'<Relationships><Relationship Id="rId1" Type="{R}/image" Target="media/image.png"/></Relationships>', "word/media/image.png": b"image-data"}, write_artifact=artifact)
    blocks = payload["blocks"]
    assert [b["type"] for b in blocks] == ["paragraph", "image", "paragraph", "table"]
    assert [r["text"] for r in blocks[0]["runs"]] == ["before", "link\t\n"]
    assert blocks[0]["runs"][1]["underline"] is True and blocks[2]["runs"][0]["text"] == "after"
    assert (blocks[1]["widthPx"], blocks[1]["heightPx"], blocks[1]["alt"]) == (100, 50, "diagram")
    assert [b["type"] for b in blocks[3]["rows"][0]["cells"][0]["paragraphs"]] == ["paragraph", "image", "paragraph"]
    assert len(written) == 2 and payload["statsText"].endswith("2 图片")


def test_table_widths_borders_padding_cell_formats_and_combined_merges(parse):
    table_props = '''<w:tblW w:type="pct" w:w="5000"/><w:tblBorders><w:top w:val="double" w:sz="12" w:color="112233"/>
      <w:bottom w:val="single" w:sz="6"/><w:insideH w:val="dashed" w:sz="6"/><w:insideV w:val="dotted" w:sz="3"/></w:tblBorders>
      <w:tblCellMar><w:top w:type="dxa" w:w="60"/><w:left w:type="dxa" w:w="120"/></w:tblCellMar>'''
    merged_props = '''<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/><w:shd w:fill="EEEEAA"/><w:vAlign w:val="center"/>
      <w:tcBorders><w:left w:val="nil"/></w:tcBorders><w:tcMar><w:top w:w="0" w:type="dxa"/></w:tcMar>'''
    content = paragraph("center", '<w:jc w:val="center"/>', '<w:b/>') + paragraph("right", '<w:jc w:val="right"/>', '<w:i/>') + '<w:p/>'
    body = f'<w:tbl><w:tblPr>{table_props}</w:tblPr><w:tblGrid><w:gridCol w:w="1500"/><w:gridCol w:w="3000"/><w:gridCol w:w="1500"/></w:tblGrid><w:tr>'
    body += cell(props=merged_props, content=content) + cell("top-right", '<w:tcW w:type="dxa" w:w="900"/>') + '</w:tr><w:tr>'
    body += cell(props='<w:gridSpan w:val="2"/><w:vMerge/>') + cell("bottom-right") + '</w:tr></w:tbl>'
    table = parse(body)["blocks"][0]
    assert table["width"] == {"unit": "percent", "value": 100} and table["columnWidthsPx"] == [100, 200, 100]
    top = table["rows"][0]["cells"][0]
    assert top["rowSpan"] == top["colSpan"] == 2 and len(table["rows"][1]["cells"]) == 1
    assert top["width"] == {"unit": "px", "value": 300} and top["verticalAlign"] == "center"
    assert top["padding"] == {"topPx": 0, "leftPx": 8} and top["shadingColor"] == "#EEEEAA"
    assert top["borders"]["top"] == {"style": "double", "widthPx": 2, "color": "#112233"}
    assert top["borders"]["left"]["style"] == "none" and top["borders"]["bottom"]["style"] == "solid"
    assert top["paragraphs"][0]["format"]["align"] == "center" and top["paragraphs"][1]["format"]["align"] == "right"
    assert [r["text"] for r in top["runs"]] == ["center", "\n", "right", "\n", ""]
    assert table["rows"][0]["cells"][1]["width"] == {"unit": "px", "value": 60}


def test_table_style_inheritance_conditional_banding_and_direct_precedence(parse):
    styles = '''<w:style w:type="table" w:styleId="Base"><w:tblPr><w:tblCellMar><w:left w:type="dxa" w:w="90"/></w:tblCellMar></w:tblPr>
      <w:rPr><w:rFonts w:ascii="Arial"/><w:sz w:val="20"/></w:rPr><w:pPr><w:spacing w:after="0"/></w:pPr>
      <w:tblStylePr w:type="band1Horz"><w:tcPr><w:shd w:fill="EEEEEE"/></w:tcPr></w:tblStylePr>
      <w:tblStylePr w:type="band2Horz"><w:tcPr><w:shd w:fill="DDDDDD"/></w:tcPr></w:tblStylePr>
      <w:tblStylePr w:type="firstCol"><w:tcPr><w:shd w:fill="CCCCCC"/></w:tcPr></w:tblStylePr>
      <w:tblStylePr w:type="firstRow"><w:tcPr><w:shd w:fill="000080"/></w:tcPr><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:pPr><w:jc w:val="center"/></w:pPr></w:tblStylePr>
      </w:style><w:style w:type="table" w:styleId="Custom"><w:basedOn w:val="Base"/>
      <w:tblStylePr w:type="firstRow"><w:tcPr><w:shd w:fill="111188"/></w:tcPr></w:tblStylePr>
      <w:tblStylePr w:type="nwCell"><w:tcPr><w:shd w:fill="FF0000"/></w:tcPr></w:tblStylePr></w:style>'''
    body = '<w:tbl><w:tblPr><w:tblStyle w:val="Custom"/><w:tblLook w:val="04A0"/><w:tblCellMar><w:left w:type="dxa" w:w="0"/></w:tblCellMar></w:tblPr>'
    body += '<w:tr>' + cell("corner") + cell(content=paragraph("header", '<w:jc w:val="right"/>', '<w:b w:val="0"/>')) + '</w:tr>'
    body += '<w:tr>' + cell("column") + cell("band1") + '</w:tr>'
    body += '<w:tr>' + cell("column") + cell("band2", '<w:shd w:fill="ABCDEF"/>') + '</w:tr>'
    body += '<w:tr>' + cell("column") + cell("band1") + '</w:tr></w:tbl>'
    table = parse(body, styles=styles)["blocks"][0]
    colors = [[c["shadingColor"] for c in row["cells"]] for row in table["rows"]]
    assert colors == [["#FF0000", "#111188"], ["#CCCCCC", "#EEEEEE"], ["#CCCCCC", "#ABCDEF"], ["#CCCCCC", "#EEEEEE"]]
    header = table["rows"][0]["cells"][1]
    assert header["padding"] == {"leftPx": 0}
    assert header["paragraphs"][0]["format"]["align"] == "right"
    assert header["runs"][0] == {"text": "header", "fontFamily": "Arial", "fontSizePx": 40 / 3, "color": "#FFFFFF", "bold": False}


def test_legacy_horizontal_merge_and_orphan_vertical_continuation(parse):
    body = '<w:tbl><w:tr>' + cell("left", '<w:hMerge w:val="restart"/>') + cell(props='<w:hMerge/>') + cell("orphan", '<w:vMerge/>') + '</w:tr></w:tbl>'
    cells = parse(body)["blocks"][0]["rows"][0]["cells"]
    assert len(cells) == 2 and cells[0]["colSpan"] == 2
    assert len(cells[0]["paragraphs"]) == 1
    assert cells[1]["runs"][0]["text"] == "orphan" and "rowSpan" not in cells[1]


def test_missing_cyclic_styles_and_malformed_optional_properties_do_not_lose_text(parse):
    styles = '''<w:style w:type="paragraph" w:styleId="A"><w:basedOn w:val="B"/><w:rPr><w:color w:val="00AA00"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="B"><w:basedOn w:val="A"/><w:rPr><w:sz w:val="24"/></w:rPr></w:style>
      <w:style w:type="character" w:styleId="Loop"><w:basedOn w:val="Loop"/><w:rPr><w:i/></w:rPr></w:style>'''
    props = '<w:pStyle w:val="A"/><w:ind w:left="nan"/><w:spacing w:line="oops" w:after="-2"/><w:numPr><w:numId w:val="no"/><w:ilvl w:val="NaN"/></w:numPr>'
    runs = '<w:rStyle w:val="Loop"/><w:sz w:val="inf"/><w:b w:val="maybe"/><w:u w:val="madeup"/><w:color w:val="red;display:none"/><w:highlight w:val="url(x)"/>'
    body = paragraph("safe", props, runs) + paragraph("missing", '<w:pStyle w:val="unknown"/>')
    body += '<w:tbl><w:tblPr><w:tblStyle w:val="unknown"/><w:tblW w:type="pct" w:w="NaN"/><w:tblLook w:val="bad-mask"/></w:tblPr><w:tr>'
    body += cell("cell", '<w:gridSpan w:val="bogus"/><w:tcW w:w="-2"/><w:tcMar><w:top w:w="inf"/></w:tcMar>') + '</w:tr></w:tbl>'
    blocks = parse(body, styles=styles)["blocks"]
    assert blocks[0]["runs"] == [{"text": "safe", "fontSizePx": 16, "color": "#00AA00", "italic": True}]
    assert blocks[1]["runs"] == [{"text": "missing"}]
    assert blocks[2]["rows"][0]["cells"][0]["runs"] == [{"text": "cell"}]
    assert "width" not in blocks[2]


def test_numbering_style_link_level_binding_and_level_override(parse):
    styles = '''<w:style w:type="numbering" w:styleId="NumberStyle"><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr></w:style>
      <w:style w:type="paragraph" w:styleId="Nested"><w:pPr><w:numPr><w:numId w:val="2"/></w:numPr></w:pPr></w:style>'''
    numbering = '''<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/><w:pStyle w:val="Nested"/>
      <w:pPr><w:ind w:left="1440"/></w:pPr></w:lvl></w:abstractNum>
      <w:abstractNum w:abstractNumId="1"><w:numStyleLink w:val="NumberStyle"/></w:abstractNum>
      <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
      <w:num w:numId="2"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="1"><w:lvl w:ilvl="1">
      <w:start w:val="4"/><w:numFmt w:val="upperRoman"/><w:lvlText w:val="%2."/><w:pStyle w:val="Nested"/>
      <w:pPr><w:ind w:left="1080" w:hanging="360"/></w:pPr></w:lvl></w:lvlOverride></w:num>'''
    block = parse(paragraph("item", '<w:pStyle w:val="Nested"/>'), styles=styles, numbering=numbering)["blocks"][0]
    assert block["marker"] == "IV." and block["depth"] == 1
    assert block["format"] == {"indentLeftPx": 72, "firstLineIndentPx": -24}


def test_numbering_indent_overrides_paragraph_style_but_direct_indent_wins(parse):
    styles = '''<w:style w:type="paragraph" w:styleId="List"><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr>
      <w:ind w:left="360" w:hanging="120"/></w:pPr></w:style>'''
    numbering = '''<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/>
      <w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
      <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'''
    props = '<w:pStyle w:val="List"/>'
    blocks = parse(paragraph("numbering", props) + paragraph("direct", props + '<w:ind w:left="0" w:firstLine="0"/>'),
                   styles=styles, numbering=numbering)["blocks"]
    assert blocks[0]["format"] == {"indentLeftPx": 48, "firstLineIndentPx": -24}
    assert blocks[1]["format"] == {"indentLeftPx": 0, "firstLineIndentPx": 0}


def test_table_caps_grid_gaps_spans_and_accumulated_horizontal_merges(parse):
    styles = '''<w:style w:type="table" w:styleId="Edges"><w:tblStylePr w:type="lastCol">
      <w:tcPr><w:shd w:fill="123456"/></w:tcPr></w:tblStylePr></w:style>'''
    body = '''<w:tbl><w:tblPr><w:tblStyle w:val="Edges"/><w:tblLook w:lastColumn="1"/></w:tblPr>
      <w:tr><w:trPr><w:gridAfter w:val="2147483647"/></w:trPr>'''
    body += cell("after", '<w:gridSpan w:val="2147483647"/>') + '</w:tr>'
    body += '<w:tr><w:trPr><w:gridBefore w:val="2147483647"/></w:trPr>'
    body += cell("left", '<w:gridSpan w:val="800"/><w:hMerge w:val="restart"/>')
    body += cell("right", '<w:gridSpan w:val="800"/><w:hMerge/>') + cell("edge") + '</w:tr></w:tbl>'
    rows = parse(body, styles=styles)["blocks"][0]["rows"]
    assert rows[0]["cells"][0]["colSpan"] == 1000
    assert [c.get("colSpan", 1) for c in rows[1]["cells"]] == [1000, 1000, 1]
    assert [r["text"] for r in rows[1]["cells"][1]["runs"]] == ["left", "\n", "right"]
    # An uncapped gridAfter would prevent the following row from reaching the last column.
    assert rows[1]["cells"][-1]["shadingColor"] == "#123456"


def test_table_direct_defaults_override_style_cell_properties_and_row_exceptions(parse):
    styles = '''<w:style w:type="table" w:styleId="Table"><w:tcPr><w:shd w:fill="000000"/>
      <w:tcBorders><w:top w:val="double"/></w:tcBorders><w:tcMar><w:left w:w="90" w:type="dxa"/></w:tcMar></w:tcPr></w:style>'''
    body = '''<w:tbl><w:tblPr><w:tblStyle w:val="Table"/><w:shd w:fill="FFFFFF"/>
      <w:tblCellMar><w:left w:w="0" w:type="dxa"/></w:tblCellMar><w:tblBorders><w:top w:val="nil"/></w:tblBorders></w:tblPr>
      <w:tr>''' + cell("inherited") + cell("direct", '<w:shd w:fill="ABCDEF"/>') + '''</w:tr>
      <w:tr><w:tblPrEx><w:shd w:fill="EEEEEE"/></w:tblPrEx>''' + cell("exception") + cell("exception") + '</w:tr></w:tbl>'
    rows = parse(body, styles=styles)["blocks"][0]["rows"]
    first = rows[0]["cells"][0]
    assert first["shadingColor"] == "#FFFFFF" and first["borders"]["top"]["style"] == "none"
    assert first["padding"]["leftPx"] == 0 and rows[0]["cells"][1]["shadingColor"] == "#ABCDEF"
    assert rows[1]["cells"][0]["shadingColor"] == "#EEEEEE"


def test_table_band_sizes_column_bands_and_explicit_condition_flags(parse):
    styles = '''<w:style w:type="table" w:styleId="Bands"><w:tblPr><w:tblStyleRowBandSize w:val="2"/></w:tblPr>
      <w:tblStylePr w:type="band1Horz"><w:tcPr><w:shd w:fill="111111"/></w:tcPr></w:tblStylePr>
      <w:tblStylePr w:type="band2Horz"><w:tcPr><w:shd w:fill="222222"/></w:tcPr></w:tblStylePr>
      <w:tblStylePr w:type="band2Vert"><w:tcPr><w:shd w:fill="333333"/></w:tcPr></w:tblStylePr>
      <w:tblStylePr w:type="lastRow"><w:tcPr><w:shd w:fill="444444"/></w:tcPr></w:tblStylePr></w:style>'''
    body = '<w:tbl><w:tblPr><w:tblStyle w:val="Bands"/><w:tblLook w:val="0000"/></w:tblPr>'
    body += ''.join('<w:tr>' + cell("a") + cell("b") + '</w:tr>' for _ in range(3))
    body += '<w:tr>' + cell("a", '<w:cnfStyle w:lastRow="1"/>') + cell("b") + '</w:tr></w:tbl>'
    rows = parse(body, styles=styles)["blocks"][0]["rows"]
    assert [[c["shadingColor"] for c in r["cells"]] for r in rows] == [
        ["#111111", "#333333"], ["#111111", "#333333"], ["#222222", "#333333"], ["#444444", "#333333"]]


def test_table_styles_set_bold_and_conditional_false_clears_it(parse):
    styles = '''<w:style w:type="table" w:styleId="Base"><w:rPr><w:b/></w:rPr></w:style>
      <w:style w:type="table" w:styleId="Derived"><w:basedOn w:val="Base"/><w:rPr><w:b/></w:rPr>
      <w:tblStylePr w:type="firstRow"><w:rPr><w:b w:val="0"/></w:rPr></w:tblStylePr></w:style>'''
    body = '<w:tbl><w:tblPr><w:tblStyle w:val="Derived"/><w:tblLook w:firstRow="1"/></w:tblPr>'
    body += '<w:tr>' + cell("header") + '</w:tr><w:tr>' + cell("body") + '</w:tr></w:tbl>'
    rows = parse(body, styles=styles)["blocks"][0]["rows"]
    assert rows[0]["cells"][0]["runs"][0]["bold"] is False
    assert rows[1]["cells"][0]["runs"][0]["bold"] is True
