from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1] / "examples/plugins/csv-preview/backend"


@pytest.fixture
def parser(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    spec = importlib.util.spec_from_file_location("csv_preview_parser_test", BACKEND / "csv_parser.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(parser, tmp_path: Path, content: bytes, *, mode: str = "auto", page_size: int = 50):
    source = tmp_path / "sample.csv"
    database = tmp_path / "index.sqlite"
    source.write_bytes(content)
    table = parser.CsvTableIndex.build(
        source,
        database,
        default_page_size=page_size,
        header_mode=mode,
    )
    return source, database, table


def test_auto_no_header_keeps_first_numeric_row(parser, tmp_path: Path) -> None:
    _, _, table = build(parser, tmp_path, b"1,2\n3,4\n")

    window = parser.query_csv_window(table, offset=0, limit=50)

    assert table.metadata["hasHeader"] is False
    assert table.metadata["headerDecision"] == "data"
    assert [row["cells"]["column_1"] for row in window["rows"]] == ["1", "3"]
    table.close()


def test_auto_header_uses_descriptive_first_row(parser, tmp_path: Path) -> None:
    _, _, table = build(parser, tmp_path, b"name,value\na,1\nb,2\n")

    assert table.metadata["hasHeader"] is True
    assert [column["id"] for column in table.columns] == ["name", "value"]
    assert parser.query_csv_window(table, offset=0, limit=50)["totalRows"] == 2
    table.close()


@pytest.mark.parametrize(
    ("mode", "has_header", "row_count", "first_column"),
    [
        ("header", True, 1, "a"),
        ("no-header", False, 2, "name"),
    ],
)
def test_explicit_header_modes(parser, tmp_path: Path, mode: str, has_header: bool, row_count: int, first_column: str) -> None:
    _, _, table = build(parser, tmp_path, b"name,value\na,1\n", mode=mode)

    window = parser.query_csv_window(table, offset=0, limit=50)

    assert table.metadata["hasHeader"] is has_header
    assert table.metadata["headerDecision"] == "explicit"
    assert window["totalRows"] == row_count
    assert window["rows"][0]["cells"][table.columns[0]["id"]] == first_column
    table.close()


def test_ambiguous_auto_mode_preserves_first_row(parser, tmp_path: Path) -> None:
    _, _, table = build(parser, tmp_path, b"one,two\nthree,four\n")

    assert table.metadata["hasHeader"] is False
    assert table.metadata["headerDecision"] == "ambiguous"
    assert parser.query_csv_window(table, offset=0, limit=50)["totalRows"] == 2
    table.close()


def test_quoted_fields_bom_gb18030_and_empty_rows(parser, tmp_path: Path) -> None:
    quoted_dir = tmp_path / "quoted"
    quoted_dir.mkdir()
    _, _, quoted = build(parser, quoted_dir, b"title,body\n\"a,b\",\"line 1\nline 2\"\n", mode="header")
    rows = parser.query_csv_window(quoted, offset=0, limit=50)["rows"]
    assert rows[0]["cells"]["title"] == "a,b"
    assert rows[0]["cells"]["body"] == "line 1\nline 2"
    quoted.close()

    bom_dir = tmp_path / "bom"
    bom_dir.mkdir()
    _, _, bom = build(parser, bom_dir, b"\xef\xbb\xbfname,value\na,1\n")
    assert bom.metadata["encoding"] == "utf-8-sig"
    bom.close()

    gb_dir = tmp_path / "gb"
    gb_dir.mkdir()
    _, _, gb = build(parser, gb_dir, "名称,值\n甲,1\n".encode("gb18030"))
    assert gb.metadata["encoding"] == "gb18030"
    assert gb.columns[0]["title"] == "名称"
    gb.close()

    blank_dir = tmp_path / "blank"
    blank_dir.mkdir()
    _, _, blank = build(parser, blank_dir, b"a,b\n\n1,2\n", mode="header")
    assert blank.total_rows == 2
    blank.close()


def test_search_sort_and_paging_only_return_requested_rows(parser, tmp_path: Path) -> None:
    _, _, table = build(parser, tmp_path, b"name,value\na,10\nb,2\nc,30\n", page_size=2)

    sorted_window = parser.query_csv_window(
        table,
        offset=1,
        limit=1,
        sort={"columnId": "value", "direction": "asc"},
    )
    searched_window = parser.query_csv_window(table, offset=0, limit=1, query="c")

    assert sorted_window["totalRows"] == 3
    assert sorted_window["rows"][0]["cells"]["name"] == "a"
    assert searched_window["totalRows"] == 1
    assert searched_window["rows"][0]["cells"]["name"] == "c"
    assert len(searched_window["rows"]) == 1
    table.close()


def test_large_index_reads_first_and_last_page_without_rows_list(parser, tmp_path: Path) -> None:
    content = b"value\n" + b"\n".join(str(index).encode() for index in range(1000)) + b"\n"
    _, database, table = build(parser, tmp_path, content, mode="header", page_size=7)

    first = parser.query_csv_window(table, offset=0, limit=7)
    last = parser.query_csv_window(table, offset=993, limit=7)

    assert not hasattr(table, "rows")
    assert database.exists()
    assert first["rows"][0]["cells"]["value"] == "0"
    assert last["rows"][-1]["cells"]["value"] == "999"
    table.close()


def test_index_rejects_column_and_field_limits_and_removes_partial_database(parser, tmp_path: Path) -> None:
    too_many_columns = tmp_path / "columns.csv"
    too_many_columns.write_text(",".join("x" for _ in range(parser.MAX_COLUMNS + 1)), encoding="utf-8")
    columns_db = tmp_path / "columns.sqlite"
    with pytest.raises(ValueError, match="列数超限"):
        parser.CsvTableIndex.build(too_many_columns, columns_db)
    assert not columns_db.exists()

    too_large = tmp_path / "field.csv"
    too_large.write_text("x\n" + ("a" * (parser.MAX_FIELD_CHARS + 1)), encoding="utf-8")
    field_db = tmp_path / "field.sqlite"
    with pytest.raises(ValueError, match="字段过大"):
        parser.CsvTableIndex.build(too_large, field_db)
    assert not field_db.exists()
