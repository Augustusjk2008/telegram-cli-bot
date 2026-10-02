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
from bot.plugins.service import PluginService


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/hdl-workbench"


@pytest.fixture
def copied_plugin(tmp_path, monkeypatch):
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
    return copied, workspace, manifest


@pytest.mark.asyncio
async def test_copied_plugin_sessions_and_source_navigation(tmp_path, copied_plugin):
    _copied, workspace, manifest = copied_plugin
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


@pytest.mark.asyncio
async def test_refresh_clears_cached_tree_and_reanalyzes_nested_source(tmp_path, copied_plugin):
    copied, workspace, _manifest = copied_plugin
    service = PluginService(tmp_path, plugins_root=copied.parent, source_plugins_root=tmp_path / "empty-source",
                            workspace_root_for=lambda _alias: workspace)
    common = {"bot_alias": "main", "plugin_id": "hdl-workbench", "audit_context": {}}

    async def open_tree():
        return await service.open_view(**common, view_id="module-tree", input_payload={"path": "."})

    async def core_details(opened):
        roots = opened["initialWindow"]["nodes"]
        modules = await service.get_view_window(**common, session_id=opened["sessionId"],
                                               request_payload={"op": "children", "nodeId": roots[0]["id"]})
        top = next(node for node in modules["nodes"] if node["label"] == "system")
        instances = await service.get_view_window(**common, session_id=opened["sessionId"],
                                                 request_payload={"op": "children", "nodeId": top["id"]})
        instance = next(node for node in instances["nodes"] if node["label"] == "u_core : core")
        action = await service.invoke_action(**common, view_id="module-tree", session_id=opened["sessionId"],
                                             action_id="open-details", payload={"nodeId": instance["id"]})
        effect, = action["hostEffects"]
        return await service.open_view(**common, view_id="module-details", input_payload=effect["input"])

    async def declaration(opened):
        row = next(row for row in opened["initialWindow"]["rows"] if row["cells"]["name"] == "data")
        return await service.invoke_action(**common, view_id="module-details", session_id=opened["sessionId"],
                                           action_id="open-declaration", payload={"rowId": row["id"]})

    try:
        first = await open_tree()
        old_details = await core_details(first)
        directory_stat = workspace.stat()
        source = workspace / "include/core.svh"
        source.write_bytes(b"// nested edit\n" + source.read_bytes())
        os.utime(workspace, ns=(directory_stat.st_atime_ns, directory_stat.st_mtime_ns))
        # Root metadata does not reveal an edit inside an existing nested file.
        assert (await open_tree())["sessionId"] == first["sessionId"]
        assert (await declaration(old_details))["hostEffects"] == []

        refreshed = await service.invoke_action(**common, view_id="module-tree", session_id=first["sessionId"],
                                                action_id="refresh-project", payload={"path": "../forged"})
        assert refreshed["refresh"] == "view" and service.sessions.get_optional(first["sessionId"]) is None
        second = await open_tree()
        assert second["sessionId"] != first["sessionId"]
        new_details = await core_details(second)
        effect, = (await declaration(new_details))["hostEffects"]
        assert Path(effect["path"]).resolve() == source.resolve() and effect["line"] == 6
        # Detail tabs are independent snapshots until explicitly closed.
        assert (await declaration(old_details))["hostEffects"] == []
        for opened in (old_details, new_details, second):
            await service.dispose_view(**common, session_id=opened["sessionId"])
            assert service.sessions.get_optional(opened["sessionId"]) is None
    finally:
        await service.shutdown()
