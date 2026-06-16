from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any


def detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in ("utf-8", "gb18030"):
        try:
            data.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def detect_dialect(text: str) -> csv.Dialect:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
    except csv.Error:

        class Dialect(csv.Dialect):
            delimiter = ","
            quotechar = '"'
            doublequote = True
            escapechar = None
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
            skipinitialspace = False

        return Dialect()


def normalize_header(value: str, index: int, seen: Counter[str]) -> tuple[str, str]:
    title = value.strip()
    base = "".join(
        ch.lower() if ch.isascii() and ch.isalnum() else "_" for ch in title
    ).strip("_")
    if not base:
        base = f"column_{index}"
        display = title or f"Column {index}"
    else:
        display = title or f"Column {index}"
    seen[base] += 1
    suffix = seen[base]
    column_id = base if suffix == 1 else f"{base}_{suffix}"
    column_title = display if suffix == 1 else f"{display} ({suffix})"
    return column_id, column_title


def parse_csv_table(
    path: str, content: bytes, default_page_size: int = 50
) -> dict[str, Any]:
    encoding = detect_encoding(content)
    text = content.decode(encoding)
    dialect = detect_dialect(text)
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return {
            "title": path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            "encoding": encoding,
            "columns": [],
            "rows": [],
            "metadata": {
                "encoding": encoding,
                "delimiter": getattr(dialect, "delimiter", ","),
                "hasHeader": False,
                "defaultPageSize": max(1, int(default_page_size or 50)),
            },
        }

    header = rows[0]
    has_header = any(cell.strip() for cell in header)
    data_rows = rows[1:] if has_header else rows
    max_len = max((len(row) for row in rows), default=0)
    seen: Counter[str] = Counter()
    columns: list[dict[str, Any]] = []
    column_ids: list[str] = []

    for index in range(max_len):
        raw_title = header[index] if has_header and index < len(header) else ""
        column_id, column_title = normalize_header(raw_title, index + 1, seen)
        column_ids.append(column_id)
        columns.append(
            {
                "id": column_id,
                "title": column_title,
                "sortable": True,
            }
        )

    parsed_rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(data_rows, start=1):
        cells = {
            column_ids[index]: row[index] if index < len(row) else ""
            for index in range(len(column_ids))
        }
        parsed_rows.append(
            {
                "id": f"row-{row_index}",
                "cells": cells,
            }
        )

    return {
        "title": path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        "encoding": encoding,
        "columns": columns,
        "rows": parsed_rows,
        "metadata": {
            "encoding": encoding,
            "delimiter": getattr(dialect, "delimiter", ","),
            "hasHeader": has_header,
            "defaultPageSize": max(1, int(default_page_size or 50)),
        },
    }


def _cell_value(row: dict[str, Any], column_id: str) -> str:
    return str((row.get("cells") or {}).get(column_id) or "")


def _sort_value(value: str) -> tuple[int, float | str]:
    try:
        return (0, float(value))
    except ValueError:
        return (1, value.lower())


def query_csv_window(
    table: dict[str, Any],
    *,
    offset: int,
    limit: int,
    query: str = "",
    sort: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = list(table.get("rows") or [])
    keyword = query.strip().lower()
    if keyword:
        rows = [
            row
            for row in rows
            if keyword
            in " ".join(
                _cell_value(row, column["id"]).lower()
                for column in table.get("columns") or []
            )
        ]
    if sort and sort.get("columnId"):
        column_id = str(sort.get("columnId") or "")
        reverse = str(sort.get("direction") or "asc").lower() == "desc"
        rows = sorted(
            rows,
            key=lambda row: _sort_value(_cell_value(row, column_id)),
            reverse=reverse,
        )
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or table.get("metadata", {}).get("defaultPageSize") or 50))
    return {
        "offset": offset,
        "limit": limit,
        "totalRows": len(rows),
        "rows": rows[offset : offset + limit],
        "appliedSort": sort if sort else None,
    }
