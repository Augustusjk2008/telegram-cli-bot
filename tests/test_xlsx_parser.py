from __future__ import annotations

import importlib.util
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


BACKEND = Path(__file__).resolve().parents[1] / "examples/plugins/xlsx-preview/backend"
X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
SHEET = "xl/worksheets/sheet1.xml"


@pytest.fixture
def xlsx_module():
    spec = importlib.util.spec_from_file_location("tested_xlsx_parser", BACKEND / "xlsx_parser.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def xlsx_bytes(rows: str = "", *, shared_strings: str = "", empty_workbook: bool = False) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        sheet = "" if empty_workbook else '<sheet name="Data" r:id="rId1"/>'
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{X}" xmlns:r="{R}"><sheets>{sheet}</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{P}"><Relationship Id="rId1" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(SHEET, f'<worksheet xmlns="{X}"><sheetData>{rows}</sheetData></worksheet>')
        if shared_strings:
            archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{X}">{shared_strings}</sst>')
    return buffer.getvalue()


def test_preview_stops_after_one_extra_valid_row_and_releases_consumed_nodes(xlsx_module, monkeypatch):
    blank_rows = 2000
    rows = '<row/>' * blank_rows
    rows += ''.join(f'<row><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, 41))
    rows += '<row><c r="1"><v>invalid reference</v></c></row>' * 5
    rows += '<row><c r="A41"><v>41</v></c></row>'
    rows += f'<row><c r="A42" t="inlineStr"><is><t>{"tail" * 64}</t></is></c></row>' * 5000
    content = xlsx_bytes(rows)
    with ZipFile(BytesIO(content)) as archive:
        sheet_size = archive.getinfo(SHEET).file_size

    real_open = xlsx_module.ZipFile.open
    real_read = xlsx_module.ZipFile.read
    real_iterparse = xlsx_module.ET.iterparse
    bytes_read = 0
    streams = []
    observed = {"rows": 0}

    def tracked_open(archive, name, *args, **kwargs):
        stream = real_open(archive, name, *args, **kwargs)
        if name == SHEET:
            streams.append(stream)
            stream_read = stream.read

            def counted_read(*args, **kwargs):
                nonlocal bytes_read
                data = stream_read(*args, **kwargs)
                bytes_read += len(data)
                return data

            monkeypatch.setattr(stream, "read", counted_read)
        return stream

    def guarded_read(archive, name, *args, **kwargs):
        assert name != SHEET, "worksheet must be streamed rather than archive.read"
        return real_read(archive, name, *args, **kwargs)

    def tracked_iterparse(*args, **kwargs):
        for event, node in real_iterparse(*args, **kwargs):
            if event == "start" and node.tag == f"{{{X}}}sheetData":
                observed["sheet_data"] = node
            if event == "end" and node.tag in {f"{{{X}}}row", f"{{{X}}}c"}:
                observed["rows"] += node.tag == f"{{{X}}}row"
                parent = observed["sheet_data"] if node.tag == f"{{{X}}}row" else observed["row"]
                observed["last_node"] = node
                observed["last_parent"] = parent
                yield event, node
                assert len(node) == 0 and node not in parent
            else:
                if event == "start" and node.tag == f"{{{X}}}row":
                    observed["row"] = node
                yield event, node

    monkeypatch.setattr(xlsx_module.ZipFile, "open", tracked_open)
    monkeypatch.setattr(xlsx_module.ZipFile, "read", guarded_read)
    monkeypatch.setattr(xlsx_module.ET, "iterparse", tracked_iterparse)
    payload = xlsx_module.parse_xlsx_document("large.xlsx", content)

    assert observed["rows"] == blank_rows + 40 + 5 + 1
    assert len(observed["last_node"]) == 0 and observed["last_node"] not in observed["last_parent"]
    assert 0 < bytes_read < sheet_size
    assert len(streams) == 1 and streams[0].closed
    table = payload["blocks"][1]
    assert [row["cells"][0]["runs"][0]["text"] for row in table["rows"]] == [str(i) for i in range(1, 41)]
    assert payload["statsText"] == "1 工作表 · 40 行预览"
    assert payload["blocks"][2]["runs"] == [{"text": "仅预览前 40 行、前 12 列。"}]


def test_exact_row_limit_with_trailing_empty_rows_is_not_truncated(xlsx_module):
    rows = ''.join(f'<row><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, 41))
    rows += '<row/><row><c><v>missing reference</v></c></row>'
    payload = xlsx_module.parse_xlsx_document("exact.xlsx", xlsx_bytes(rows))
    assert len(payload["blocks"][1]["rows"]) == 40
    assert [block["type"] for block in payload["blocks"]] == ["heading", "table"]


def test_visible_columns_cell_types_and_payload_are_preserved(xlsx_module, monkeypatch):
    rows = '''<row>
        <c r="A1" t="s"><v>0</v></c>
        <c r="B1" t="inlineStr"><is><r><t> Inline </t></r><r><t>rich </t></r></is></c>
        <c r="C1" t="str"><v> cached &amp; string </v></c>
        <c r="D1" t="b"><v>1</v></c><c r="E1" t="b"><v>0</v></c>
        <c r="F1"><v>42.5</v></c><c r="G1" t="s"><v>99</v></c><c r="H1"/>
        <c r="L1" t="inlineStr"><is><t>last visible</t></is></c>
        <c r="M1"><v>hidden</v></c>
        </row><row><c r="N2"><v>outside preview</v></c></row><row><c r="A3"/></row>'''
    content = xlsx_bytes(rows, shared_strings='<si><r><t>Shared </t></r><r><t>text</t></r></si>')
    with ZipFile(BytesIO(content)) as archive:
        monkeypatch.setattr(xlsx_module, "MAX_UNCOMPRESSED_BYTES", sum(info.file_size for info in archive.infolist()))
    real_cell_text = xlsx_module._cell_text

    def visible_cell_text(cell, shared_strings):
        assert xlsx_module._column_index(cell.attrib["r"]) <= 12
        return real_cell_text(cell, shared_strings)

    monkeypatch.setattr(xlsx_module, "_cell_text", visible_cell_text)
    payload = xlsx_module.parse_xlsx_document("folder/sample.xlsx", content)
    assert set(payload) == {"path", "title", "statsText", "blocks"}
    assert (payload["path"], payload["title"], payload["statsText"]) == (
        "folder/sample.xlsx", "sample.xlsx", "1 工作表 · 3 行预览",
    )
    assert payload["blocks"][0] == {"type": "heading", "level": 2, "runs": [{"text": "Data"}]}
    table = payload["blocks"][1]
    assert table["type"] == "table"
    assert [[cell["runs"][0]["text"] for cell in row["cells"]] for row in table["rows"]] == [
        ["Shared text", "Inline rich", "cached & string", "TRUE", "FALSE", "42.5", "", "", "", "", "", "last visible"],
        [""] * 12,
        [""] * 12,
    ]
    assert payload["blocks"][2]["runs"] == [{"text": "仅预览前 40 行、前 12 列。"}]


@pytest.mark.parametrize("rows", ["", "<row/>", '<row><c r="1"><v>invalid</v></c></row>'])
def test_empty_sheet_message_is_preserved(xlsx_module, rows):
    payload = xlsx_module.parse_xlsx_document("empty.xlsx", xlsx_bytes(rows))
    assert payload["statsText"] == "1 工作表 · 0 行预览"
    assert payload["blocks"][1] == {"type": "paragraph", "runs": [{"text": "工作表为空。"}]}


def test_empty_workbook_message_is_preserved(xlsx_module):
    payload = xlsx_module.parse_xlsx_document("empty.xlsx", xlsx_bytes(empty_workbook=True))
    assert payload["statsText"] == "0 工作表 · 0 行预览"
    assert payload["blocks"] == [{"type": "paragraph", "runs": [{"text": "工作簿为空。"}]}]


def test_total_uncompressed_size_is_rejected_before_any_member_read(xlsx_module, monkeypatch):
    content = xlsx_bytes('<row><c r="A1"><v>1</v></c></row>')
    with ZipFile(BytesIO(content)) as archive:
        sizes = [info.file_size for info in archive.infolist()]
    limit = sum(sizes) - 1
    assert max(sizes) < limit
    monkeypatch.setattr(xlsx_module, "MAX_UNCOMPRESSED_BYTES", limit)
    monkeypatch.setattr(xlsx_module.ZipFile, "read", lambda *_args, **_kwargs: pytest.fail("archive.read must not run"))
    monkeypatch.setattr(xlsx_module.ZipFile, "open", lambda *_args, **_kwargs: pytest.fail("archive.open must not run"))
    with pytest.raises(RuntimeError, match="XLSX 解压内容超过预览限制"):
        xlsx_module.parse_xlsx_document("oversized.xlsx", content)
