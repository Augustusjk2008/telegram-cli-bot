from __future__ import annotations

import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest


BACKEND = Path(__file__).resolve().parents[1] / "examples/plugins/zip-preview/backend"


@pytest.fixture
def plugin(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    for name, filename in (
        ("plugin_sdk", "plugin_sdk.py"),
        ("zip_parser", "zip_parser.py"),
        ("zip_preview_main_test", "main.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, BACKEND / filename)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    yield module
    module.shutdown()


def zip_bytes(entries: list[tuple[str, str]]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, text in entries:
            archive.writestr(name, text)
    return buffer.getvalue()


def install_host(plugin, monkeypatch, sources: dict[str, bytes]) -> list[str]:
    calls: list[str] = []

    def read_bytes(path: str, *, error_message: str) -> bytes:
        calls.append(path)
        return sources[path]

    monkeypatch.setattr(plugin.server, "read_bytes", read_bytes)
    return calls


def children(plugin, session_id: str, node_id: str | None = None) -> list[dict]:
    return plugin.get_view_window({"sessionId": session_id, "op": "children", "nodeId": node_id})["nodes"]


def test_open_returns_only_roots_and_expands_one_level_at_a_time(plugin, monkeypatch) -> None:
    calls = install_host(plugin, monkeypatch, {
        "sample.zip": zip_bytes([
            ("folder/deep/secret.txt", "secret"),
            ("folder/direct.txt", "direct"),
            ("README.md", "readme"),
        ]),
    })
    opened = plugin.open_view({"path": "sample.zip"})
    assert opened["mode"] == "session"
    assert opened["renderer"] == "tree"
    roots = opened["summary"]["roots"]
    assert [node["label"] for node in roots] == ["folder", "README.md"]
    assert opened["initialWindow"] == {"op": "children", "nodeId": None, "nodes": roots}
    assert all(not node.get("children") for node in roots)
    assert "secret.txt" not in json.dumps(opened)
    session_id = opened["sessionId"]
    folder = children(plugin, session_id, "dir:folder")
    assert [node["label"] for node in folder] == ["deep", "direct.txt"]
    assert all(not node.get("children") for node in folder)
    assert [node["label"] for node in children(plugin, session_id, "dir:folder/deep")] == ["secret.txt"]
    assert children(plugin, session_id) == roots
    assert calls == ["sample.zip"]


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_duplicate_members_have_distinct_ids_and_metadata(plugin, monkeypatch) -> None:
    install_host(plugin, monkeypatch, {
        "duplicate.zip": zip_bytes([("folder/same.txt", "a"), ("folder/same.txt", "bbb")]),
    })
    opened = plugin.open_view({"path": "duplicate.zip"})
    nodes = children(plugin, opened["sessionId"], "dir:folder")
    assert [node["label"] for node in nodes] == ["same.txt", "same.txt"]
    assert [node["id"] for node in nodes] == ["file:0:folder/same.txt", "file:1:folder/same.txt"]
    assert [node["payload"]["size"] for node in nodes] == [1, 3]


@pytest.mark.parametrize(("configured_limit", "limit"), [(100, 100), (1, 100), (100_000, 10_000)])
def test_entry_limits_select_files_in_archive_order_for_sessions_and_snapshots(
    plugin, monkeypatch, configured_limit: int, limit: int,
) -> None:
    content = zip_bytes(
        [("ignored/", "")]
        + [(f"folder/items/file-{index:05}.txt", "") for index in range(limit + 1)]
        + [("late/unselected.txt", "")],
    )
    install_host(plugin, monkeypatch, {"limited.zip": content})
    plugin.server.config["maxEntries"] = configured_limit
    opened = plugin.open_view({"path": "limited.zip"})
    session_id = opened["sessionId"]
    assert [node["id"] for node in opened["summary"]["roots"]] == ["dir:folder"]
    assert opened["summary"]["statsText"] == f"{limit} 文件 · 2 文件夹 · 仅预览前 {limit} 项"
    nodes = children(plugin, session_id, "dir:folder/items")
    assert len(nodes) == limit
    assert nodes[0]["id"] == "file:1:folder/items/file-00000.txt"
    assert nodes[-1]["label"] == f"file-{limit - 1:05}.txt"
    with pytest.raises(RuntimeError, match="目录节点不存在"):
        children(plugin, session_id, "dir:late")
    snapshot = plugin.render_view({"path": "limited.zip"})
    assert snapshot["payload"]["statsText"] == opened["summary"]["statsText"]
    assert len(snapshot["payload"]["roots"][0]["children"][0]["children"]) == limit


@pytest.mark.parametrize("entries", [[], [("empty/", "")]])
def test_empty_archives_keep_the_existing_file_selection_rules(plugin, monkeypatch, entries) -> None:
    install_host(plugin, monkeypatch, {"empty.zip": zip_bytes(entries)})
    opened = plugin.open_view({"path": "empty.zip"})
    assert opened["summary"]["roots"] == []
    assert opened["summary"]["statsText"] == "0 文件 · 0 文件夹"
    assert opened["summary"]["searchable"] is False
    assert children(plugin, opened["sessionId"]) == []


def test_invalid_archive_does_not_create_a_session(plugin, monkeypatch) -> None:
    install_host(plugin, monkeypatch, {"invalid.zip": b"not a zip"})
    with pytest.raises(RuntimeError, match="ZIP 文件损坏"):
        plugin.open_view({"path": "invalid.zip"})
    assert not plugin.SESSIONS


def test_node_queries_are_limited_to_the_current_session_index(plugin, monkeypatch) -> None:
    calls = install_host(plugin, monkeypatch, {
        "first.zip": zip_bytes([("first/file.txt", "one")]),
        "second.zip": zip_bytes([("second/file.txt", "two")]),
    })
    first = plugin.open_view({"path": "first.zip"})["sessionId"]
    second = plugin.open_view({"path": "second.zip"})["sessionId"]
    for node_id in ("dir:first", "dir:missing", "", "dir:", "file:0:second/file.txt", "../../outside"):
        with pytest.raises(RuntimeError, match="目录节点不存在"):
            children(plugin, second, node_id)
    assert [node["label"] for node in children(plugin, first, "dir:first")] == ["file.txt"]
    assert [node["label"] for node in children(plugin, second, "dir:second")] == ["file.txt"]
    with pytest.raises(RuntimeError, match="children"):
        plugin.get_view_window({"sessionId": first, "op": "search"})
    with pytest.raises(RuntimeError, match="会话不存在或已释放"):
        children(plugin, "missing-session")
    assert calls == ["first.zip", "second.zip"]


def test_dispose_is_idempotent_and_shutdown_keeps_session_ids_monotonic(plugin, monkeypatch) -> None:
    install_host(plugin, monkeypatch, {"sample.zip": zip_bytes([("file.txt", "data")])})
    first = plugin.open_view({"path": "sample.zip"})["sessionId"]
    assert plugin.dispose_view({"sessionId": first}) == {"disposed": True}
    assert plugin.dispose_view({"sessionId": first}) == {"disposed": False}
    with pytest.raises(RuntimeError, match="会话不存在或已释放"):
        children(plugin, first)
    second = plugin.open_view({"path": "sample.zip"})["sessionId"]
    plugin.shutdown()
    plugin.shutdown()
    assert not plugin.SESSIONS
    with pytest.raises(RuntimeError, match="会话不存在或已释放"):
        children(plugin, second)
    third = plugin.open_view({"path": "sample.zip"})["sessionId"]
    assert int(first.rsplit("-", 1)[-1]) < int(second.rsplit("-", 1)[-1]) < int(third.rsplit("-", 1)[-1])
