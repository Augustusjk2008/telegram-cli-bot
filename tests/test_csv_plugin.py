from __future__ import annotations

import base64
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.runtime import PluginRuntime


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = REPO_ROOT / "examples/plugins/csv-preview"
BACKEND = PLUGIN / "backend"


@pytest.fixture
def plugin(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    spec = importlib.util.spec_from_file_location(
        "csv_preview_main_test", BACKEND / "main.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    module.shutdown()
    sys.modules.pop(spec.name, None)


def install_host(module, source: Path) -> list[dict]:
    calls: list[dict] = []

    def call_host(method: str, params: dict):
        calls.append({"method": method, "params": dict(params)})
        assert method == "host.workspace.read_range"
        content = source.read_bytes()
        offset = params["offset"]
        chunk = content[offset : offset + params["length"]]
        return {
            "result": {
                "path": str(source.resolve()),
                "offset": offset,
                "length": len(chunk),
                "fileSizeBytes": len(content),
                "mtimeNs": str(source.stat().st_mtime_ns),
                "contentBase64": base64.b64encode(chunk).decode("ascii"),
                "eof": offset + len(chunk) >= len(content),
            }
        }

    module.call_host = call_host
    return calls


def context(*, page_size: int = 50, header_mode: str = "auto", read_bytes: int = 1024 * 1024) -> dict:
    return {
        "plugin": {"config": {"defaultPageSize": page_size, "headerMode": header_mode}},
        "host": {"botAlias": "main", "limits": {"readBytes": read_bytes}},
    }


def test_open_dispose_cleans_index_and_session_ids_are_monotonic(plugin, tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("name,value\na,1\n", encoding="utf-8")
    install_host(plugin, source)

    first = plugin.open_view({"path": str(source)}, context(header_mode="header"))
    resource = plugin.SESSIONS[first["sessionId"]].resource
    source_dir = Path(resource.source.directory.name)
    assert source_dir.exists()
    assert first["summary"]["totalRows"] == 1

    assert plugin.dispose_view({"sessionId": first["sessionId"]}) == {"disposed": True}
    assert not source_dir.exists()

    second = plugin.open_view({"path": str(source)}, context(header_mode="header"))
    assert second["sessionId"] != first["sessionId"]
    assert int(second["sessionId"].rsplit("-", 1)[-1]) > int(first["sessionId"].rsplit("-", 1)[-1])
    plugin.dispose_view({"sessionId": second["sessionId"]})


def test_same_source_reuses_index_until_last_session_closes(plugin, tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("name,value\na,1\nb,2\n", encoding="utf-8")
    calls = install_host(plugin, source)

    first = plugin.open_view({"path": str(source)}, context())
    second = plugin.open_view({"path": str(source)}, context())
    first_resource = plugin.SESSIONS[first["sessionId"]].resource
    second_resource = plugin.SESSIONS[second["sessionId"]].resource

    assert first_resource is second_resource
    assert len(plugin.RESOURCES) == 1
    plugin.dispose_view({"sessionId": first["sessionId"]})
    assert len(plugin.RESOURCES) == 1
    plugin.dispose_view({"sessionId": second["sessionId"]})
    assert not plugin.RESOURCES
    assert len(calls) >= 2


def test_source_hash_change_rebuilds_index(plugin, tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("value\none\n", encoding="utf-8")
    install_host(plugin, source)
    first = plugin.open_view({"path": str(source)}, context(header_mode="header"))
    old_mtime = source.stat().st_mtime_ns

    source.write_text("value\ntwo\n", encoding="utf-8")
    os.utime(source, ns=(old_mtime, old_mtime))
    second = plugin.open_view({"path": str(source)}, context(header_mode="header"))

    assert first["sessionId"] != second["sessionId"]
    assert len(plugin.RESOURCES) == 2
    rows = plugin.get_view_window({"sessionId": second["sessionId"], "offset": 0, "limit": 1})["rows"]
    assert rows[0]["cells"]["value"] == "two"


def test_failed_index_does_not_leave_session_or_partial_resource(plugin, tmp_path: Path) -> None:
    source = tmp_path / "broken.csv"
    source.write_text('"unterminated\n', encoding="utf-8")
    install_host(plugin, source)

    with pytest.raises(ValueError, match="CSV 文件损坏"):
        plugin.open_view({"path": str(source)}, context())

    assert not plugin.SESSIONS
    assert not plugin.RESOURCES


def test_plugin_shutdown_cleans_all_open_resources(plugin, tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("1,2\n3,4\n", encoding="utf-8")
    install_host(plugin, source)
    first = plugin.open_view({"path": str(source)}, context(header_mode="no-header"))
    second = plugin.open_view({"path": str(source)}, context(header_mode="header"))
    directories = [
        Path(plugin.SESSIONS[item["sessionId"]].resource.source.directory.name)
        for item in (first, second)
    ]

    plugin.shutdown()

    assert not plugin.SESSIONS
    assert not plugin.RESOURCES
    assert all(not directory.exists() for directory in directories)


@pytest.mark.asyncio
async def test_real_stdio_plugin_supports_range_copy_paging_and_dispose(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("name,value\na,1\nb,2\n", encoding="utf-8")
    manifest = load_plugin_manifest(PLUGIN / "plugin.json")
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: tmp_path,
        host_api=PluginHostApi(ArtifactStore(tmp_path)),
        call_timeout_seconds=10,
    )
    try:
        opened = await runtime.open_view("main", manifest, "csv-table", {"path": "data.csv"})
        assert opened["summary"]["totalRows"] == 2
        assert [row["cells"]["name"] for row in opened["initialWindow"]["rows"]] == ["a", "b"]
        window = await runtime.get_view_window(
            "main",
            manifest,
            opened["sessionId"],
            {"offset": 0, "limit": 1, "query": "b"},
        )
        assert window["totalRows"] == 1
        assert [row["cells"]["name"] for row in window["rows"]] == ["b"]
        assert (await runtime.dispose_view("main", manifest, opened["sessionId"]))["disposed"] is True
    finally:
        await runtime.shutdown()
