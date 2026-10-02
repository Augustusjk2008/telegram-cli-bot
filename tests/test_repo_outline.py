from __future__ import annotations

import importlib.util
import shutil
import sys
from io import StringIO
from pathlib import Path

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins.runtime import PluginRuntime


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/repo-outline"


@pytest.fixture
def outline(monkeypatch):
    spec = importlib.util.spec_from_file_location("tested_repo_outline", PLUGIN / "backend/main.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    monkeypatch.setattr(sys, "stdin", StringIO(""))
    spec.loader.exec_module(module)
    return module


def entry(name: str, *, directory: bool = False) -> dict:
    return {"name": name, "isDir": directory}


def session(outline, **config):
    return outline.build_session("test", {"plugin": {"config": config}}, {})


def test_search_skips_dependency_and_build_directories(outline, monkeypatch):
    state = session(outline, includeHidden=True)
    calls = []

    def host(method, params, _error):
        calls.append((method, params["path"]))
        if method == "host.workspace.list_dir":
            return {"entries": {
                ".": [
                    entry(name, directory=True)
                    for name in (".git", "Node_Modules", "venv", ".venv", "__pycache__", "dist", "build", "src")
                ] + [entry("node_modules.py")],
                "src": [entry("needle.py")],
            }[params["path"]]}
        return {"items": []}

    monkeypatch.setattr(outline, "host_result", host)
    payload = outline.search_workspace(state, "needle")
    assert [node["id"] for node in payload["nodes"]] == ["file:src/needle.py"]
    assert [path for method, path in calls if method.endswith("list_dir")] == [".", "src"]
    assert {path for method, path in calls if method.endswith("outline")} == {"node_modules.py", "src/needle.py"}
    assert outline.search_workspace(state, "needle") == payload
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("ignored", "visible"),
    [("", ["generated", "node_modules"]), (" GENERATED, node_modules ", [])],
)
def test_ignored_directory_setting_can_be_cleared_or_overridden(outline, monkeypatch, ignored, visible):
    monkeypatch.setattr(outline, "host_result", lambda *_args: {
        "entries": [entry("generated", directory=True), entry("node_modules", directory=True)],
    })
    nodes = outline.get_directory_children(session(outline, ignoreDirectories=ignored), ".")
    assert [node["label"] for node in nodes] == visible


@pytest.mark.parametrize("path", [".", "src"])
def test_truncated_directory_warns_in_tree_and_search(outline, monkeypatch, path):
    def host(method, params, _error):
        if method == "host.workspace.list_dir":
            if path == "src" and params["path"] == ".":
                return {"entries": [entry("src", directory=True)]}
            return {"entries": [entry("needle.py")], "truncated": True}
        return {"items": []}

    monkeypatch.setattr(outline, "host_result", host)
    opened = outline.open_view({}, {})
    nodes = outline.get_view_window({
        "sessionId": opened["sessionId"], "op": "children", "nodeId": f"dir:{path}",
    })["nodes"]
    notice = nodes[-1]
    assert notice["id"] == f"notice:{path}"
    assert "读取上限" in notice["secondaryText"]
    assert not notice["hasChildren"] and not notice.get("actions")
    for query in ("needle", ""):
        result = outline.get_view_window({
            "sessionId": opened["sessionId"], "op": "search", "query": query,
        })
        assert "未完整显示" in result["statsText"]


@pytest.mark.parametrize("extra", [None, "file", "directory"])
def test_file_scan_limit_only_warns_when_content_remains(outline, monkeypatch, extra):
    entries = [entry("needle.py")]
    if extra:
        entries.append(entry("other.py" if extra == "file" else "src", directory=extra == "directory"))
    monkeypatch.setattr(outline, "host_result", lambda method, *_args: {
        "entries": entries,
    } if method.endswith("list_dir") else {"items": []})
    state = session(outline)
    state.max_files = 1
    result = outline.search_workspace(state, "needle")
    assert len(result["nodes"]) == 1
    assert ("文件上限" in result["statsText"]) == bool(extra)


@pytest.mark.parametrize("file_count", [2, 3])
def test_search_result_limit_marks_unsearched_files(outline, monkeypatch, file_count):
    monkeypatch.setattr(outline, "SEARCH_RESULT_LIMIT", 2)
    monkeypatch.setattr(outline, "host_result", lambda method, *_args: {
        "entries": [entry(f"needle-{index}.py") for index in range(file_count)],
    } if method.endswith("list_dir") else {"items": []})
    result = outline.search_workspace(session(outline), "needle")
    assert len(result["nodes"]) == 2
    assert ("结果上限" in result["statsText"]) == (file_count > 2)


@pytest.mark.asyncio
async def test_repo_outline_runs_from_copied_plugin_directory(tmp_path: Path):
    plugin_dir = tmp_path / "plugins/repo-outline"
    shutil.copytree(PLUGIN, plugin_dir)
    workspace = tmp_path / "workspace"
    for folder in ("src", "node_modules"):
        directory = workspace / folder
        directory.mkdir(parents=True)
        (directory / "sample.py").write_text("def needle():\n    pass\n", encoding="utf-8")

    manifest = load_plugin_manifest(plugin_dir / "plugin.json")
    fields = {field.key for section in manifest.config_schema.sections for field in section.fields}
    assert "ignoreDirectories" in fields
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(ArtifactStore(tmp_path)),
        call_timeout_seconds=10,
    )
    try:
        opened = await runtime.open_view("main", manifest, "repo-tree", {})
        result = await runtime.get_view_window("main", manifest, opened["sessionId"], {
            "op": "search", "query": "needle",
        })
        assert [node["id"] for node in result["nodes"]] == ["file:src/sample.py"]
        assert result["nodes"][0]["children"][0]["actions"][0]["hostAction"] == {
            "type": "open_file", "path": "src/sample.py", "line": 1,
        }
        disposed = await runtime.dispose_view("main", manifest, opened["sessionId"])
        assert disposed["disposed"] is True
    finally:
        await runtime.shutdown()
