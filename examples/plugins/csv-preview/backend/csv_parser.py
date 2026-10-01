from __future__ import annotations

import codecs
import csv
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_COLUMNS = 512
MAX_FIELD_CHARS = 64 * 1024
SAMPLE_ROWS = 64
SAMPLE_CHARS = 64 * 1024


def detect_encoding(path: Path) -> str:
    with path.open("rb") as handle:
        has_bom = handle.read(3) == b"\xef\xbb\xbf"
    encodings = ("utf-8-sig",) if has_bom else ("utf-8", "gb18030")
    for encoding in encodings:
        decoder = codecs.getincrementaldecoder(encoding)()
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV 编码失败，仅支持 UTF-8 和 GB18030")


def detect_dialect(text: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=[",", "\t", ";", "|"])
    except csv.Error:
        return csv.excel()


def normalize_header(value: str, index: int, seen: Counter[str]) -> tuple[str, str]:
    title = value.strip()
    base = "".join(
        ch.lower() if ch.isascii() and ch.isalnum() else "_" for ch in title
    ).strip("_") or f"column_{index}"
    display = title or f"Column {index}"
    column_id = base
    suffix = 1
    while column_id in seen:
        suffix += 1
        column_id = f"{base}_{suffix}"
    seen[column_id] += 1
    return column_id, display if suffix == 1 else f"{display} ({suffix})"


def _value_type(value: str) -> str:
    value = value.strip()
    if not value:
        return "empty"
    if value.lower() in {"true", "false"}:
        return "boolean"
    try:
        float(value)
        return "number"
    except ValueError:
        pass
    if len(value) >= 10 and value[4:5] in {"-", "/"}:
        try:
            datetime.fromisoformat(value.replace("/", "-").replace("Z", "+00:00"))
            return "date"
        except ValueError:
            pass
    return "text"


def decide_header(sample: list[list[str]], mode: str) -> tuple[bool, str]:
    if mode not in {"auto", "header", "no-header"}:
        raise ValueError(f"无效的 CSV 表头模式: {mode}")
    if not sample:
        return False, "empty"
    if mode != "auto":
        return mode == "header", "explicit"
    first = sample[0]
    following = [row for row in sample[1:] if row]
    if not first or not following or any(len(row) != len(first) for row in following):
        return False, "ambiguous"
    first_types = [_value_type(value) for value in first]
    data_types: list[str] = []
    for column in range(len(first)):
        types = [_value_type(row[column]) for row in following if row[column].strip()]
        if not types:
            data_types.append("empty")
            continue
        kind, count = Counter(types).most_common(1)[0]
        data_types.append(kind if count / len(types) >= 0.8 else "mixed")
    if all(kind in {"text", "empty"} for kind in first_types) and any(
        first_kind == "text" and data_kind in {"number", "boolean", "date"}
        for first_kind, data_kind in zip(first_types, data_types)
    ):
        return True, "header"
    if first_types == data_types and any(
        kind in {"number", "boolean", "date"} for kind in first_types
    ):
        return False, "data"
    return False, "ambiguous"


def _sort_value(value: str) -> tuple[int, float | str]:
    try:
        number = float(value)
        if not math.isnan(number):
            return 0, number
    except ValueError:
        pass
    return 1, value.lower()


def _sqlite_sort_value(cells_json: str, column: int) -> float | str:
    cells = json.loads(cells_json)
    value = cells[column] if column < len(cells) else ""
    return _sort_value(value)[1]


