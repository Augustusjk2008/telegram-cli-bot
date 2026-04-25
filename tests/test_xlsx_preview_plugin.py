from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from bot.plugins.service import PluginService


def _column_name(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _write_xlsx(path: Path, sheets: list[tuple[str, list[list[str]]]]) -> None:
    shared_strings: list[str] = []
    shared_index: dict[str, int] = {}

    def shared_id(value: str) -> int:
        if value not in shared_index:
            shared_index[value] = len(shared_strings)
            shared_strings.append(value)
        return shared_index[value]

    workbook_sheet_nodes: list[str] = []
    workbook_rel_nodes: list[str] = []
    sheet_entries: list[tuple[str, str]] = []
    content_type_nodes: list[str] = []

    for sheet_index, (sheet_name, rows) in enumerate(sheets, start=1):
        rel_id = f"rId{sheet_index}"
        workbook_sheet_nodes.append(
            f'<sheet name="{sheet_name}" sheetId="{sheet_index}" r:id="{rel_id}"/>'
        )
        workbook_rel_nodes.append(
            f'<Relationship Id="{rel_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{sheet_index}.xml"/>'
        )
        content_type_nodes.append(
            f'<Override PartName="/xl/worksheets/sheet{sheet_index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )

        row_nodes: list[str] = []
        for row_index, row in enumerate(rows, start=1):
            cell_nodes: list[str] = []
            for col_index, value in enumerate(row, start=1):
                if value == "":
                    continue
                ref = f"{_column_name(col_index)}{row_index}"
                cell_nodes.append(f'<c r="{ref}" t="s"><v>{shared_id(value)}</v></c>')
            row_nodes.append(f'<row r="{row_index}">{"".join(cell_nodes)}</row>')

        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_nodes)}</sheetData>'
            "</worksheet>"
        )
        sheet_entries.append((f"xl/worksheets/sheet{sheet_index}.xml", sheet_xml))

    shared_string_items = "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(workbook_sheet_nodes)}</sheets>'
        "</workbook>"
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(workbook_rel_nodes)}'
        "</Relationships>"
    )
    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f"{shared_string_items}"
        "</sst>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        f'{"".join(content_type_nodes)}'
        "</Types>"
    )
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
        for filename, content in sheet_entries:
            archive.writestr(filename, content)


def _join_block_text(block: dict[str, object]) -> str:
    return "".join(str(run.get("text") or "") for run in block.get("runs", []))


@pytest.mark.asyncio
async def test_xlsx_preview_plugin_renders_workbook_as_document(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/xlsx-preview"), plugins_root / "xlsx-preview")
    _write_xlsx(
        repo_root / "docs" / "roadmap.xlsx",
        [
            (
                "Summary",
                [
                    ["Milestone", "Status"],
                    ["Renderer", "Done"],
                    ["Plugin", "In Progress"],
                ],
            ),
            (
                "Owners",
                [
                    ["Area", "Owner"],
                    ["Frontend", "Kai"],
                ],
            ),
        ],
    )

    service = PluginService(repo_root, plugins_root=plugins_root)

    target = service.resolve_file_target("docs/roadmap.xlsx")
    assert target["kind"] == "plugin_view"
    assert target["pluginId"] == "xlsx-preview"
    assert target["viewId"] == "document"

    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="xlsx-preview",
        view_id="document",
        input_payload={"path": "docs/roadmap.xlsx"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["renderer"] == "document"
    assert rendered["mode"] == "snapshot"
    assert rendered["payload"]["title"] == "roadmap.xlsx"
    assert rendered["payload"]["statsText"] == "2 工作表 · 5 行预览"
    assert rendered["payload"]["blocks"][0]["type"] == "heading"
    assert _join_block_text(rendered["payload"]["blocks"][0]) == "Summary"
    assert any(block["type"] == "table" for block in rendered["payload"]["blocks"])

    await service.shutdown()


@pytest.mark.asyncio
async def test_xlsx_preview_plugin_truncates_large_sheet(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/xlsx-preview"), plugins_root / "xlsx-preview")
    header = [f"C{index}" for index in range(1, 15)]
    rows = [header] + [[f"R{row}C{col}" for col in range(1, 15)] for row in range(1, 45)]
    _write_xlsx(repo_root / "docs" / "large.xlsx", [("Large", rows)])

    service = PluginService(repo_root, plugins_root=plugins_root)
    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="xlsx-preview",
        view_id="document",
        input_payload={"path": "docs/large.xlsx"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    table = next(block for block in rendered["payload"]["blocks"] if block["type"] == "table")
    note = next(
        block for block in rendered["payload"]["blocks"]
        if block["type"] == "paragraph" and "仅预览前" in _join_block_text(block)
    )

    assert len(table["rows"]) == 40
    assert len(table["rows"][0]["cells"]) == 12
    assert _join_block_text(note) == "仅预览前 40 行、前 12 列。"

    await service.shutdown()


@pytest.mark.asyncio
async def test_xlsx_preview_plugin_shows_empty_sheet_message(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/xlsx-preview"), plugins_root / "xlsx-preview")
    _write_xlsx(repo_root / "docs" / "empty.xlsx", [("EmptySheet", [])])

    service = PluginService(repo_root, plugins_root=plugins_root)
    rendered = await service.render_view(
        bot_alias="main",
        plugin_id="xlsx-preview",
        view_id="document",
        input_payload={"path": "docs/empty.xlsx"},
        audit_context={"account_id": "u1", "bot_alias": "main"},
    )

    assert rendered["payload"]["blocks"][0]["type"] == "heading"
    assert rendered["payload"]["blocks"][1]["type"] == "paragraph"
    assert _join_block_text(rendered["payload"]["blocks"][1]) == "工作表为空。"

    await service.shutdown()


@pytest.mark.asyncio
async def test_xlsx_preview_plugin_rejects_invalid_zip(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "plugins"
    shutil.copytree(Path("examples/plugins/xlsx-preview"), plugins_root / "xlsx-preview")
    target = repo_root / "docs" / "broken.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not a zip")

    service = PluginService(repo_root, plugins_root=plugins_root)

    with pytest.raises(RuntimeError, match="XLSX 文件损坏或格式不支持"):
        await service.render_view(
            bot_alias="main",
            plugin_id="xlsx-preview",
            view_id="document",
            input_payload={"path": "docs/broken.xlsx"},
            audit_context={"account_id": "u1", "bot_alias": "main"},
        )

    await service.shutdown()
