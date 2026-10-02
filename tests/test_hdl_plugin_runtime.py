from __future__ import annotations

import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from bot.plugins.artifacts import ArtifactStore
from bot.plugins.host_api import PluginHostApi
from bot.plugins.manifest import load_plugin_manifest
from bot.plugins import runtime as runtime_module
from bot.plugins.runtime import PluginRuntime


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/hdl-workbench"


@pytest.mark.asyncio
async def test_copied_plugin_sessions_and_source_navigation(tmp_path, monkeypatch):
    # Let the Host tests use a separate interpreter with the optional HDL dependencies.
    child_python = os.environ.get("HDL_PLUGIN_TEST_PYTHON")
    if child_python:
        executable = Path(child_python).resolve(strict=True)
        monkeypatch.setattr(runtime_module, "sys", SimpleNamespace(executable=str(executable)))
    else:
        pytest.importorskip("tree_sitter")
        pytest.importorskip("tree_sitter_verilog")

    copied = tmp_path / "plugins/hdl-workbench"
    shutil.copytree(PLUGIN, copied, ignore=shutil.ignore_patterns("__pycache__"))
    workspace = tmp_path / "workspace"
    shutil.copytree(copied / "samples/project", workspace)
    manifest = load_plugin_manifest(copied / "plugin.json")
    runtime = PluginRuntime(
        workspace_root_for=lambda _alias: workspace,
        host_api=PluginHostApi(ArtifactStore(tmp_path)),
        call_timeout_seconds=15,
    )

    async def children(session_id, node_id):
        return (await runtime.get_view_window(
            "main", manifest, session_id, {"op": "children", "nodeId": node_id},
        ))["nodes"]

    try:
        tree = await runtime.open_view("main", manifest, "module-tree", {"path": "."})
        assert tree["mode"] == "session" and tree["renderer"] == "tree"
        roots = tree["initialWindow"]["nodes"]
        tops = next(node for node in roots if node["label"] == "候选顶层")
        modules = await children(tree["sessionId"], tops["id"])
        system = next(node for node in modules if node["label"].startswith("system"))
        instances = await children(tree["sessionId"], system["id"])
        instance = next(node for node in instances if node["label"].startswith("u_core"))
        details_action = await runtime.invoke_action(
            "main", manifest, view_id="module-tree", session_id=tree["sessionId"],
            action_id="open-details", payload={"nodeId": instance["id"]},
        )
        effect, = details_action["hostEffects"]
        assert effect["type"] == "open_plugin_view" and effect["viewId"] == "module-details"
        details = await runtime.open_view("main", manifest, effect["viewId"], effect["input"])
        page = await runtime.get_view_window(
            "main", manifest, details["sessionId"], {"offset": 1, "limit": 1},
        )
        row, = page["rows"]
        assert row["cells"]["name"] == "data" and page["totalRows"] == 3
        opened = await runtime.invoke_action(
            "main", manifest, view_id="module-details", session_id=details["sessionId"],
            action_id="open-declaration", payload={"rowId": row["id"], "path": "untrusted.v", "line": 999},
        )
        source, = opened["hostEffects"]
        assert source["type"] == "open_file"
        assert Path(source["path"]).resolve() == (workspace / "include/core.svh").resolve()
        assert source["line"] == 5

        assert (await runtime.dispose_view("main", manifest, tree["sessionId"]))["disposed"]
        # A detail tab remains usable after closing its originating hierarchy tab.
        assert (await runtime.get_view_window(
            "main", manifest, details["sessionId"], {"offset": 2, "limit": 1},
        ))["totalRows"] == 3
        assert (await runtime.dispose_view("main", manifest, details["sessionId"]))["disposed"]
        with pytest.raises(RuntimeError, match="会话"):
            await runtime.get_view_window("main", manifest, details["sessionId"], {"offset": 0, "limit": 1})
    finally:
        await runtime.shutdown()