class CsvTableIndex:
    def __init__(
        self,
        database_path: Path,
        connection: sqlite3.Connection,
        title: str,
        columns: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        self.database_path = database_path
        self.connection = connection
        self.title = title
        self.columns = columns
        self.metadata = metadata
        self.total_rows = int(metadata["totalRows"])
        connection.create_function("csv_sort_value", 2, _sqlite_sort_value, deterministic=True)

    @classmethod
    def build(
        cls,
        source_path: Path,
        database_path: Path,
        *,
        title: str | None = None,
        default_page_size: int = 50,
        header_mode: str = "auto",
    ) -> CsvTableIndex:
        encoding = detect_encoding(source_path)
        connection = sqlite3.connect(database_path)
        previous_field_limit = csv.field_size_limit(MAX_FIELD_CHARS)
        try:
            connection.execute("PRAGMA temp_store=FILE")
            connection.execute("PRAGMA cache_size=-2048")
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute(
                "CREATE TABLE rows (row_no INTEGER PRIMARY KEY, cells_json TEXT NOT NULL, search_text TEXT NOT NULL)"
            )
            with source_path.open("r", encoding=encoding, newline="") as handle, connection:
                dialect = detect_dialect(handle.read(4096))
                handle.seek(0)
                reader = csv.reader(handle, dialect, strict=True)
                sample: list[list[str]] = []
                sampled_chars = 0
                for _ in range(SAMPLE_ROWS):
                    row = next(reader, None)
                    if row is None:
                        break
                    cls._check_row(row)
                    sample.append(row)
                    sampled_chars += sum(map(len, row))
                    if sampled_chars >= SAMPLE_CHARS:
                        break

                has_header, decision = decide_header(sample, header_mode)
                header = sample[0] if has_header else []
                columns: list[dict[str, Any]] = []
                seen: Counter[str] = Counter()
                row_count = 0

                def extend_columns(width: int) -> None:
                    while len(columns) < width:
                        column = len(columns)
                        raw_title = header[column] if column < len(header) else ""
                        column_id, column_title = normalize_header(raw_title, column + 1, seen)
                        columns.append(
                            {"id": column_id, "title": column_title, "sortable": True}
                        )

                def insert(row: list[str]) -> None:
                    nonlocal row_count
                    cls._check_row(row)
                    extend_columns(len(row))
                    row_count += 1
                    connection.execute(
                        "INSERT INTO rows VALUES (?, ?, ?)",
                        (
                            row_count,
                            json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                            " ".join(row).lower(),
                        ),
                    )

                extend_columns(max((len(row) for row in sample), default=0))
                for row in sample[1:] if has_header else sample:
                    insert(row)
                sample.clear()
                for row in reader:
                    insert(row)

                metadata = {
                    "encoding": encoding,
                    "delimiter": dialect.delimiter,
                    "hasHeader": has_header,
                    "headerMode": header_mode,
                    "headerDecision": decision,
                    "defaultPageSize": max(1, min(500, int(default_page_size))),
                    "totalRows": row_count,
                    "columns": columns,
                }
                connection.executemany(
                    "INSERT INTO metadata VALUES (?, ?)",
                    (
                        (key, json.dumps(value, ensure_ascii=False))
                        for key, value in metadata.items()
                    ),
                )
            return cls(database_path, connection, title or source_path.name, columns, metadata)
        except BaseException as exc:
            connection.close()
            database_path.unlink(missing_ok=True)
            if isinstance(exc, csv.Error):
                if "field larger than field limit" in str(exc):
                    raise ValueError(f"CSV 字段过大，最多 {MAX_FIELD_CHARS} 个字符") from exc
                raise ValueError(f"CSV 文件损坏: {exc}") from exc
            raise
        finally:
            csv.field_size_limit(previous_field_limit)

    @staticmethod
    def _check_row(row: list[str]) -> None:
        if len(row) > MAX_COLUMNS:
            raise ValueError(f"CSV 列数超限，最多 {MAX_COLUMNS} 列")

    def close(self) -> None:
        self.connection.close()


def query_csv_window(
    table: CsvTableIndex,
    *,
    offset: int,
    limit: int,
    query: str = "",
    sort: dict[str, Any] | None = None,
) -> dict[str, Any]:
    keyword = query.strip().lower()
    where = " WHERE instr(search_text, ?) > 0" if keyword else ""
    params: list[Any] = [keyword] if keyword else []
    total = (
        table.connection.execute("SELECT count(*) FROM rows" + where, params).fetchone()[0]
        if keyword
        else table.total_rows
    )
    order = "row_no ASC"
    column = next(
        (
            index
            for index, item in enumerate(table.columns)
            if item["id"] == (sort or {}).get("columnId")
        ),
        None,
    )
    if column is not None:
        direction = (
            "DESC"
            if str((sort or {}).get("direction") or "asc").lower() == "desc"
            else "ASC"
        )
        order = f"csv_sort_value(cells_json, ?) {direction}, row_no ASC"
        params.append(column)
    offset = max(0, int(offset or 0))
    limit = max(1, min(500, int(limit or table.metadata["defaultPageSize"])))
    records = table.connection.execute(
        "SELECT row_no, cells_json FROM rows"
        + where
        + f" ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    rows = []
    for row_no, cells_json in records:
        cells = json.loads(cells_json)
        rows.append(
            {
                "id": f"row-{row_no}",
                "cells": {
                    item["id"]: cells[index] if index < len(cells) else ""
                    for index, item in enumerate(table.columns)
                },
            }
        )
    return {
        "offset": offset,
        "limit": limit,
        "totalRows": total,
        "rows": rows,
        "appliedSort": sort or None,
    }
