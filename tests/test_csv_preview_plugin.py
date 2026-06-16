from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from bot.plugins.registry import PluginRegistry
from bot.plugins.service import PluginService


def _load_csv_parser():
    parser_path = Path("examples/plugins/csv-preview/backend/csv_parser.py")
    spec = importlib.util.spec_from_file_location("csv_preview_parser", parser_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_csv_parser_handles_bom_gb18030_quotes_and_multiline() -> None:
    parser = _load_csv_parser()

    bom_table = parser.parse_csv_table(
        "bom.csv",
        b'\xef\xbb\xbfname,note\nAlice,"hello\nworld"\n',
        default_page_size=20,
    )
    assert bom_table["metadata"]["encoding"] == "utf-8-sig"
    assert bom_table["rows"][0]["cells"]["note"] == "hello\nworld"

    gb_table = parser.parse_csv_table(
        "gb.csv",
        "姓名,城市\n张三,南京\n".encode("gb18030"),
        default_page_size=20,
    )
    assert gb_table["metadata"]["encoding"] == "gb18030"
    assert [column["title"] for column in gb_table["columns"]] == ["姓名", "城市"]
    assert gb_table["rows"][0]["cells"]["column_1"] == "张三"


def test_csv_parser_normalizes_empty_and_duplicate_headers() -> None:
    parser = _load_csv_parser()

    table = parser.parse_csv_table(
        "headers.csv",
        b",Name,Name,\n1,Alice,Admin,x\n",
        default_page_size=20,
    )

    assert [column["id"] for column in table["columns"]] == [
        "column_1",
        "name",
        "name_2",
        "column_4",
    ]
    assert [column["title"] for column in table["columns"]] == [
        "Column 1",
        "Name",
        "Name (2)",
        "Column 4",
    ]
    assert table["rows"][0]["cells"]["name_2"] == "Admin"


def test_csv_window_query_sort_and_paging() -> None:
    parser = _load_csv_parser()
    table = parser.parse_csv_table(
        "scores.csv",
        b"name,score\nAlice,7\nBob,12\nCarol,5\n",
        default_page_size=2,
    )

    window = parser.query_csv_window(
        table,
        offset=0,
        limit=1,
        query="o",
        sort={"columnId": "score", "direction": "desc"},
    )

    assert window["totalRows"] == 2
    assert window["rows"][0]["cells"] == {"name": "Bob", "score": "12"}
    assert window["appliedSort"] == {"columnId": "score", "direction": "desc"}


def test_csv_preview_manifest_resolves_csv_to_table_view() -> None:
    registry = PluginRegistry(Path("examples/plugins"))
    manifest = registry.discover()["csv-preview"]
    resolution = registry.resolve_file_handler("data/report.csv")

    assert manifest.schema_version == 2
    assert manifest.views[0].renderer == "table"
    assert manifest.views[0].view_mode == "session"
    assert manifest.views[0].data_profile == "heavy"
    assert resolution is not None
    assert resolution.plugin_id == "csv-preview"
    assert resolution.view_id == "csv-table"


@pytest.mark.asyncio
async def test_csv_preview_plugin_opens_and_queries_table_session(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    plugins_root.mkdir(parents=True)
    shutil.copytree(Path("examples/plugins/csv-preview"), plugins_root / "csv-preview")

    csv_path = repo_root / "scores.csv"
    csv_path.write_text("name,score\nAlice,7\nBob,12\nCarol,5\n", encoding="utf-8")

    service = PluginService(repo_root, plugins_root=plugins_root)
    view = await service.open_view(
        bot_alias="main",
        plugin_id="csv-preview",
        view_id="csv-table",
        input_payload={"path": str(csv_path)},
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )
    window = await service.get_view_window(
        bot_alias="main",
        plugin_id="csv-preview",
        session_id=view["sessionId"],
        request_payload={
            "offset": 0,
            "limit": 1,
            "query": "o",
            "sort": {"columnId": "score", "direction": "desc"},
        },
        audit_context={"account_id": "member_1", "bot_alias": "main"},
    )

    assert view["renderer"] == "table"
    assert view["mode"] == "session"
    assert view["summary"]["totalRows"] == 3
    assert view["initialWindow"]["rows"][0]["cells"]["name"] == "Alice"
    assert window["totalRows"] == 2
    assert window["rows"][0]["cells"]["name"] == "Bob"
    await service.shutdown()
